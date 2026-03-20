/**
 * Purpose: Backend server initialization for the "Project from clarification".
 * Dependencies:
 *   - express: HTTP server framework.
 *   - mongoose: MongoDB object modeling tool for database interactions.
 *   - dotenv: Environment variable management.
 *   - cors: Middleware for Cross-Origin Resource Sharing.
 * Author: Backend Engineer Agent
 */

const express = require('express'); // For creating the HTTP server and routing.
const mongoose = require('mongoose'); // For interacting with the MongoDB database.
const dotenv = require('dotenv'); // For managing environment variables securely.
const cors = require('cors'); // For enabling CORS in the server.

dotenv.config(); // Load environment variables from .env file.

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware setup
app.use(cors()); // Enable CORS for all routes.
app.use(express.json()); // Parse JSON payloads.
app.use(express.urlencoded({ extended: true })); // Parse URL-encoded payloads.

// Database connection
mongoose
  .connect(process.env.DATABASE_URL, {
    useNewUrlParser: true,
    useUnifiedTopology: true,
  })
  .then(() => console.log('Connected to MongoDB'))
  .catch((err) => console.error('Error connecting to MongoDB:', err));

// Placeholder routes
app.get('/', (req, res) => {
  res.send('Welcome to the Cookie Website API!');
});

// Start server
app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`);
});

module.exports = app;