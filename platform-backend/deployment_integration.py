"""
Deployment Integration Module

Bridges the Agentic Nexus orchestrator with the Deployment Agent.
Handles invoking deployment functions after code generation is complete.
"""

import os
import json
import logging
from typing import Dict, Optional
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class DeploymentIntegration:
    """
    Orchestrates deployment after code generation is complete.
    Invokes appropriate deployment agent functions based on project configuration.
    """
    
    def __init__(self, project_id: str, app_name: str, ledger_data: Dict):
        """
        Initialize deployment integration.
        
        Args:
            project_id: Unique project identifier
            app_name: Application name
            ledger_data: Task ledger data containing project metadata
        """
        self.project_id = project_id
        self.app_name = app_name
        self.ledger_data = ledger_data
        self.logger = logging.getLogger(f"Deployment[{project_id}]")
    
    async def generate_deployment_bundle(self) -> Dict:
        """
        Generate deployment bundle (Dockerfile, Bicep, GitHub Actions, README).
        
        Returns:
            Dictionary containing bundle results
        """
        try:
            from deployment_agent import generate_dockerfile, generate_bicep, generate_github_actions, generate_readme
            from pydantic import BaseModel
            
            # Extract app type and language from ledger
            description = self.ledger_data.get("user_intent", "")
            app_type = self._infer_app_type(description)
            language = self._infer_language(description)
            port = self.ledger_data.get("port", 8000)
            azure_resources = self.ledger_data.get("azure_resources", ["cosmos_db", "blob_storage", "key_vault"])
            
            # Create minimal config object
            class ProjectConfig:
                def __init__(self):
                    self.project_id = project_id_val
                    self.app_name = app_name_val
                    self.app_type = app_type_val
                    self.language = language_val
                    self.port = port_val
                    self.env_vars = []
                    self.azure_resources = azure_resources_val
                    self.description = description_val
            
            # Store values to avoid scoping issues
            project_id_val = self.project_id
            app_name_val = self.app_name
            app_type_val = app_type
            language_val = language
            port_val = port
            azure_resources_val = azure_resources
            description_val = description
            
            config = ProjectConfig()
            
            self.logger.info("🏗️  Generating deployment bundle...")
            
            dockerfile = generate_dockerfile(config)
            bicep = generate_bicep(config)
            github_actions = generate_github_actions(config)
            readme = generate_readme(config)
            
            # Save deployment artifacts
            deploy_dir = Path("./generated_code/deployment")
            deploy_dir.mkdir(parents=True, exist_ok=True)
            
            (deploy_dir / "Dockerfile").write_text(dockerfile)
            (deploy_dir / "infrastructure.bicep").write_text(bicep)
            (deploy_dir / "github-actions.yml").write_text(github_actions)
            (deploy_dir / "README.md").write_text(readme)
            
            self.logger.info(f"✅ Deployment bundle saved to {deploy_dir}")
            
            return {
                "status": "success",
                "project_id": self.project_id,
                "bundle_location": str(deploy_dir.absolute()),
                "artifacts": {
                    "dockerfile": str(deploy_dir / "Dockerfile"),
                    "bicep": str(deploy_dir / "infrastructure.bicep"),
                    "github_actions": str(deploy_dir / "github-actions.yml"),
                    "readme": str(deploy_dir / "README.md")
                },
                "generated_at": datetime.utcnow().isoformat()
            }
        
        except Exception as e:
            self.logger.error(f"❌ Failed to generate deployment bundle: {str(e)}")
            raise
    
    async def generate_blueprint(self) -> Dict:
        """
        Generate system blueprint (agents, resources, data flows).
        
        Returns:
            Dictionary containing blueprint
        """
        try:
            from deployment_agent import generate_blueprint
            
            class ProjectConfig:
                def __init__(self):
                    self.project_id = project_id_val
                    self.app_name = app_name_val
                    self.app_type = app_type_val
                    self.language = language_val
                    self.azure_resources = azure_resources_val
                    self.description = description_val
            
            project_id_val = self.project_id
            app_name_val = self.app_name
            app_type_val = self._infer_app_type(self.ledger_data.get("user_intent", ""))
            language_val = self._infer_language(self.ledger_data.get("user_intent", ""))
            azure_resources_val = self.ledger_data.get("azure_resources", ["cosmos_db", "blob_storage", "key_vault"])
            description_val = self.ledger_data.get("user_intent", "")
            
            config = ProjectConfig()
            
            self.logger.info("📐 Generating system blueprint...")
            blueprint = generate_blueprint(config)
            
            # Save blueprint
            blueprint_file = Path("./generated_code/blueprint.json")
            with open(blueprint_file, 'w') as f:
                json.dump(blueprint, f, indent=2)
            
            self.logger.info(f"✅ Blueprint saved to {blueprint_file}")
            
            return {
                "status": "success",
                "blueprint": blueprint,
                "location": str(blueprint_file.absolute()),
                "generated_at": datetime.utcnow().isoformat()
            }
        
        except Exception as e:
            self.logger.error(f"❌ Failed to generate blueprint: {str(e)}")
            raise
    
    async def estimate_cost(self) -> Dict:
        """
        Estimate monthly Azure infrastructure cost.
        
        Returns:
            Dictionary containing cost estimation
        """
        try:
            from deployment_agent import estimate_cost
            
            class ProjectConfig:
                def __init__(self):
                    self.project_id = project_id_val
                    self.app_name = app_name_val
                    self.app_type = app_type_val
                    self.language = language_val
                    self.port = port_val
                    self.azure_resources = azure_resources_val
                    self.description = description_val
            
            project_id_val = self.project_id
            app_name_val = self.app_name
            app_type_val = self._infer_app_type(self.ledger_data.get("user_intent", ""))
            language_val = self._infer_language(self.ledger_data.get("user_intent", ""))
            port_val = self.ledger_data.get("port", 8000)
            azure_resources_val = self.ledger_data.get("azure_resources", ["cosmos_db", "blob_storage", "key_vault"])
            description_val = self.ledger_data.get("user_intent", "")
            
            config = ProjectConfig()
            
            self.logger.info("💰 Estimating deployment costs...")
            estimate = estimate_cost(config)
            
            # Save estimate
            estimate_file = Path("./generated_code/cost_estimate.json")
            with open(estimate_file, 'w') as f:
                json.dump(estimate, f, indent=2)
            
            self.logger.info(f"✅ Cost estimate: ${estimate.get('total_monthly_usd', 0):.2f}/month")
            self.logger.info(f"   Location: {estimate_file}")
            
            return {
                "status": "success",
                "estimate": estimate,
                "location": str(estimate_file.absolute()),
                "generated_at": datetime.utcnow().isoformat()
            }
        
        except Exception as e:
            self.logger.error(f"❌ Failed to estimate costs: {str(e)}")
            raise
    
    def _infer_app_type(self, text: str) -> str:
        """Infer application type from description."""
        text_lower = text.lower()
        if "fastapi" in text_lower or "python" in text_lower:
            return "fastapi"
        elif "express" in text_lower or "node" in text_lower:
            return "express"
        elif "react" in text_lower:
            return "react"
        elif "nextjs" in text_lower or "next.js" in text_lower:
            return "nextjs"
        return "fastapi"  # Default
    
    def _infer_language(self, text: str) -> str:
        """Infer programming language from description."""
        text_lower = text.lower()
        if "typescript" in text_lower:
            return "typescript"
        elif "node" in text_lower or "javascript" in text_lower:
            return "node"
        elif "python" in text_lower:
            return "python"
        return "python"  # Default


