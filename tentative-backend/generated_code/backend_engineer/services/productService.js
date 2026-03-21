/**
 * Purpose: Service layer for handling product-related business logic
 * Dependencies: Database connection
 * Author: Backend Engineer
 */

const { Pool } = require('pg'); // Importing PostgreSQL client

// Set up PostgreSQL connection
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
});

// Function to retrieve all products
const getProducts = async () => {
  const query = 'SELECT * FROM products';
  const { rows } = await pool.query(query);
  return rows;
};

module.exports = { getProducts };