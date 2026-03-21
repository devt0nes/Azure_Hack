"""
Purpose: Automated tests for API endpoints of the bakery website backend.
Dependencies: unittest, requests (for HTTP requests)
Author: QA Engineer
"""

import unittest
import requests  # For sending HTTP requests to test the API endpoints


class TestAPIEndpoints(unittest.TestCase):
    """
    Unit tests for API endpoints: /api/products, /api/products/:id, /api/contact
    """

    BASE_URL = "http://localhost:3000"  # Base URL of the backend server

    def test_get_products(self):
        """
        Test the /api/products endpoint to ensure it returns a
        list of products with valid data.
        """
        response = requests.get(f"{self.BASE_URL}/api/products")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, dict)
        self.assertIn("products", data)
        self.assertIsInstance(data["products"], list)
        for product in data["products"]:
            self.assertIn("id", product)
            self.assertIn("name", product)
            self.assertIn("description", product)
            self.assertIn("price", product)
            self.assertIn("image_url", product)

    def test_get_product_details(self):
        """
        Test the /api/products/:id endpoint to ensure it returns
        valid details for a specific product.
        """
        # Replace 'example_id' with a valid product ID for this test
        example_id = "example_id"
        response = requests.get(f"{self.BASE_URL}/api/products/{example_id}")
        self.assertEqual(response.status_code, 200)
        product = response.json()
        self.assertIsInstance(product, dict)
        self.assertIn("id", product)
        self.assertIn("name", product)
        self.assertIn("description", product)
        self.assertIn("price", product)
        self.assertIn("image_url", product)

    def test_post_contact_form(self):
        """
        Test the /api/contact endpoint to ensure it accepts and
        processes contact form submissions correctly.
        """
        payload = {
            "name": "Test User",
            "email": "testuser@example.com",
            "message": "This is a test inquiry."
        }
        response = requests.post(f"{self.BASE_URL}/api/contact", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("status", data)
        self.assertIn("message", data)
        self.assertEqual(data["status"], "success")


if __name__ == "__main__":
    unittest.main()