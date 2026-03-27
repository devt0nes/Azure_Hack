"""
Cosmos DB Client for Azure Cosmos DB operations
Handles connection, container creation, and CRUD operations
"""

import os
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import time
from pathlib import Path
from dotenv import load_dotenv

# Ensure local .env is loaded when this module is used standalone (e.g. python -c / scripts).
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=False)

logger = logging.getLogger(__name__)


class CosmosDBClient:
    """
    Azure Cosmos DB client for managing containers and documents.
    Automatically creates containers and performs CRUD operations.
    """

    def __init__(self, connection_string: str = None, db_name: str = None):
        """
        Initialize Cosmos DB client
        
        Args:
            connection_string: Azure Cosmos DB connection string
            db_name: Database name (default: from env COSMOS_DB_NAME)
        """
        try:
            from azure.cosmos import CosmosClient, PartitionKey, exceptions
            self.CosmosClient = CosmosClient
            self.PartitionKey = PartitionKey
            self.exceptions = exceptions
        except ImportError:
            raise RuntimeError(
                "azure-cosmos package is not installed. "
                "Install it with: pip install azure-cosmos"
            )

        self.connection_string = connection_string or os.getenv("COSMOS_CONNECTION_STR")
        self.db_name = db_name or os.getenv("COSMOS_DB_NAME", "agentic-nexus-db")

        if not self.connection_string:
            raise ValueError(
                "COSMOS_CONNECTION_STR environment variable is not set. "
                "Please provide a valid connection string."
            )

        self.client = None
        self.database = None
        self._is_connected = False
        self._container_partition_keys: Dict[str, str] = {}

        logger.info(f"CosmosDB client initialized for database: {self.db_name}")

    def connect(self) -> bool:
        """
        Establish connection to Cosmos DB and create database if needed.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            logger.info("Connecting to Cosmos DB...")
            self.client = self.CosmosClient.from_connection_string(self.connection_string)

            # Idempotent database creation
            self.database = self.client.create_database_if_not_exists(id=self.db_name)
            logger.info(f"✓ Connected to database: {self.db_name}")

            self._is_connected = True
            return True

        except Exception as e:
            logger.error(f"✗ Failed to connect to Cosmos DB: {str(e)}")
            self._is_connected = False
            return False

    def is_connected(self) -> bool:
        """Check if client is connected to Cosmos DB"""
        return self._is_connected and self.database is not None

    def create_container(
        self,
        container_name: str,
        partition_key: str = "/id",
        throughput: int = 400
    ) -> bool:
        """
        Create a container if it doesn't exist.
        
        Args:
            container_name: Name of the container
            partition_key: Partition key path (default: /id)
            throughput: RU/s for the container (default: 400)
            
        Returns:
            bool: True if container created or already exists, False on error
        """
        if not self.is_connected():
            logger.error("Not connected to Cosmos DB")
            return False

        try:
            logger.info(f"Ensuring container exists: {container_name} ({partition_key})")
            try:
                container = self.database.create_container_if_not_exists(
                    id=container_name,
                    partition_key=self.PartitionKey(path=partition_key),
                    offer_throughput=throughput,
                )
            except Exception as exc:
                msg = str(exc)
                if "serverless" in msg.lower() and "throughput" in msg.lower():
                    logger.info(
                        "Serverless Cosmos account detected; retrying container creation without offer_throughput"
                    )
                    container = self.database.create_container_if_not_exists(
                        id=container_name,
                        partition_key=self.PartitionKey(path=partition_key),
                    )
                else:
                    raise

            # Container creation can be eventually consistent; probe until metadata is readable.
            self._wait_for_container_ready(container_name)
            self._container_partition_keys[container_name] = partition_key
            logger.info(f"✓ Container ready: {container_name}")
            return True

        except Exception as e:
            logger.error(f"✗ Failed to create container {container_name}: {str(e)}")
            return False

    def _wait_for_container_ready(self, container_name: str, timeout_seconds: float = 15.0) -> None:
        start = time.time()
        last_error: Optional[Exception] = None
        while (time.time() - start) < timeout_seconds:
            try:
                container = self.database.get_container_client(container_name)
                props = container.read()
                partition_path = (props.get("partitionKey") or {}).get("paths", ["/id"])[0]
                self._container_partition_keys[container_name] = partition_path
                return
            except Exception as exc:
                last_error = exc
                time.sleep(0.5)
        if last_error:
            raise last_error

    def _default_container_config(self) -> Dict[str, str]:
        template_container = os.getenv("COSMOS_TEMPLATE_CONTAINER") or os.getenv("COSMOS_TEMPLATE_CONTAINTER", "TemplateLibrary")
        starter_template_container = os.getenv("COSMOS_STARTER_TEMPLATE_CONTAINER", "starter_templates")
        return {
            os.getenv("LEDGER_CONTAINER", "TaskLedgers"): "/task_id",
            os.getenv("AGENT_CONTAINER", "AgentRegistry"): "/agent_id",
            template_container: "/template_id",
            starter_template_container: "/template_id",
        }

    def _infer_partition_path(self, container_name: str) -> str:
        if container_name in self._container_partition_keys:
            return self._container_partition_keys[container_name]

        # Known defaults first
        known = self._default_container_config().get(container_name)
        if known:
            self._container_partition_keys[container_name] = known
            return known

        # Fallback to reading container metadata
        try:
            container = self.database.get_container_client(container_name)
            props = container.read()
            path = (props.get("partitionKey") or {}).get("paths", ["/id"])[0]
            self._container_partition_keys[container_name] = path
            return path
        except Exception:
            # Safe fallback used by most generic containers
            return "/id"

    def _resolve_partition_value(self, container_name: str, document: Dict[str, Any], document_id: str) -> str:
        partition_path = self._infer_partition_path(container_name)
        key = partition_path.lstrip("/")

        if key not in document:
            # Auto-backfill expected partition key value for known containers
            document[key] = document.get("id", document_id)

        value = document.get(key)
        if value is None:
            raise ValueError(f"Partition key '{partition_path}' missing for container '{container_name}'")
        return str(value)

    def ensure_containers(self) -> Dict[str, bool]:
        """
        Ensure all required containers exist.
        
        Returns:
            dict: Status of each container creation
        """
        if not self.is_connected():
            logger.error("Not connected to Cosmos DB")
            return {}

        containers_config = self._default_container_config()

        results = {}
        for container_name, partition_key in containers_config.items():
            results[container_name] = self.create_container(
                container_name=container_name,
                partition_key=partition_key,
                throughput=400
            )

        return results

    def insert_document(
        self,
        container_name: str,
        document: Dict[str, Any]
    ) -> Optional[Dict]:
        """
        Insert a document into a container.
        
        Args:
            container_name: Name of the container
            document: Document to insert (must have 'id' field)
            
        Returns:
            dict: Created document or None on error
        """
        if not self.is_connected():
            logger.error("Not connected to Cosmos DB")
            return None

        try:
            container = self.database.get_container_client(container_name)
            
            # Ensure document has required fields
            if "id" not in document:
                document["id"] = str(datetime.now().timestamp())
            if "created_at" not in document:
                document["created_at"] = datetime.now().isoformat()

            self._resolve_partition_value(container_name, document, document["id"])
            result = container.upsert_item(body=document)
            logger.info(f"✓ Inserted document into {container_name}: {document.get('id')}")
            return result

        except self.exceptions.CosmosResourceExistsError:
            logger.warning(f"Document with id {document.get('id')} already exists")
            return document
        except Exception as e:
            logger.error(f"✗ Failed to insert document: {str(e)}")
            return None

    def query_documents(
        self,
        container_name: str,
        query: str,
        parameters: List[Dict] = None
    ) -> List[Dict]:
        """
        Query documents from a container.
        
        Args:
            container_name: Name of the container
            query: SQL query string
            parameters: Query parameters
            
        Returns:
            list: Query results
        """
        if not self.is_connected():
            logger.error("Not connected to Cosmos DB")
            return []

        try:
            container = self.database.get_container_client(container_name)
            results = list(container.query_items(
                query=query,
                parameters=parameters or [],
                enable_cross_partition_query=True
            ))
            logger.info(f"✓ Queried {len(results)} documents from {container_name}")
            return results

        except Exception as e:
            logger.error(f"✗ Failed to query documents: {str(e)}")
            return []

    def get_document(
        self,
        container_name: str,
        document_id: str,
        partition_key: str = None
    ) -> Optional[Dict]:
        """
        Get a document by ID.
        
        Args:
            container_name: Name of the container
            document_id: Document ID
            partition_key: Partition key value (default: same as document_id)
            
        Returns:
            dict: Document or None if not found
        """
        if not self.is_connected():
            logger.error("Not connected to Cosmos DB")
            return None

        try:
            container = self.database.get_container_client(container_name)
            if partition_key:
                partition_key_value = partition_key
            else:
                partition_path = self._infer_partition_path(container_name)
                # If partition key is not /id and caller didn't pass it, cross-partition query by id.
                if partition_path != "/id":
                    docs = list(container.query_items(
                        query="SELECT TOP 1 * FROM c WHERE c.id = @id",
                        parameters=[{"name": "@id", "value": document_id}],
                        enable_cross_partition_query=True,
                    ))
                    if not docs:
                        logger.warning(f"Document not found: {document_id}")
                        return None
                    return docs[0]
                partition_key_value = document_id

            result = container.read_item(item=document_id, partition_key=partition_key_value)
            logger.info(f"✓ Retrieved document from {container_name}: {document_id}")
            return result

        except self.exceptions.CosmosResourceNotFoundError:
            logger.warning(f"Document not found: {document_id}")
            return None
        except Exception as e:
            logger.error(f"✗ Failed to get document: {str(e)}")
            return None

    def update_document(
        self,
        container_name: str,
        document_id: str,
        updates: Dict[str, Any],
        partition_key: str = None
    ) -> Optional[Dict]:
        """
        Update a document.
        
        Args:
            container_name: Name of the container
            document_id: Document ID
            updates: Fields to update
            partition_key: Partition key value
            
        Returns:
            dict: Updated document or None on error
        """
        if not self.is_connected():
            logger.error("Not connected to Cosmos DB")
            return None

        try:
            # Get existing document
            document = self.get_document(container_name, document_id, partition_key)
            if not document:
                logger.warning(f"Document not found for update: {document_id}")
                return None

            # Update fields
            document.update(updates)
            document["updated_at"] = datetime.now().isoformat()

            # Replace document
            container = self.database.get_container_client(container_name)
            if partition_key:
                partition_key_value = partition_key
            else:
                partition_key_value = self._resolve_partition_value(container_name, document, document_id)
            result = container.replace_item(item=document_id, body=document, partition_key=partition_key_value)
            logger.info(f"✓ Updated document in {container_name}: {document_id}")
            return result

        except Exception as e:
            logger.error(f"✗ Failed to update document: {str(e)}")
            return None

    def delete_document(
        self,
        container_name: str,
        document_id: str,
        partition_key: str = None
    ) -> bool:
        """
        Delete a document.
        
        Args:
            container_name: Name of the container
            document_id: Document ID
            partition_key: Partition key value
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_connected():
            logger.error("Not connected to Cosmos DB")
            return False

        try:
            container = self.database.get_container_client(container_name)
            if partition_key:
                partition_key_value = partition_key
            else:
                doc = self.get_document(container_name, document_id)
                if not doc:
                    logger.warning(f"Document not found for deletion: {document_id}")
                    return True
                partition_key_value = self._resolve_partition_value(container_name, doc, document_id)
            container.delete_item(item=document_id, partition_key=partition_key_value)
            logger.info(f"✓ Deleted document from {container_name}: {document_id}")
            return True

        except self.exceptions.CosmosResourceNotFoundError:
            logger.warning(f"Document not found for deletion: {document_id}")
            return True  # Already deleted
        except Exception as e:
            logger.error(f"✗ Failed to delete document: {str(e)}")
            return False

    def list_containers(self) -> List[str]:
        """
        List all containers in the database.
        
        Returns:
            list: Container names
        """
        if not self.is_connected():
            logger.error("Not connected to Cosmos DB")
            return []

        try:
            containers = list(self.database.list_containers())
            container_names = [c["id"] for c in containers]
            logger.info(f"✓ Found {len(container_names)} containers: {container_names}")
            return container_names

        except Exception as e:
            logger.error(f"✗ Failed to list containers: {str(e)}")
            return []

    def health_check(self) -> Dict[str, Any]:
        """
        Perform a health check on the Cosmos DB connection.
        
        Returns:
            dict: Health status information
        """
        status = {
            "connected": self.is_connected(),
            "database": self.db_name,
            "containers": [],
            "error": None
        }

        if not self.is_connected():
            status["error"] = "Not connected to Cosmos DB"
            return status

        try:
            status["containers"] = self.list_containers()
            status["timestamp"] = datetime.now().isoformat()
        except Exception as e:
            status["error"] = str(e)

        return status


