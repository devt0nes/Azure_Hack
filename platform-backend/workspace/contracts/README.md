# Restroom Finder Architecture Contracts

## Overview
This repository contains strict, machine-enforceable contracts for the Restroom Finder application, facilitating:
- User authentication, facility search and updates, reviews, dashboard, notifications, and admin management.

## Technology Stack
- **Backend:** Node.js (Express), Socket.IO, PostgreSQL, Redis
- **Frontend:** React (Vite), Redux, Mapbox GL JS, Tailwind CSS

## Contracts
- `contracts/backend_api_contract.json`: Strict backend API surface for auth, facilities, reviews, admin, notifications, with smoke test marking for each endpoint
- `contracts/frontend_route_contract.json`: Canonical UI route contract, each mapping to backend endpoint IDs, guaranteeing no orphan endpoints or routes

## Startup & Developer Notes
- Backend starts on port 5100; frontend on 5180 (Vite script required)
- See stack root for framework starter template(s) and required scripts (dev/start)
- Do not modify contracts except by system architect policy
