/**
 * Purpose: Test API endpoints for the bakery project backend.
 * Dependencies: jest, supertest
 * Author: QA Engineer
 */

const request = require('supertest'); // For HTTP request testing
const app = require('../app'); // Import the Express app

describe('API Endpoints', () => {
  /**
   * Test the GET /api/products endpoint
   */
  describe('GET /api/products', () => {
    it('should return a list of products with status 200', async () => {
      const response = await request(app).get('/api/products');
      expect(response.status).toBe(200);
      expect(response.body).toHaveProperty('products');
      expect(Array.isArray(response.body.products)).toBe(true);
    });

    it('should filter products by category when category query param is provided', async () => {
      const response = await request(app).get('/api/products?category=Pastry');
      expect(response.status).toBe(200);
      expect(response.body.products.every(product => product.category === 'Pastry')).toBe(true);
    });
  });

  /**
   * Test the POST /api/orders endpoint
   */
  describe('POST /api/orders', () => {
    it('should successfully place an order and return status 201', async () => {
      const orderDetails = {
        customer_name: 'John Doe',
        items: [
          { productId: 1, quantity: 2 },
          { productId: 2, quantity: 1 },
        ],
        total: 8.0,
      };

      const response = await request(app)
        .post('/api/orders')
        .send(orderDetails)
        .set('Content-Type', 'application/json');

      expect(response.status).toBe(201);
      expect(response.body).toHaveProperty('message', 'Order successfully placed');
      expect(response.body).toHaveProperty('orderId');
    });

    it('should return a 400 error if order details are missing or incomplete', async () => {
      const response = await request(app)
        .post('/api/orders')
        .send({})
        .set('Content-Type', 'application/json');

      expect(response.status).toBe(400);
      expect(response.body).toHaveProperty('error');
    });
  });
});