# Singleton instance
_cosmos_client = None


def get_cosmos_client() -> CosmosDBClient:
    """Get or create the singleton Cosmos DB client"""
    global _cosmos_client
    if _cosmos_client is None:
        _cosmos_client = CosmosDBClient()
    return _cosmos_client


def init_cosmos_db() -> bool:
    """
    Initialize Cosmos DB connection and ensure all containers exist.
    
    Returns:
        bool: True if successful
    """
    client = get_cosmos_client()
    
    if not client.connect():
        logger.error("Failed to connect to Cosmos DB")
        return False
    
    results = client.ensure_containers()
    success = all(results.values())
    
    if success:
        logger.info("✓ All Cosmos DB containers initialized successfully")
    else:
        logger.error(f"✗ Some containers failed to initialize: {results}")
    
    return success


def default_ui_templates() -> List[Dict[str, Any]]:
    """Return a small set of common UI templates for TemplateLibrary."""
    return [
        {
            "id": "template-dashboard-layout-v1",
            "template_id": "template-dashboard-layout-v1",
            "name": "Dashboard Layout",
            "type": "ui_component",
            "framework": "react",
            "language": "javascript",
            "tags": ["dashboard", "layout", "cards", "stats"],
            "content": {
                "path": "templates/dashboard/DashboardLayout.jsx",
                "code": "import React from 'react';\n\nexport default function DashboardLayout({ title = 'Dashboard', stats = [], children }) {\n  return (\n    <main className='min-h-screen bg-slate-50 p-6'>\n      <header className='mb-6'>\n        <h1 className='text-2xl font-bold text-slate-900'>{title}</h1>\n      </header>\n\n      <section className='mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4'>\n        {stats.map((item) => (\n          <article key={item.label} className='rounded-xl border bg-white p-4 shadow-sm'>\n            <p className='text-sm text-slate-500'>{item.label}</p>\n            <p className='text-2xl font-semibold text-slate-900'>{item.value}</p>\n          </article>\n        ))}\n      </section>\n\n      <section className='rounded-xl border bg-white p-5 shadow-sm'>{children}</section>\n    </main>\n  );\n}\n",
            },
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        },
        {
            "id": "template-sidebar-nav-v1",
            "template_id": "template-sidebar-nav-v1",
            "name": "Sidebar Navigation",
            "type": "ui_component",
            "framework": "react",
            "language": "javascript",
            "tags": ["sidebar", "navigation", "layout"],
            "content": {
                "path": "templates/sidebar/SidebarNav.jsx",
                "code": "import React from 'react';\nimport { NavLink } from 'react-router-dom';\n\nexport default function SidebarNav({ items = [] }) {\n  return (\n    <aside className='h-screen w-64 border-r bg-white p-4'>\n      <div className='mb-6 text-lg font-bold text-slate-900'>App</div>\n      <nav className='space-y-1'>\n        {items.map((item) => (\n          <NavLink\n            key={item.to}\n            to={item.to}\n            className={({ isActive }) =>\n              `block rounded-md px-3 py-2 text-sm ${isActive ? 'bg-indigo-50 text-indigo-700' : 'text-slate-700 hover:bg-slate-100'}`\n            }\n          >\n            {item.label}\n          </NavLink>\n        ))}\n      </nav>\n    </aside>\n  );\n}\n",
            },
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        },
    ]


