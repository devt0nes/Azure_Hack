# Azure Hack

---

## Backend Integration & Migration — March 7, 2026

### Platform Backend (Production)
Integrated full Agentic Nexus backend to replace placeholder API:

**Backend Replacement**
- **Deleted**: Minimal `platform-backend` with placeholder endpoints
- **Activated**: Full-featured backend from `tentative-backend` (now `platform-backend`)
- Comprehensive FastAPI application with:
  - Project lifecycle management (`/api/projects`)
  - Real-time status tracking
  - Artifact generation and download
  - Deployment integration (Docker, Bicep, GitHub Actions)
  - Cost estimation
  - Audit logging

**Compatibility Layer**
Added legacy endpoint adapters for seamless frontend integration:
- `POST /clarify` - Director clarification (maps to project creation)
- `GET /aeg` - Agent Execution Graph (returns task ledger structure)
- `POST /execute` - Project execution trigger
- `POST /tutor/ask` - Learning assistant responses
- `GET /api/tunnel-status` - Preview tunnel status

**Architecture Improvements**
- **Orchestration Engine**: Full multi-agent system with swarm coordination
  - 9 specialized agents (Backend, Frontend, Database, DevOps, Security, QA, etc.)
  - Dynamic task distribution and dependency management
  - Parallel execution with smart coordination
  - Checkpoint/resume capability
- **Azure Integration**:
  - Azure OpenAI (GPT-4o/GPT-4o-mini)
  - Cosmos DB for persistence
  - Service Bus for agent coordination
  - Container Apps deployment ready
- **Deployment Automation**:
  - Automatic Dockerfile generation
  - Bicep infrastructure templates
  - GitHub Actions CI/CD pipelines
  - Monthly cost estimation

**Bug Fixes**
- Fixed `deployment_integration.py` class scoping issues
- Corrected language inference logic (TypeScript detection)
- Made orchestrator accept API-driven project requests (removed hardcoded input)

**Running the Backend**
```bash
cd platform-backend

# Install dependencies
pip install -r requirements.txt

# Configure Azure credentials
cp .env.example .env
# Edit .env with your Azure OpenAI/Cosmos/Service Bus credentials

# Run locally
uvicorn app:app --reload --port 8000

# Or use Docker
docker-compose up --build
```

**API Documentation**
- Interactive docs: `http://localhost:8000/api/docs`
- OpenAPI schema: `http://localhost:8000/api/openapi.json`
- See `platform-backend/API_DOCUMENTATION.md` for detailed endpoint reference

**Frontend Configuration**
Updated `.env` to point to integrated backend:
```env
VITE_API_BASE_URL=http://localhost:8000
VITE_TUTOR_API_URL=http://localhost:8000
```

### Quick Start Guide

**1. Start Backend**
```bash
# Terminal 1
cd platform-backend

# Install dependencies (one-time)
pip install -r requirements.txt

# Configure Azure credentials
cp .env.example .env
# Edit .env with Azure credentials (OpenAI endpoint, key, etc.)

# Start server (use python -m if uvicorn not on PATH)
python -m uvicorn app:app --reload --port 8000
```

**2. Start Frontend**
```bash
# Terminal 2
cd platform-frontend
npm install  # one-time
npm run dev
# Opens at http://localhost:5173 (or next available port)
```

**3. Access Application**
- Frontend UI: `http://localhost:5173`
- Backend API Docs: `http://localhost:8000/api/docs`
- Login with any button (hardcoded auth, no real credentials needed)

**4. Create a Project**
- Use Director chat to describe your project
- System generates Agent Execution Graph
- Monitor progress in real-time
- Download generated code artifacts

### Project Structure (Simplified)
```
Azure_Hack/
├── platform-backend/     # FastAPI + Orchestration Engine (production)
├── platform-frontend/    # React + Vite UI
└── infrastructure/       # Bicep templates, deployment scripts
```

---

## Landing Page & Authentication Flow — March 7, 2026

### Landing Page
Created complete marketing landing page that serves as the entry point:

