const mongoose = require('mongoose');

const EscalationSchema = new mongoose.Schema({
    escalation_id: { type: String, unique: true, required: true },
    complaint_id: { type: String, required: true },
    escalated: { type: Boolean, required: true },
    escalate_message: { type: String },
    timestamp: { type: Date, required: true }
});

module.exports = mongoose.model('Escalation', EscalationSchema);
