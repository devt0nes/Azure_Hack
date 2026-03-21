/**
 * Purpose: Handles routes related to customer inquiries.
 * Dependencies: Express for routing, Inquiry model for database operations.
 * Author: Backend Engineer Agent
 */

const express = require('express'); // For creating routes
const router = express.Router();
const Inquiry = require('../models/Inquiry'); // MongoDB model for inquiries

/**
 * Submit a customer inquiry.
 * POST /api/contact
 */
router.post('/', async (req, res) => {
  try {
    const { name, email, message } = req.body;
    if (!name || !email || !message) {
      return res.status(400).json({ error: 'All fields are required' });
    }
    const newInquiry = new Inquiry({ name, email, message, timestamp: new Date() });
    await newInquiry.save();
    res.status(200).json({ status: 'success', message: 'Inquiry submitted successfully' });
  } catch (error) {
    res.status(500).json({ error: 'Failed to submit inquiry' });
  }
});

module.exports = router;