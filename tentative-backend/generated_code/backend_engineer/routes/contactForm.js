/**
 * Purpose: Define routes for handling contact form submissions.
 * Dependencies: express, uuid
 * Author: Backend Engineer
 */

const express = require('express');
const { v4: uuidv4 } = require('uuid');
const router = express.Router();

// Mock database for contact form submissions
const contactSubmissions = [];

// Route to handle contact form submissions
router.post('/', (req, res) => {
  const { name, email, message } = req.body;

  // Validate input
  if (!name || !email || !message) {
    return res.status(400).json({ error: 'All fields are required.' });
  }

  // Add submission to mock database
  const newSubmission = {
    id: uuidv4(),
    name,
    email,
    message,
    submitted_at: new Date(),
  };

  contactSubmissions.push(newSubmission);

  res.status(201).json({ message: 'Contact form submitted successfully.' });
});

module.exports = router;