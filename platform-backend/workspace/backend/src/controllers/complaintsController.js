const { z } = require('zod');
const Complaint = require('../models/complaint');
const ComplaintChat = require('../models/complaintChat');
const Escalation = require('../models/escalation');
const { v4: uuidv4 } = require('uuid');

// Zod schemas as per contract
const submitComplaintSchema = z.object({
    user_id: z.string(),
    message: z.string()
});
const chatWithAgentSchema = z.object({
    sender: z.string(),
    message: z.string()
});

// Helpers
function categorizeComplaint(message) {
    if (/late|delay/i.test(message)) return 'delivery';
    if (/refund|return/i.test(message)) return 'refund';
    return 'general';
}
function autoRespond(category) {
    if (category === 'delivery') return 'We are investigating your delivery issue.';
    if (category === 'refund') return 'Refund request received, processing.';
    return 'Thank you for contacting support.';
}

exports.submitComplaint = async (req, res) => {
    try {
        const parsed = submitComplaintSchema.safeParse(req.body);
        if (!parsed.success) {
            return res.status(400).json({ error: 'Invalid request body' });
        }
        const { user_id, message } = parsed.data;
        const category = categorizeComplaint(message);
        const status = 'acknowledged';
        const complaint_id = uuidv4();
        const auto_response = autoRespond(category);
        const complaint = new Complaint({
            complaint_id,
            user_id,
            message,
            status,
            category,
            auto_response,
            updated_at: new Date()
        });
        await complaint.save();
        return res.status(200).json({
            complaint_id,
            status,
            category,
            auto_response
        });
    } catch (err) {
        console.error('[submitComplaint]', err);
        return res.status(500).json({ error: 'Server error' });
    }
};

exports.getComplaintStatus = async (req, res) => {
    try {
        const { complaint_id } = req.params;
        if (!complaint_id) {
            return res.status(400).json({ error: 'Missing complaint_id' });
        }
        const complaint = await Complaint.findOne({ complaint_id });
        if (!complaint) {
            return res.status(404).json({ error: 'Complaint not found' });
        }
        return res.status(200).json({
            complaint_id,
            status: complaint.status,
            updated_at: complaint.updated_at.toISOString()
        });
    } catch (err) {
        console.error('[getComplaintStatus]', err);
        return res.status(500).json({ error: 'Server error' });
    }
};

exports.listComplaints = async (req, res) => {
    try {
        const { user_id } = req.query;
        if (!user_id) {
            return res.status(400).json({ error: 'Missing user_id' });
        }
        const complaints = await Complaint.find({ user_id });
        const result = complaints.map(c => ({
            complaint_id: c.complaint_id,
            status: c.status,
            category: c.category,
            updated_at: c.updated_at.toISOString()
        }));
        return res.status(200).json({ complaints: result });
    } catch (err) {
        console.error('[listComplaints]', err);
        return res.status(500).json({ error: 'Server error' });
    }
};

exports.chatWithAgent = async (req, res) => {
    try {
        const { complaint_id } = req.params;
        const parsed = chatWithAgentSchema.safeParse(req.body);
        if (!complaint_id || !parsed.success) {
            return res.status(400).json({ error: 'Invalid complaint_id or request body' });
        }
        const { sender, message } = parsed.data;
        // Basic escalation keyword check
        let escalated = false;
        let reply = 'Thank you, your message has been received.';
        if (/human|escalate|agent/i.test(message)) {
            escalated = true;
            reply = 'Your complaint will be reviewed by a human agent.';
            await Complaint.updateOne({ complaint_id }, { status: 'escalated', updated_at: new Date() });
            await Escalation.create({ escalation_id: uuidv4(), complaint_id, escalated: true, escalate_message: message, timestamp: new Date() });
        }
        await ComplaintChat.create({ chat_id: uuidv4(), complaint_id, sender, message, timestamp: new Date(), escalated });
        return res.status(200).json({ reply, escalated });
    } catch (err) {
        console.error('[chatWithAgent]', err);
        return res.status(500).json({ error: 'Server error' });
    }
};

exports.escalateComplaint = async (req, res) => {
    try {
        const { complaint_id } = req.params;
        if (!complaint_id) {
            return res.status(400).json({ error: 'Missing complaint_id' });
        }
        await Complaint.updateOne({ complaint_id }, { status: 'escalated', updated_at: new Date() });
        await Escalation.create({ escalation_id: uuidv4(), complaint_id, escalated: true, escalate_message: 'Manual escalation', timestamp: new Date() });
        return res.status(200).json({ escalated: true, message: 'Complaint escalated to a human agent.' });
    } catch (err) {
        console.error('[escalateComplaint]', err);
        return res.status(500).json({ error: 'Server error' });
    }
};