**Hero Section**
- Large title and tagline explaining the platform
- "Get Started" call-to-action button
- Animated gradient backgrounds and floating elements
- Navigation bar with Login and Sign Up buttons

**How It Works Section**
- 3-step workflow explanation:
  1. **Direct & Clarify** - Communicate with Director Agent
  2. **Orchestrate Agents** - System generates Agent Execution Graph
  3. **Monitor & Execute** - Real-time tracking with logs and cost monitoring
- Glassmorphic cards with gradient icons
- Hover effects for visual feedback

**Subscription Plans**
- **Starter ($0/month)**: 5 projects, basic orchestration, community support
- **Professional ($49/month)**: Unlimited projects, priority support, advanced analytics (Popular badge)
- **Enterprise (Custom)**: Everything + dedicated infrastructure, SLA guarantees, white-label

**Footer**
- Copyright and branding information

### Authentication Flow (Hardcoded)
- **Default state**: Shows landing page
- **Login/Signup actions**: All buttons (Nav Login, Nav Sign Up, Get Started, plan buttons) trigger hardcoded login
- **Post-login**: Redirects to full Command Center application with all current features
- **State management**: `isLoggedIn` boolean in App.jsx (currently no real auth)

### Technical Implementation
- Created `LandingPage.jsx` component
- App.jsx conditionally renders: `!isLoggedIn ? <LandingPage /> : <CommandCenter />`
- `handleLogin()` function toggles state (hardcoded, no real authentication)
- Landing page uses same design system (glassmorphism, gradients, animations)
- All existing features remain behind the "login" wall

### User Flow
1. User lands on marketing page with platform info
2. User clicks any login/signup/CTA button
3. State changes to logged in (instant, no backend call)
4. App shows full Command Center interface with all features

---

## Prominent Director & Side-Panel Assistant — March 7, 2026

### Director Agent - Main Focus
Made Director Agent the primary, most prominent element:
- **Larger layout**: Changed grid from `[1fr_2fr_1fr]` to `[300px_1fr_300px]` giving Director maximum space
- **Enhanced styling**: 
  - Border changed to `border-2` with ember accent color (`border-ember/30`)
  - Stronger background gradient (`from-white/90`)
  - Larger shadow (`shadow-xl` → `shadow-2xl` on hover)
  - Min-height increased to 700px
- **Visual accent bar**: Added vertical ember gradient bar next to title
- **Larger title**: Text-xl with ember gradient coloring
- **Better padding**: Increased to p-8 for spacious feel

### Learning Assistant - Side Panel
Converted from full-screen modal to helpful side panel:
- **Side panel design**: Slides in from right at 500px width
- **Backdrop**: Semi-transparent overlay with backdrop-blur
- **Emerald theming**: Green gradient accent to differentiate from Director (orange/ember)
- **Compact header**: Shows "Learning Assistant" with subtitle "Ask questions and get contextual help"
- **Easy dismiss**: Click backdrop or close button (Close)
- **Smooth animation**: Uses existing slide-in-right animation
- **Non-intrusive**: Appears alongside content, doesn't cover main Director view
- **Fixed positioning**: Right-aligned panel stays on screen while scrolling

### UX Improvements
- Director always visible and takes center stage
- Learning Assistant renamed to "Assistant" on button (shorter, clearer)
- Better visual hierarchy with color-coded sections (ember = Director, emerald = Assistant)
- Side panel design keeps focus on main Director workflow
- Assistant panel doesn't compete for attention—it's a helpful sidebar

---

## Header & Learning Modal Updates — March 7, 2026

### Prominent Header Design
Enhanced the header to be more prominent and informative:
- **Larger title**: Increased from text-4xl to text-5xl/6xl (responsive)
- **Tagline/Description**: Added descriptive paragraph explaining the platform's purpose ("Orchestrate multi-agent AI workflows...")
- **Better spacing**: Increased vertical padding (py-12) and margin-bottom (mb-12)
- **Improved typography**: Larger tracking on brand label, better line-height on description
- **Enhanced layout**: Uses flex-1 with min-width to maintain responsive flexibility

