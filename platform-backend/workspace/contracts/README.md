# ShoeMart System Architecture Contracts

**This directory contains the core architecture contracts for project initialization.**

## Scaffolding
- Frontend: React + Vite + TypeScript template initialized in `/frontend`
- Backend: Node.js + Express + MongoDB template initialized in `/backend`

## Contracts
- `contracts/backend_api_contract.json` — Backend API contract (canonical, machine-readable)
- `contracts/frontend_route_contract.json` — Frontend route contract (explicit endpoint dependencies)

**Startup Standards:**
- Backend dev port: `5100`
- Frontend dev port: `5180`
- Backend and frontend both bootstrapped for production workflows.

**Important:**
- All endpoints (and all frontend routes) are fully machine-parseable and validated for reachability.
- No implementation code exists in this layer.
