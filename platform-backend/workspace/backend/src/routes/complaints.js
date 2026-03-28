const express = require('express');
const router = express.Router();
const complaintsController = require('../controllers/complaintsController');

// POST /api/complaints
router.post('/', complaintsController.submitComplaint);
// GET /api/complaints/:complaint_id/status
router.get('/:complaint_id/status', complaintsController.getComplaintStatus);
// GET /api/complaints?user_id=:user_id
router.get('/', complaintsController.listComplaints);
// POST /api/complaints/:complaint_id/chat
router.post('/:complaint_id/chat', complaintsController.chatWithAgent);
// POST /api/complaints/:complaint_id/escalate
router.post('/:complaint_id/escalate', complaintsController.escalateComplaint);

module.exports = router;
