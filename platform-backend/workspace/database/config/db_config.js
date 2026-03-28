// MongoDB connection config
module.exports = {
  mongoUri: process.env.MONGO_URI || 'mongodb://localhost:27017',
  dbName: process.env.DB_NAME || 'shoemart',
};
