"""
Purpose: Unit tests for backend API endpoints in the bakery website project.
Dependencies: unittest, requests
Author: QA Engineer
"""

import unittest
import requests

BASE_URL = "http://localhost:5000/api"

class TestAPIEndpoints(unittest.TestCase):
    """
    Test cases for backend API endpoints.
    """

    def test_get_products(self):
        """
        Test the /api/products endpoint to retrieve the list of bakery products.
        """
        response = requests.get(f"{BASE_URL}/products")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_post_order(self):
        """
        Test the /api/order endpoint to place an order.
        """
        data = {
            "product_id": "123e4567-e89b-12d3-a456-426614174000",
            "quantity": 2,
            "customer_name": "John Doe",
            "customer_email": "john.doe@example.com"
        }
        response = requests.post(f"{BASE_URL}/order", json=data)
        self.assertEqual(response.status_code, 201)
        self.assertIn("order_id", response.json())

    def test_post_contact(self):
        """
        Test the /api/contact endpoint to submit a customer inquiry.
        """
        data = {
            "name": "Jane Doe",
            "email": "jane.doe@example.com",
            "message": "I have a question about your cakes."
        }
        response = requests.post(f"{BASE_URL}/contact", json=data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("success", response.json())

if __name__ == "__main__":
    unittest.main()