### Learning Agent Modal
Converted Learning Agent from tab to popup modal:
- **Icon Button**: Replaced Learning tab with a prominent button next to "Director Agent" header
- **Full-screen Modal**: Opens 85vh modal overlay with glassmorphic background blur
- **Easy Access**: Click "Learning" button to open, "Close" to dismiss
- **Better UX**: Learning content no longer competes for space in main layout
- **Smooth Animation**: Modal uses fade-in animation on open
- **Responsive**: Modal adapts to screen size with max-w-6xl constraint

### Layout Improvements
- **Director Section**: Now always visible (no tab switching needed)
- **Content Flow**: Director conversation + Preview always shown side-by-side
- **Cleaner Navigation**: Simpler interface without tab switching for main workflow
- **Modal State**: Added `showLearningModal` state for popup control

---

## Visual Enhancements — March 7, 2026

### Latest changes
Elevated UI to React Bits-inspired glassmorphism and animations for modern, premium aesthetic:

**Tailwind Config Upgrades**
- Added custom animations: `fade-in`, `fade-in-up`, `slide-in-right`, `glow-pulse`, `float`, `shimmer`
- Extended keyframes for smooth motion effects
- New box-shadow variants: `glow-sm` (20px), `glass` (8px depth effect)
- Backdrop blur variant: `blur-xs` for fine-grained frosted glass effects

**AgentCard Enhancement**
- Gradient backgrounds tied to state (blue/amber/green/rose gradients)
- Glassmorphic design with backdrop blur and semi-transparent layers
- Gradient progress bars with color-coded animations
- Shimmer effect on active progress (0-100%)
- Hover scale effect (`group-hover:scale-105`) with glass depth shadow
- Glow effects for RUNNING state with shadow pulsing
- Progress percentage display + status indicator ("In Progress" / "Waiting" / "Done")

**CostTicker Animation**
- Smooth number counter animation (cost increments with 0.1 lerp, tokens tick up)
- Gradient text color: ember → orange → amber gradient
- Glassmorphic background with radial gradient overlay
- Subtle glow shadow effect
- Indicators: cost and token count

**LogStream Styling**
- Animated fade-in for each log entry on scroll
- Glassmorphic card background with gradient (sand → white → haze)
- Individual log items: rounded border, backdrop blur, hover brightness increase
- Bold emoji bullets (›) with proper spacing
- Semi-transparent white cards with hover effect

**Main App Layout**
- Dynamic gradient background: sand → white → haze (left-to-right)
- Floating animated blobs in background (2 elements, staggered animation)
- Header animation: fade-in on mount
- Gradient text for title and labels
- Animated connection status indicator with glow pulse when connected
- Connected state: emerald with green glow shadow

**Component Panels (Glassmorphic)**
- All sections: white/glass backgrounds with backdrop blur
- Rounded borders: 3xl (24px) for generous curves
- Hover states: border brightness + shadow enhancement
- Gradient underlay on hover for subtle depth
- Tab buttons: Gradient backgrounds for active states (ember/emerald)
- Shadow handling: glass shadow instead of plain shadow-sm

**Button Styling**
- Tab buttons now use full gradient backgrounds when active
- Director tab: ember → orange gradient
- Learning tab: emerald → teal gradient
- Transitions smooth with 300ms duration
- Enhanced visual hierarchy with proper spacing

### Technical Details
- Animations use CSS-in-Tailwind with cubic-bezier timing for natural motion
- Float animation: 6s cycle, 20px Y-axis travel
- Shimmer effect: 2s background-position animation
- All transitions: 0.3s ease-out for responsive feel
- Glow effects use rgba shadows for soft, modern look

### Notes
- Design inspiration: React Bits (reactbits.dev) aesthetic patterns
- Glassmorphism + backdrop blur requires modern browser support
- CSS animations run at 60fps with GPU acceleration (transform/opacity)
- Gradient text uses `bg-clip-text` for clean, sharp color transitions
- All enhancements are production-ready with smooth performance

