// MongoDB connection configuration
module.exports = {
  uri: process.env.MONGO_URI || 'mongodb://localhost:27017/restroomfinder',
  dbName: 'restroomfinder',
};
