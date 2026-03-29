# Restroom Finder Frontend

## Overview
Modern, map-focused, community-driven React (Vite, TypeScript, Tailwind) frontend for Restroom Finder. Implements all routes and API integration per contract.

## File Structure
- src/
  - api/        # API utilities (contract-aligned)
  - pages/      # Per-route page components
  - components/ # Presentational (UI, Map, etc.)
  - App.tsx     # Route shell
  - main.tsx    # Bootstrap
- index.html    # Vite entry, mounts /src/main.tsx

## Scripts
- `npm run dev` (port 5180)
- `npm run build`

## Env
- .env.example for env variables (set VITE_API_URL)

## Contracts
See /contracts for endpoint and route contract; DO NOT drift from schema spec.

## THEME
Theme tokens for brand colors, fonts set in tailwind.config.js. All UI uses utility classes from those tokens.