### Next steps
1. Test on actual device with frontend `npm run dev`
2. Fine-tune animation timings if needed
3. Add dark mode variant (optional enhancement)
4. Wire up real data to see animations in action during agent execution
5. Consider adding stagger delays to card animations for sequence effect

---

## 📅 Day 1 — February 27, 2026

### Latest changes
Built the complete Day 1 frontend stack for Platform A (Command Center):

**Frontend Architecture**
- Scaffolded React 18 + Vite app with Tailwind CSS
- Created conversation UI with Director chat interface (`/pages/Conversation.jsx`)
- Built reusable components: `AgentCard`, `CostTicker`, `LogStream`, `FeedbackPanel`
- Implemented API service layer (`/services/api.js`) with `/clarify` endpoint integration
- Added placeholder views for AEG graph (`AEGView.jsx`) and local preview (`Preview.jsx`)
- Custom color palette (midnight, ember, sand) with IBM Plex Mono + Space Grotesk fonts

**Project Structure**
- Created `platform-frontend/` with complete component hierarchy
- Scaffolded `platform-backend/` with Python API placeholders (api.py, signalr_hub.py, cosmos_client.py)
- Added `infrastructure/` with Bicep templates and Docker Compose template

### Notes
- Set `VITE_API_BASE_URL` environment variable if the Director API is not on the same origin (e.g., `http://localhost:8000`)
- Tailwind configuration with custom theme in `platform-frontend/tailwind.config.js`
- All components use `.jsx` extension (switched from TypeScript to JavaScript for Day 1 speed)
- Frontend expects API contracts: `POST /clarify` with `{ project_id, user_input }` → `{ director_reply, task_ledger_updated }`

### Next steps
1. Run the frontend: `cd platform-frontend && npm run dev`
2. Wire up environment variables by creating `platform-frontend/.env` with `VITE_API_BASE_URL`
3. Implement FastAPI `/clarify` endpoint in `platform-backend/api.py`
4. Integrate ReactFlow for AEG graph visualization (Day 2)
5. Set up Azure App Service deployment

---

## 📅 Day 2 — February 27, 2026

### Latest changes
Implemented real-time agent visualization and WebSocket infrastructure:

**AEG Visualization (ReactFlow)**
- Built interactive graph view with ReactFlow in `AEGView.jsx`
- Color-coded agent states: PENDING (midnight), RUNNING (ember), COMPLETED (emerald), FAILED (red)
- Auto-layout algorithm positions nodes in 3-column grid
- Animated edges between dependent agents
- Background grid, mini-map, and zoom controls

**Real-time Updates (SignalR)**
- Full SignalR WebSocket client in `services/signalr.js`
- Auto-reconnect with connection state indicator (green/amber/red dot in header)
- Event handlers: `AgentStatusUpdate`, `LogMessage`, `CostUpdate`
- Live agent cards update on status changes
- Log stream appends new messages in real-time
- Cost ticker updates with token/cost deltas

**API Expansion**
- Added `GET /aeg` endpoint in `api.js` (fetches graph structure)
- Added `POST /execute` endpoint (triggers project build)
- All endpoints handle project_id scoping

**State Management**
- App-level state for agents, logs, tokens, and cost
- Dynamic agent array (adds new agents on first status update)
- Connection state tracking (disconnected → connected → reconnecting → failed)

### Notes
- Set `VITE_SIGNALR_URL` environment variable (e.g., `http://localhost:8000/hub`)
- Reference `.env.example` for all required environment variables
- SignalR expects backend hub at `/hub` route
- AEG nodes require `{ id, agent_type, state, dependencies }` schema
- AEG edges require `{ from, to }` schema

### Next steps
1. Copy `.env.example` to `.env` and configure endpoints
2. Implement backend SignalR hub in `platform-backend/signalr_hub.py`
3. Implement `/aeg` and `/execute` endpoints in `platform-backend/api.py`
4. Test real-time updates by triggering agent events
5. Begin Docker Compose local preview integration (Day 3)

