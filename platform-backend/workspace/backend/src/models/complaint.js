const mongoose = require('mongoose');

const ComplaintSchema = new mongoose.Schema({
    complaint_id: { type: String, unique: true, required: true },
    user_id: { type: String, required: true },
    message: { type: String, required: true },
    status: { type: String, required: true },
    category: { type: String, required: true },
    auto_response: { type: String },
    updated_at: { type: Date, required: true }
});

module.exports = mongoose.model('Complaint', ComplaintSchema);
