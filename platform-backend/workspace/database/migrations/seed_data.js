// Seed data for Mongo bootstrapping
const { ObjectId } = require('mongodb');

module.exports = {
  complaints: [
    {
      _id: new ObjectId(),
      complaint_id: 'abc-123',
      user_id: 'user-001',
      message: 'Late delivery',
      status: 'open',
      category: 'delivery',
      auto_response: 'Your complaint has been logged. We are investigating.',
      updated_at: new Date().toISOString(),
    },
    {
      _id: new ObjectId(),
      complaint_id: 'def-456',
      user_id: 'user-002',
      message: 'Received wrong size',
      status: 'open',
      category: 'product',
      auto_response: 'Thank you for reporting. Our team will contact you.',
      updated_at: new Date().toISOString(),
    }
  ],
  complaint_chats: [
    {
      _id: new ObjectId(),
      complaint_id: 'abc-123',
      sender: 'user',
      message: 'Any update?',
      reply: 'We are working on your complaint.',
      escalated: false,
      created_at: new Date().toISOString(),
    },
    {
      _id: new ObjectId(),
      complaint_id: 'def-456',
      sender: 'user',
      message: 'Need this solved urgently.',
      reply: 'Escalated to support.',
      escalated: true,
      created_at: new Date().toISOString(),
    }
  ]
};
