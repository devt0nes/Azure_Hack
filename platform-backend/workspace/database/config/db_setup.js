// Mongo setup script: creates collections, indexes, inserts seed data
const { MongoClient, ObjectId } = require('mongodb');
const config = require('./db_config');
const seedData = require('../migrations/seed_data');

async function setup() {
  const client = new MongoClient(config.mongoUri);
  await client.connect();
  const db = client.db(config.dbName);

  // Complaints collection
  await db.createCollection('complaints');
  await db.collection('complaints').createIndex({ complaint_id: 1 }, { unique: true });
  await db.collection('complaints').createIndex({ user_id: 1 });

  // Complaint chats collection
  await db.createCollection('complaint_chats');
  await db.collection('complaint_chats').createIndex({ complaint_id: 1 });

  // Insert seed data
  await db.collection('complaints').insertMany(seedData.complaints);
  await db.collection('complaint_chats').insertMany(seedData.complaint_chats);

  await client.close();
  console.log('MongoDB setup complete.');
}

if (require.main === module) {
  setup();
}
