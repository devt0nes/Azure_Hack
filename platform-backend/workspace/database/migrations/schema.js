// MongoDB Schema Definition: Restroom Finder
// Contract-driven: backend_api_contract.json

module.exports = {
  users: {
    fields: {
      _id: 'ObjectId',
      username: 'string',
      email: 'string',
      password: 'string',
      role: 'string', // 'user', 'admin', 'manager'
    },
    indexes: [
      { key: { email: 1 }, unique: true },
    ],
  },
  facilities: {
    fields: {
      _id: 'ObjectId',
      name: 'string',
      description: 'string',
      latitude: 'number',
      longitude: 'number',
      amenities: '[string]',
      accessible: 'boolean',
      rating: 'number',
      status: 'string', // 'open', 'closed', 'cleaning', etc
    },
    indexes: [
      { key: { name: 1 } },
      { key: { latitude: 1, longitude: 1 } },
    ],
  },
  reviews: {
    fields: {
      _id: 'ObjectId',
      facilityId: 'ObjectId', // reference to facilities
      userId: 'ObjectId', // reference to users
      rating: 'number',
      review: 'string',
      status: 'string', // 'pending', 'approved', 'rejected'
      createdAt: 'ISODate',
    },
    indexes: [
      { key: { facilityId: 1 } },
      { key: { userId: 1 } },
    ],
  },
  notifications: {
    fields: {
      _id: 'ObjectId',
      facilityId: 'ObjectId', // reference to facilities
      type: 'string',
      message: 'string',
      timestamp: 'ISODate',
    },
    indexes: [
      { key: { facilityId: 1 } },
      { key: { timestamp: -1 } },
    ],
  },
};
