/**
 * Purpose: Defines the schema and model for customer inquiries.
 * Dependencies: Mongoose for schema and model creation.
 * Author: Backend Engineer Agent
 */

const mongoose = require('mongoose');

const inquirySchema = new mongoose.Schema({
  name: { type: String, required: true },
  email: { type: String, required: true },
  message: { type: String, required: true },
  timestamp: { type: Date, default: Date.now },
});

const Inquiry = mongoose.model('Inquiry', inquirySchema);

module.exports = Inquiry;