---

## 🔧 Hotfix — February 27, 2026

### Latest changes
Fixed blank page issue caused by missing environment variables:

**Graceful Degradation**
- SignalR connection now gracefully handles missing `VITE_SIGNALR_URL` without crashing
- Returns dummy connection object when URL not configured (logs warning to console)
- AEG view shows "API not configured" message instead of attempting failed fetch
- App now renders with mock data even without backend running

**Error Handling**
- Wrapped SignalR initialization in try-catch to prevent app crashes
- Connection state defaults to 'disconnected' when setup fails
- All API-dependent components now check for configuration before making requests

### Notes
- Frontend now works standalone without backend (displays mock data)
- To enable live features, copy `.env.example` to `.env` and set URLs
- Check browser console for "VITE_SIGNALR_URL not configured" warning if WebSocket disabled
- Mock agents, logs, and cost ticker still display to showcase UI

### Next steps
1. Create `.env` file from `.env.example` when backend is ready
2. Frontend will automatically connect once environment variables are set
3. Continue with backend implementation

---

## 📅 Day 3 — February 27, 2026

### Latest changes
Built Learning Mode tutor with GPT-4o for architecture education:

**Learning Mode Component**
- Interactive AI tutor with chat interface in `LearningMode.jsx`
- Tabbed navigation: Switch between Director conversation and Learning Mode
- Quick question buttons: "Explain this build", "What is the AEG?", "How does cost tracking work?"
- Markdown rendering for rich tutor responses with formatted code, lists, and headings
- Visual "Overview Level" indicator with GPT-4o badge

**Tutor Service (`services/tutor.js`)**
- API integration ready for OpenAI GPT-4o endpoint (`POST /tutor/ask`)
- Mock responses work without backend (comprehensive architecture explanations)
- Context-aware: Can pass agents, logs, and project state to tutor
- Handles questions about:
  - Build architecture and multi-agent orchestration
  - Agent Execution Graph (AEG) structure and benefits
  - Cost tracking methodology
  - Conversation flow and Director clarification loop

**Mock Overview Responses**
- **"Explain this build"**: Returns full architecture overview with Director, specialist agents, Platform A, and execution flow
- **"What is the AEG?"**: Explains directed acyclic graph, node states, edge dependencies, parallelism benefits
- **"How does cost tracking work?"**: Details token consumption, real-time SignalR updates, optimization strategies
- Default response: Lists available topics to ask about

**UI/UX Enhancements**
- Tab switcher in main panel: Director ↔ Learning
- Ember-styled quick question chips for one-click queries
- Tutor messages render as formatted Markdown (h1/h2/lists/code blocks)
- User messages display in ember bubble, tutor in white with border
- Smooth scroll in chat history

### Notes
- Set `VITE_TUTOR_API_URL` and `VITE_TUTOR_API_KEY` environment variables when backend is ready
- Mock mode works immediately without configuration
- Tutor API expects: `{ project_id, question, context }` → `{ response, level, timestamp }`
- Markdown rendering via `react-markdown` (installed automatically)
- Overview level is first tier of learning hierarchy (future: Detailed → Code levels)
- **Fix applied**: ReactMarkdown `className` prop removed (wrapped in div) to fix v9+ compatibility

### Next steps
1. Click "Learning" tab in Command Center to test tutor
2. Try quick questions or ask custom queries
3. Implement backend tutor endpoint with real GPT-4o integration
4. Add context passing (current agents/logs) to tutor requests
5. Expand to Detailed and Code explanation levels (Day 4+)

---

## 🔧 Configuration Update — Git Setup

### Latest changes
Configured version control for GitHub push:

**Git Ignore Files**
- Root `.gitignore`: Project-wide exclusions (node_modules, .env, Python cache, build outputs)
- Frontend `.gitignore`: Added .env file exclusions to prevent credential leaks
- Backend `.gitignore`: Python-specific exclusions (__pycache__, venv/, .env)

