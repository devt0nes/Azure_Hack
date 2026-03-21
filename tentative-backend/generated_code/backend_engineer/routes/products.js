/**
 * Purpose: Define product-related API routes for fetching bakery products and their details.
 * Dependencies: Express for routing, Product model for database interaction.
 * Author: Backend Engineer Agent
 */

const express = require('express');
const router = express.Router();
const Product = require('../models/Product'); // Product model for MongoDB

/**
 * Fetch a list of all bakery products.
 * GET /api/products
 */
router.get('/', async (req, res) => {
  try {
    const products = await Product.find(); // Retrieve all products from the database
    res.status(200).json({ products });
  } catch (error) {
    console.error('Error fetching products:', error);
    res.status(500).json({ message: 'Server error while fetching products.' });
  }
});

/**
 * Fetch details for a specific product.
 * GET /api/products/:id
 */
router.get('/:id', async (req, res) => {
  try {
    const product = await Product.findById(req.params.id); // Retrieve product by ID
    if (!product) {
      return res.status(404).json({ message: 'Product not found.' });
    }
    res.status(200).json(product);
  } catch (error) {
    console.error('Error fetching product details:', error);
    res.status(500).json({ message: 'Server error while fetching product details.' });
  }
});

module.exports = router;