def seed_default_templates(templates: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Seed TemplateLibrary with common templates (idempotent via upsert)."""
    client = get_cosmos_client()
    if not client.connect():
        return {"ok": False, "seeded": 0, "errors": ["Could not connect to Cosmos DB"]}

    container_results = client.ensure_containers()
    if not container_results or not all(container_results.values()):
        return {"ok": False, "seeded": 0, "errors": ["Could not ensure required containers"]}

    template_container = os.getenv("COSMOS_TEMPLATE_CONTAINER") or os.getenv("COSMOS_TEMPLATE_CONTAINTER", "TemplateLibrary")
    payload = templates if isinstance(templates, list) and templates else default_ui_templates()

    seeded = 0
    upserted: List[str] = []
    errors: List[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        doc = dict(item)
        if "id" not in doc:
            doc["id"] = str(doc.get("template_id") or f"template-{seeded + 1}")
        if "template_id" not in doc:
            doc["template_id"] = doc["id"]
        doc["updated_at"] = datetime.now().isoformat()

        result = client.insert_document(template_container, doc)
        if result is None:
            errors.append(f"Failed to upsert template: {doc.get('id')}")
        else:
            seeded += 1
            upserted.append(str(doc.get("id")))

    return {
        "ok": len(errors) == 0,
        "seeded": seeded,
        "upserted": upserted,
        "errors": errors,
        "container": template_container,
    }


def default_starter_templates() -> List[Dict[str, Any]]:
    """Return starter project templates intended for direct workspace initialization."""
    now = datetime.now().isoformat()
    return [
        {
            "id": "react-vite-tailwind-ts-starter-v1",
            "template_id": "react-vite-tailwind-ts-starter-v1",
            "name": "React + Vite + Tailwind + TypeScript Starter",
            "kind": "starter_template",
            "version": "1.0.0",
            "stack_tokens": ["react", "vite", "tailwind", "typescript", "frontend"],
            "description": "Production-ready starter scaffold for React + Vite + Tailwind + TypeScript.",
            "files": {
                "package.json": "{\n  \"name\": \"frontend-app\",\n  \"private\": true,\n  \"version\": \"0.1.0\",\n  \"type\": \"module\",\n  \"scripts\": {\n    \"dev\": \"vite --port 5180 --strictPort\",\n    \"build\": \"tsc -b && vite build\",\n    \"preview\": \"vite preview --port 5180 --strictPort\"\n  },\n  \"dependencies\": {\n    \"react\": \"^18.3.1\",\n    \"react-dom\": \"^18.3.1\",\n    \"react-router-dom\": \"^6.28.0\"\n  },\n  \"devDependencies\": {\n    \"@types/react\": \"^18.3.3\",\n    \"@types/react-dom\": \"^18.3.0\",\n    \"@vitejs/plugin-react\": \"^4.3.1\",\n    \"autoprefixer\": \"^10.4.20\",\n    \"postcss\": \"^8.4.47\",\n    \"tailwindcss\": \"^3.4.13\",\n    \"typescript\": \"^5.6.3\",\n    \"vite\": \"^5.4.8\"\n  }\n}\n",
                "index.html": "<!doctype html>\n<html lang=\"en\">\n  <head>\n    <meta charset=\"UTF-8\" />\n    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />\n    <title>Frontend App</title>\n  </head>\n  <body>\n    <div id=\"root\"></div>\n    <script type=\"module\" src=\"/src/main.tsx\"></script>\n  </body>\n</html>\n",
                "tsconfig.json": "{\n  \"compilerOptions\": {\n    \"target\": \"ES2020\",\n    \"lib\": [\"ES2020\", \"DOM\", \"DOM.Iterable\"],\n    \"module\": \"ESNext\",\n    \"skipLibCheck\": true,\n    \"moduleResolution\": \"Bundler\",\n    \"resolveJsonModule\": true,\n    \"allowSyntheticDefaultImports\": true,\n    \"esModuleInterop\": true,\n    \"strict\": true,\n    \"noEmit\": true,\n    \"jsx\": \"react-jsx\"\n  },\n  \"include\": [\"src\"]\n}\n",
                "vite.config.ts": "import { defineConfig } from 'vite';\nimport react from '@vitejs/plugin-react';\n\nexport default defineConfig({\n  plugins: [react()],\n});\n",
                "tailwind.config.js": "/** @type {import('tailwindcss').Config} */\nexport default {\n  content: ['./index.html', './src/**/*.{ts,tsx,js,jsx}'],\n  theme: {\n    extend: {},\n  },\n  plugins: [],\n};\n",
                "postcss.config.js": "export default {\n  plugins: {\n    tailwindcss: {},\n    autoprefixer: {},\n  },\n};\n",
                "src/main.tsx": "import React from 'react';\nimport ReactDOM from 'react-dom/client';\nimport { BrowserRouter } from 'react-router-dom';\nimport App from './App';\nimport './index.css';\n\nReactDOM.createRoot(document.getElementById('root')!).render(\n  <React.StrictMode>\n    <BrowserRouter>\n      <App />\n    </BrowserRouter>\n  </React.StrictMode>,\n);\n",
                "src/App.tsx": "import { Link, Route, Routes } from 'react-router-dom';\n\nfunction Home() {\n  return (\n    <div className=\"mx-auto max-w-3xl p-8\">\n      <h1 className=\"text-3xl font-bold text-slate-900\">Frontend Starter Ready</h1>\n      <p className=\"mt-3 text-slate-600\">React + Vite + Tailwind + TypeScript has been initialized.</p>\n    </div>\n  );\n}\n\nexport default function App() {\n  return (\n    <div className=\"min-h-screen bg-slate-50\">\n      <nav className=\"border-b bg-white\">\n        <div className=\"mx-auto flex max-w-6xl items-center gap-6 px-6 py-3\">\n          <Link to=\"/\" className=\"font-semibold text-indigo-700\">Home</Link>\n        </div>\n      </nav>\n      <Routes>\n        <Route path=\"/\" element={<Home />} />\n      </Routes>\n    </div>\n  );\n}\n",
                "src/index.css": "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n\n:root {\n  color-scheme: light;\n}\n\nbody {\n  margin: 0;\n  font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;\n}\n",
            },
            "created_at": now,
            "updated_at": now,
                },
                {
                        "id": "node-express-mongodb-backend-starter-v1",
                        "template_id": "node-express-mongodb-backend-starter-v1",
                        "name": "Node.js + Express + MongoDB Backend Starter",
                        "kind": "starter_template",
                        "version": "1.0.0",
                        "stack_tokens": ["nodejs", "node", "express", "mongodb", "mongoose", "backend"],
                        "description": "Production-ready backend starter for Node.js + Express + MongoDB (Mongoose).",
                        "files": {
                                "package.json": """{
    \"name\": \"backend-app\",
    \"private\": true,
    \"version\": \"0.1.0\",
    \"main\": \"src/server.js\",
    \"scripts\": {
        \"dev\": \"nodemon src/server.js\",
        \"start\": \"node src/server.js\"
    },
    \"dependencies\": {
        \"cors\": \"^2.8.5\",
        \"dotenv\": \"^16.4.5\",
        \"express\": \"^4.21.1\",
        \"helmet\": \"^7.1.0\",
        \"mongoose\": \"^8.7.1\",
        \"zod\": \"^3.22.4\"
    },
    \"devDependencies\": {
        \"nodemon\": \"^3.1.7\"
    }
}
""",
                                ".env.example": """PORT=5100
