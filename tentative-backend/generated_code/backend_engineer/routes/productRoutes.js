/**
 * Purpose: Routes for managing coffee products (catalog).
 * Dependencies:
 * - express: For creating route handlers.
 * - Product: Mongoose model for products.
 * Author: Backend Engineer
 */

const express = require('express');
const router = express.Router();
const Product = require('../models/Product'); // Mongoose model for products

/**
 * Fetch all products.
 * @route GET /api/products
 * @returns {Array} List of products with images, descriptions, and prices.
 */
router.get('/', async (req, res) => {
  try {
    const products = await Product.find();
    res.status(200).json(products);
  } catch (error) {
    res.status(500).json({ message: 'Error fetching products', error });
  }
});

module.exports = router;