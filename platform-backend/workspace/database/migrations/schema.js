// MongoDB schema for ShoeMart complaint & chat system
// complaints: stores complaints submitted via API
// complaint_chats: stores chat messages related to complaints

module.exports = {
  complaints: {
    fields: {
      _id: 'ObjectId',
      complaint_id: 'string', // uuid or hex string
      user_id: 'string',
      message: 'string',
      status: 'string',
      category: 'string',
      auto_response: 'string',
      updated_at: 'string', // ISO datetime
    },
    indexes: [
      { fields: { complaint_id: 1 }, options: { unique: true } },
      { fields: { user_id: 1 } }
    ]
  },
  complaint_chats: {
    fields: {
      _id: 'ObjectId',
      complaint_id: 'string', // ref to complaint_id
      sender: 'string',
      message: 'string',
      reply: 'string',
      escalated: 'boolean',
      created_at: 'string', // ISO datetime
    },
    indexes: [
      { fields: { complaint_id: 1 } }
    ]
  }
};
