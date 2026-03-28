# backend_engineer Notebook

## TODO
TODO:
1. Inspect upstream database/migrations/schema.js for MongoDB complaint collection structure.
2. Align complaint endpoints in API with DB fields.
3. Plan full implementation for complaint endpoints: POST /api/complaints, GET /api/complaints, GET /api/complaints/:complaint_id/status, POST /api/complaints/:complaint_id/chat, POST /api/complaints/:complaint_id/escalate.
4. Batch-create controllers, service/model, routes, and Express app setup compliant with API contract.
5. Add zod for input validation, helmet, cors, express.json middleware, env config for DB, and README.md.


## ARCHITECTURE
ARCHITECTURE:
- Directory: backend/
- Entry point: backend/app.js (Express application, port 5100)
- Routes: backend/routes/complaints.js (all complaint endpoints per contract)
- Controllers: backend/controllers/complaintsController.js (business logic, contract-aligned responses)
- Model: backend/models/complaintModel.js (MongoDB via Mongoose, field mapping per DB schema)
- Middleware: backend/middleware/validation.js (zod input validation), backend/middleware/errorHandler.js (centralized error)
- DB config: backend/config/db.js (MongoDB connection)
- Security: helmet, cors
- README.md: backend/README.md (setup, API matrix, self-check doc)
- Test: ensure all contract endpoints covered, response shapes match, no extra routes.