async def run_post_generation_deployment(
    project_id: str,
    app_name: str,
    ledger_data: Dict,
    enable_blueprint: bool = True,
    enable_cost_estimate: bool = True,
    enable_bundle: bool = True
) -> Dict:
    """
    Execute deployment tasks after code generation is complete.
    
    Args:
        project_id: Unique project identifier
        app_name: Application name
        ledger_data: Task ledger containing project metadata
        enable_blueprint: Whether to generate blueprint
        enable_cost_estimate: Whether to estimate costs
        enable_bundle: Whether to generate deployment bundle
        
    Returns:
        Dictionary with all deployment results
    """
    integration = DeploymentIntegration(project_id, app_name, ledger_data)
    results = {
        "project_id": project_id,
        "timestamp": datetime.utcnow().isoformat(),
        "deployment_tasks": {}
    }
    
    try:
        if enable_bundle:
            results["deployment_tasks"]["bundle"] = await integration.generate_deployment_bundle()
        
        if enable_blueprint:
            results["deployment_tasks"]["blueprint"] = await integration.generate_blueprint()
        
        if enable_cost_estimate:
            results["deployment_tasks"]["cost_estimate"] = await integration.estimate_cost()
        
        results["status"] = "success"
        logger.info("\n" + "="*70)
        logger.info("🚀 DEPLOYMENT INTEGRATION COMPLETE")
        logger.info("📦 Artifacts available in: ./generated_code/")
        logger.info("="*70)
    
    except Exception as e:
        results["status"] = "failed"
        results["error"] = str(e)
        logger.error(f"❌ Deployment integration failed: {str(e)}")
    
    return results
