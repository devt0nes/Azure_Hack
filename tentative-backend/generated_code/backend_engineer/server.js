/**
 * Purpose: Main server file for the Coffee Enthusiast website backend.
 * Author: Backend Engineer
 * Dependencies: express, body-parser, dotenv, cors
 *
 * This file initializes the Express application, sets up middleware,
 * configures routes, and starts the server.
 */

require("dotenv").config(); // Load environment variables from .env
const express = require("express"); // Backend framework for handling HTTP requests
const bodyParser = require("body-parser"); // Middleware for parsing JSON request bodies
const cors = require("cors"); // Middleware for enabling Cross-Origin Resource Sharing (CORS)

// Create Express app
const app = express();

// Middleware configuration
app.use(cors()); // Enable CORS for all origins
app.use(bodyParser.json()); // Parse incoming JSON requests

// API Endpoints
app.get("/", (req, res) => {
  res.send("Welcome to the Coffee Enthusiast API");
});

// Start the server
const PORT = process.env.PORT || 5000;
app.listen(PORT, () => {
  console.log(`Server is running on port ${PORT}`);
});

module.exports = app;