MONGODB_URI=mongodb://127.0.0.1:27017/library_platform
""",
                                "src/server.js": """require('dotenv').config();
const app = require('./app');
const { connectMongo } = require('./config/db');

const PORT = Number(process.env.PORT || 5100);

async function bootstrap() {
    await connectMongo();
    app.listen(PORT, () => {
        console.log(`[backend] listening on http://127.0.0.1:${PORT}`);
    });
}

bootstrap().catch((err) => {
    console.error('[backend] startup failed', err);
    process.exit(1);
});
""",
                                "src/app.js": """const express = require('express');
const helmet = require('helmet');
const cors = require('cors');
const healthRouter = require('./routes/health');

const app = express();

// Security middleware
app.use(helmet());
app.use(cors());
app.use(express.json());

app.use('/api/health', healthRouter);

// Error handling middleware
app.use((err, _req, res, _next) => {
    console.error(err);
    // Handle Zod validation errors
    if (err.name === 'ZodError') {
        return res.status(400).json({ 
            error: 'Validation failed',
            details: err.errors 
        });
    }
    res.status(500).json({ error: 'Internal server error' });
});

module.exports = app;
""",
                                "src/config/db.js": """const mongoose = require('mongoose');

async function connectMongo() {
    const uri = process.env.MONGODB_URI;
    if (!uri) {
        throw new Error('MONGODB_URI is not set');
    }
    await mongoose.connect(uri);
    console.log('[backend] MongoDB connected');
}

