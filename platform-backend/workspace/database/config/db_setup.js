// MongoDB Setup Script: creates collections, indexes, and seeds
const { MongoClient } = require('mongodb');
const schema = require('../migrations/schema');
const seedData = require('../migrations/seed_data');
const config = require('./db_config');

async function setup() {
  const client = new MongoClient(config.uri);
  await client.connect();
  const db = client.db(config.dbName);

  // Create collections and indexes
  for (const [collName, def] of Object.entries(schema)) {
    const coll = db.collection(collName);
    for (const idx of def.indexes || []) {
      await coll.createIndex(idx.key, { unique: idx.unique || false });
    }
  }

  // Seed data
  for (const [collName, docs] of Object.entries(seedData)) {
    const coll = db.collection(collName);
    await coll.deleteMany({}); // Clean collection
    if (docs.length) {
      await coll.insertMany(docs);
    }
  }

  await client.close();
  console.log('MongoDB setup and seed complete.');
}

if (require.main === module) {
  setup();
}