**Protected Files**
- All `.env*` files excluded from git
- API keys, connection strings, and Azure credentials never committed
- node_modules and virtual environments ignored
- Build artifacts and temporary files excluded

**Repository Ready**
- Safe to push to GitHub
- All sensitive data protected
- Clean commit history possible

### Notes
- Review .gitignore files before first commit
- Create `.env` from `.env.example` locally (never commit actual .env)
- Azure credentials and SignalR connection strings stay local only

### Next steps
1. Initialize git: `git init`
2. Add remote: `git remote add origin <your-repo-url>`
3. Commit and push: `git add . && git commit -m "Initial commit" && git push -u origin main`

---

## � Day 4 — February 27, 2026

### Latest changes
Implemented local preview with Docker Compose and Azure Dev Tunnels:

**Docker Compose Setup**
- Production-ready `docker-compose.template.yml` with frontend and backend services
- Frontend: Node 20 Alpine with Vite hot-reload (`npm run dev -- --host 0.0.0.0`)
- Backend: Python 3.11 slim with FastAPI + uvicorn auto-reload
- Shared network for container communication
- Volume mounts for instant code changes without rebuilds
- Cached node_modules and pip packages for faster startups

**Dev Tunnels Integration**
- PowerShell scripts: `start-devtunnel.ps1` and `stop-devtunnel.ps1`
- Creates persistent Azure Dev Tunnel with public HTTPS URL
- Forwards localhost:5173 to `https://*.devtunnels.ms` domain
- Saves tunnel URL to `.tunnel-url` file (git-ignored)
- Auto-reconnect on existing tunnels

**Preview Component with iframe**
- Embedded preview in Command Center UI (`Preview.jsx`)
- Real-time iframe rendering of frontend with tunnel or localhost URL
- Tunnel status indicator (local vs active)
- Controls: Refresh iframe, Open in external tab
- Shows tunnel URL with copy hint
- Docker Compose quick start hint at bottom

**Tunnel Service (`services/tunnel.js`)**
- Queries backend `/api/tunnel-status` endpoint for active tunnel info
- Graceful fallback to localhost when tunnel not configured
- Docker environment detection (checks for `backend:8000` in API_BASE_URL)
- Returns: `{ url, status, port }`

**Backend Updates (`api.py`)**
- FastAPI server with CORS middleware for cross-origin dev tunnels
- Health check endpoint: `GET /` returns service info
- Tunnel status endpoint: `GET /api/tunnel-status` reads `.tunnel-url` file
- Placeholder endpoints ready: `/clarify`, `/aeg`, `/execute`, `/tutor/ask`
- uvicorn with `--reload` flag for hot-reload on file changes

**Hot-reload Configuration**
- Frontend: Vite watches `platform-frontend/` directory via Docker volume
- Backend: uvicorn watches `platform-backend/` with `--reload` flag
- node_modules volume prevents host overrides (faster installs)
- Python package cache volume reduces pip install times
- Changes reflect instantly without container rebuilds

**Quick Start Script**
- `infrastructure/scripts/start-local.ps1` launches Docker Compose
- Checks Docker daemon status before starting
- Displays service URLs (frontend:5173, backend:8000)
- Graceful shutdown with `docker-compose down` on Ctrl+C

### Notes
- **Docker required**: Install Docker Desktop to use local preview
- **Dev Tunnels CLI**: Install with `winget install Microsoft.devtunnel` for public URLs
- Run Docker Compose: `docker-compose -f infrastructure/docker-compose.template.yml up`
- Run Dev Tunnel: `.\infrastructure\scripts\start-devtunnel.ps1`
- Hot-reload works automatically - edit files and see changes live
- iframe sandbox: `allow-same-origin allow-scripts allow-forms allow-popups`
- `.tunnel-url` is git-ignored (tunnel URLs are ephemeral)
- Set `VITE_PREVIEW_URL` in `.env` to override default localhost