module.exports = { connectMongo };
""",
                                "src/routes/health.js": """const router = require('express').Router();

router.get('/', (_req, res) => {
    res.status(200).json({ status: 'ok' });
});

module.exports = router;
""",
                        },
                        "created_at": now,
                        "updated_at": now,
                },
                {
                        "id": "mongodb-database-starter-v1",
                        "template_id": "mongodb-database-starter-v1",
                        "name": "MongoDB Database Starter",
                        "kind": "starter_template",
                        "version": "1.0.0",
                        "stack_tokens": ["mongodb", "mongo", "database"],
                        "description": "Database starter for MongoDB with local docker-compose and bootstrap script.",
                        "files": {
                                "docker-compose.yml": """version: '3.9'
services:
    mongo:
        image: mongo:7
        restart: unless-stopped
        ports:
            - '27017:27017'
        environment:
            MONGO_INITDB_DATABASE: library_platform
        volumes:
            - mongo_data:/data/db
            - ./mongo-init:/docker-entrypoint-initdb.d:ro

volumes:
    mongo_data:
""",
                                "mongo-init/01-init.js": """db = db.getSiblingDB('library_platform');

db.createCollection('users');
db.createCollection('books');
db.createCollection('reservations');
db.createCollection('events');

db.users.createIndex({ email: 1 }, { unique: true });
db.books.createIndex({ title: 'text', author: 'text', isbn: 'text' });
db.reservations.createIndex({ user_id: 1, book_id: 1, reservation_date: 1 });
db.events.createIndex({ date: 1 });
""",
                                "README.md": """# MongoDB Starter

