/**
 * Purpose: Mongoose model for coffee products.
 * Fields:
 * - name: Product name (String)
 * - price: Product price (Number)
 * - description: Product description (String)
 * - imageUrl: URL of the product image (String)
 * Author: Backend Engineer
 */

const mongoose = require('mongoose');

const productSchema = new mongoose.Schema({
  name: { type: String, required: true },
  price: { type: Number, required: true },
  description: { type: String, required: true },
  imageUrl: { type: String, required: true },
});

module.exports = mongoose.model('Product', productSchema);