const mongoose = require('mongoose');

const ComplaintChatSchema = new mongoose.Schema({
    chat_id: { type: String, unique: true, required: true },
    complaint_id: { type: String, required: true },
    sender: { type: String, required: true },
    message: { type: String, required: true },
    timestamp: { type: Date, required: true },
    escalated: { type: Boolean, default: false }
});

module.exports = mongoose.model('ComplaintChat', ComplaintChatSchema);