### Next steps
1. Install Docker Desktop if not already installed
2. Copy `.env.example` to `.env` and configure variables
3. Start local environment: `.\infrastructure\scripts\start-local.ps1`
4. (Optional) Start dev tunnel: `.\infrastructure\scripts\start-devtunnel.ps1`
5. Click "Preview" tab in Command Center to see embedded iframe
6. Test hot-reload: Edit `App.jsx` and watch changes appear instantly
7. Share tunnel URL with team for collaborative preview

---
## Day 4 Enhancement — March 3, 2026

### Latest changes
Enhanced AEG visualization with task-ledger format support and focused preview:

**Task-Ledger JSON Parser**
- Added support for full task-ledger payload format from Director AI
- Parses `agent_specifications.required_agents`, `agent_dependencies`, and `parallel_execution_groups`
- Auto-generates DAG from agent dependency mappings
- Backward compatible with legacy `nodes/edges` format
- Sample task-ledger embedded for demo without backend (LegalDocs SaaS Platform example)

**Smart Graph Layout**
- Positions agents by parallel execution groups (horizontal stages)
- Groups displayed left-to-right showing execution flow
- Each node shows: Agent role (title-cased), group number, handoff count
- Dependency edges rendered with animated transitions
- Auto-fit view with zoom controls (0.5x - 1.5x)

**Clickable Card Preview with Focus Mode**
- AEG preview now clickable with hover hint ("Click to focus")
- Clicking opens full-screen modal overlay with larger graph canvas
- Focused view: 72vh height, max-width 7xl (1280px+)
- Close button dismisses overlay back to card view
- Card shows project name and data source (Sample Ledger vs Backend API)

**Node Metadata Display**
- Agent names formatted from snake_case to Title Case
- Group level indicator: "Group 1", "Group 2", etc.
- Handoff count shows number of downstream dependencies
- Color-coded states: PENDING (midnight), RUNNING (ember), COMPLETED (emerald), FAILED (red)

**Dual Parser Strategy**
- `normalizeLegacyGraph()`: Handles old `{ nodes, edges }` format
- `normalizeLedgerGraph()`: Handles full task-ledger with `agent_specifications`
- `toFlowGraph()`: Auto-detects format and routes to correct parser
- Graceful error handling for unsupported formats

### Notes
- Task-ledger format expected from backend `/aeg` endpoint
- Sample ledger shows 9-agent LegalDocs SaaS project with 4 execution groups
- Agent dependencies create directed edges (e.g., solution_architect → backend_engineer)
- Ungrouped agents positioned in final column automatically
- Backend can return either format - frontend adapts automatically

### Next steps
1. Click AEG Preview card in Command Center to test focused view
2. Inspect sample task-ledger graph structure and dependencies
3. Implement backend `/aeg` endpoint to return real task-ledger JSON
4. Wire SignalR to update agent node states in real-time during execution
5. Add node click handlers to show agent details/logs in side panel

---
## �🔧 Hotfix — Learning Mode Height Issue

### Latest changes
Fixed Learning Mode tab displaying blank content:

**CSS Layout Fix v3**
- Changed conditional rendering from ternary operator to separate `&&` blocks
- Wrapped LearningMode in `flex flex-1 flex-col` wrapper div
- Added `bg-sand/10` background and `min-h-[500px]` to LearningMode component for visibility
- Added explicit text colors to ensure content is visible

**Root Cause**
- Ternary operator with fragment (`<>...</>`) wasn't properly distributing flex height
- LearningMode component needed explicit wrapper with flex context
- White text on white background caused visibility issues
- React's conditional rendering with fragments didn't establish proper height context

**Resolution**
- Use separate conditional blocks (`activeTab === 'learning' && <...>`)
- Each tab content wrapped in dedicated flex container
- Added background tint and minimum height to LearningMode
- Component now has proper height context from parent

---

## 🔌 Backend Integration Checklist

This section tracks all backend endpoints and services that need to be implemented to connect with the frontend.

### API Endpoints (FastAPI)

**Director Conversation**
- `POST /clarify` - Director clarifies user requirements
  - Request: `{ project_id: string, user_input: string }`
  - Response: `{ director_reply: string, task_ledger_updated: boolean }`
  - File: `platform-backend/api.py`

