// MongoDB Seed Data: Restroom Finder
// Insert sample users, facilities, reviews, notifications

const { ObjectId } = require('mongodb');

module.exports = {
  users: [
    {
      _id: ObjectId('507f191e810c19729de860ea'),
      username: 'testuser',
      email: 'testuser@mail.com',
      password: 'P@ssw0rd', // Hash in app
      role: 'user',
    },
    {
      _id: ObjectId('507f191e810c19729de860eb'),
      username: 'facilityadmin',
      email: 'admin@mail.com',
      password: 'Admin!123', // Hash in app
      role: 'admin',
    },
  ],
  facilities: [
    {
      _id: ObjectId('609d1459278a3e3b3c154123'),
      name: 'Rest Area 1',
      description: 'Clean restroom',
      latitude: 40.7128,
      longitude: -74.0060,
      amenities: ['baby-changing', 'wheelchair'],
      accessible: true,
      rating: 4.7,
      status: 'open',
    },
  ],
  reviews: [
    {
      _id: ObjectId('709d1459278a3e3b3c154101'),
      facilityId: ObjectId('609d1459278a3e3b3c154123'),
      userId: ObjectId('507f191e810c19729de860ea'),
      rating: 5,
      review: 'Clean and well maintained',
      status: 'approved',
      createdAt: new Date('2024-06-01T10:00:00Z'),
    },
  ],
  notifications: [
    {
      _id: ObjectId('809d1459278a3e3b3c154241'),
      facilityId: ObjectId('609d1459278a3e3b3c154123'),
      type: 'status_change',
      message: 'Facility is now open',
      timestamp: new Date('2024-06-01T10:10:00Z'),
    },
  ],
};