## Start local MongoDB

```bash
docker compose up -d
```

## Connection string

```text
mongodb://127.0.0.1:27017/library_platform
```

Collections and indexes are bootstrapped from `mongo-init/01-init.js`.
""",
                        },
                        "created_at": now,
                        "updated_at": now,
                },
    ]


def seed_starter_templates(templates: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Seed starter_templates container with project starter templates."""
    client = get_cosmos_client()
    if not client.connect():
        return {"ok": False, "seeded": 0, "errors": ["Could not connect to Cosmos DB"]}

    container_results = client.ensure_containers()
    if not container_results or not all(container_results.values()):
        return {"ok": False, "seeded": 0, "errors": ["Could not ensure required containers"]}

    container_name = os.getenv("COSMOS_STARTER_TEMPLATE_CONTAINER", "starter_templates")
    payload = templates if isinstance(templates, list) and templates else default_starter_templates()

    seeded = 0
    upserted: List[str] = []
    errors: List[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        doc = dict(item)
        if "id" not in doc:
            doc["id"] = str(doc.get("template_id") or f"starter-template-{seeded + 1}")
        if "template_id" not in doc:
            doc["template_id"] = doc["id"]
        doc["updated_at"] = datetime.now().isoformat()

        result = client.insert_document(container_name, doc)
        if result is None:
            errors.append(f"Failed to upsert starter template: {doc.get('id')}")
        else:
            seeded += 1
            upserted.append(str(doc.get("id")))

    return {
        "ok": len(errors) == 0,
        "seeded": seeded,
        "upserted": upserted,
        "errors": errors,
        "container": container_name,
    }


def get_starter_template(template_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a starter template by template_id from Cosmos."""
    if not template_id:
        return None

    client = get_cosmos_client()
    if not client.connect():
        return None

    container_name = os.getenv("COSMOS_STARTER_TEMPLATE_CONTAINER", "starter_templates")

    doc = client.get_document(container_name, template_id, partition_key=template_id)
    if isinstance(doc, dict):
        return doc

    docs = client.query_documents(
        container_name,
        "SELECT TOP 1 * FROM c WHERE c.template_id = @template_id",
        [{"name": "@template_id", "value": template_id}],
    )
    return docs[0] if docs else None


def resolve_starter_template_for_stack(stack_tokens: List[str]) -> Optional[Dict[str, Any]]:
    """Resolve best starter template match for a given list of stack tokens."""
    tokens = [str(t).strip().lower() for t in (stack_tokens or []) if str(t).strip()]
    if not tokens:
        return None

    client = get_cosmos_client()
    if not client.connect():
        return None

    container_name = os.getenv("COSMOS_STARTER_TEMPLATE_CONTAINER", "starter_templates")
    candidates = client.query_documents(container_name, "SELECT * FROM c WHERE c.kind = @kind", [{"name": "@kind", "value": "starter_template"}])
    if not candidates:
        return None

    def score(doc: Dict[str, Any]) -> int:
        doc_tokens = [str(t).strip().lower() for t in (doc.get("stack_tokens") or []) if str(t).strip()]
        if not doc_tokens:
            return 0
        doc_set = set(doc_tokens)
        return sum(1 for t in tokens if t in doc_set)

    ranked = sorted(candidates, key=lambda d: score(d), reverse=True)
    best = ranked[0] if ranked else None
    if not best or score(best) == 0:
        return None
    return best