**Agent Execution Graph**
- `GET /aeg` - Fetch current AEG structure
  - Query: `?project_id=<project_id>`
  - Response: `{ nodes: [{ id, agent_type, state, dependencies }], edges: [{ from, to }] }`
  - File: `platform-backend/api.py`

**Build Execution**
- `POST /execute` - Trigger project build
  - Request: `{ project_id: string }`
  - Response: `{ status: "STARTED" | "FAILED" }`
  - File: `platform-backend/api.py`

**Learning Mode Tutor**
- `POST /tutor/ask` - Ask GPT-4o tutor
  - Request: `{ project_id: string, question: string, context: object }`
  - Response: `{ response: string, level: string, timestamp: string }`
  - Integration: OpenAI GPT-4o API
  - File: `platform-backend/api.py`

### SignalR WebSocket Hub

**Hub URL**: `/hub`
- File: `platform-backend/signalr_hub.py`

**Client Events (Hub → Frontend)**:
- `AgentStatusUpdate` - Agent state changes
  - Payload: `{ agent_id, state, progress, tokens_used, cost, logs[] }`
- `LogMessage` - New log entry
  - Payload: `{ message: string }`
- `CostUpdate` - Token/cost totals updated
  - Payload: `{ tokens: number, cost: number }`

**Connection Handling**:
- Auto-reconnect support
- Broadcast to project_id groups
- Handle disconnect/reconnect gracefully

### Database (Cosmos DB)

**Schema Design** (NoSQL, partition by `project_id`):
- **Task Ledger**: User requirements, clarifications, task breakdown
- **AEG State**: Nodes, edges, current execution state
- **Session History**: Conversation logs, project metadata
- **Agent Logs**: Per-agent execution logs, token usage

Files: `platform-backend/cosmos_client.py`

### Event Grid (Optional)

**Agent Lifecycle Events**:
- Agent started, completed, failed
- Subscribe to these events in `platform-backend/event_handlers.py`
- Broadcast updates via SignalR

### Environment Variables

Backend needs these configured:
```env
# Cosmos DB
COSMOS_ENDPOINT=https://<account>.documents.azure.com:443/
COSMOS_KEY=<key>
COSMOS_DATABASE=command-center

# SignalR Service
SIGNALR_CONNECTION_STRING=<connection-string>

# OpenAI (for Tutor)
OPENAI_API_KEY=<key>
OPENAI_MODEL=gpt-4o

# Azure Event Grid (Optional)
EVENT_GRID_ENDPOINT=<endpoint>
EVENT_GRID_KEY=<key>
```

### CORS Configuration

Frontend runs on `http://localhost:5175` in dev. Backend API must enable:
```python
origins = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    # Add production domains later
]
```

---

## 🔐 Git & Version Control

**.gitignore Configuration**

Three .gitignore files are configured:

1. **Root (.gitignore)** - Project-wide exclusions
   - Node modules, Python cache, virtual environments
   - All .env files (never commit secrets!)
   - IDE/editor files (.vscode, .idea, etc.)
   - Build outputs (dist/, build/, target/)
   - Azure deployment artifacts
   - OS files (.DS_Store, Thumbs.db)

2. **Frontend (platform-frontend/.gitignore)**
   - Node modules and dist folders
   - All .env* files
   - Vite build outputs
   - Editor-specific files

3. **Backend (platform-backend/.gitignore)**
   - Python cache (__pycache__, *.pyc)
   - Virtual environments (venv/, env/)
   - Test coverage reports
   - Distribution builds

**Important**: Never commit:
- `.env` files (API keys, connection strings)
- `node_modules/` directories
- Build artifacts (`dist/`, `build/`)
- Azure credentials or `.azure/` folders

**Repository Setup**:
```bash
# Initialize git (if not already done)
git init

# Add all files
git add .

# First commit
git commit -m "Initial commit: Platform A Command Center"

# Add remote
git remote add origin <your-github-repo-url>

# Push to GitHub
git push -u origin main
```
