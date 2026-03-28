# Customer Complaint Chatbot Frontend

## Overview

React + Vite + Tailwind minimalist chatbot frontend for complaint submission, status tracking, automated support chat, escalation handling, compliant with backend contracts.

## Routes Implemented
- `/` - Complaint entry/list page
- `/complaint/:complaint_id/status` - Complaint status page
- `/complaint/:complaint_id/chat` - Chat for complaint + escalation

## Tech Stack
- React, Vite, Tailwind
- Accessibility: high contrast, keyboard navigation, ARIA, screen reader support

## API Utilities
- All API calls are in `src/api.ts`; see backend_api_contract.json for contract alignment (no drift).

## Setup
- Install dependencies: `npm install`
- Start dev server: `npm run dev` (serves on port 5180)
- Ensure `VITE_API_URL` is set (or defaults to `http://localhost:5100`)

## Custom Theme
- `tailwind.config.js` uses brand color tokens: `primary` (#0077cc), `secondary` (#333333), `background` (#ffffff)

## Accessibility/Design
- Minimalist, calm, professional tone as requested.
- No placeholder pages/components. All routes are production-ready.

## Testing
- Build: `npm run build` (checks for syntax, contract compliance)

## Ownership & File Structure
- All code is inside the `frontend/` directory:
  - `src/pages/` for main route pages
  - `src/components/` for reusable UI elements
  - `src/api.ts` for backend contract interface

---