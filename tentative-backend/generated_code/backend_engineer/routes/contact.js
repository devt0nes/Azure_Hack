/**
 * Purpose: Handle contact form submissions via the API.
 * Dependencies: express, uuid
 * Author: Backend Engineer
 */

const express = require('express');
const { v4: uuidv4 } = require('uuid');
const router = express.Router();

// Mock database for contact form submissions
const contactSubmissions = [];

// POST /api/contact
// Submit a contact form inquiry
router.post('/', (req, res) => {
  const { name, email, message } = req.body;

  // Input validation
  if (!name || !email || !message) {
    return res.status(400).json({ error: 'Name, email, and message are required.' });
  }

  // Create a new contact submission
  const newSubmission = {
    id: uuidv4(),
    name,
    email,
    message,
    submitted_at: new Date().toISOString(),
  };

  // Save the submission (mock database for now)
  contactSubmissions.push(newSubmission);

  res.status(201).json({ message: 'Contact form submitted successfully' });
});

module.exports = router;