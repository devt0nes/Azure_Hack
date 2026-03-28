# Customer Complaint Chatbot Backend

## Setup

1. Install dependencies:
   ```bash
   npm install
   ```
2. Set MongoDB URI in `.env` file:
   ```env
   MONGODB_URI=mongodb://localhost:27017/customer_complaint_chatbot
   PORT=5100
   ```
3. Run the server:
   - Development: `npm run dev`
   - Production: `npm start`

## API Overview

Implements all endpoints from `contracts/backend_api_contract.json`.

### Endpoints
- `POST /api/complaints`: Submit complaint
- `GET /api/complaints/{complaint_id}/status`: Get complaint status
- `GET /api/complaints?user_id={user_id}`: List user complaints
- `POST /api/complaints/{complaint_id}/chat`: Chat with agent/chatbot
- `POST /api/complaints/{complaint_id}/escalate`: Escalate complaint

### Folder Structure
- `src/models/`: Mongoose schemas aligning database fields to contract
- `src/controllers/`: Logic implementing contract-compliant APIs
- `src/routes/`: Route handlers mapped exactly to contract endpoint paths
- `src/config/`: Database connection logic
- `src/app.js`: Express app wiring
- `src/server.js`: Entry point

### Notes
- Zod is used for request validation.
- All MongoDB fields and contract JSON field names are mapped and transformed where necessary.
- Defensive error handling and contract-envelope responses enforced.
