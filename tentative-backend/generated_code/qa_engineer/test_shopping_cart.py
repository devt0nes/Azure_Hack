"""
Purpose: Unit and Integration tests for the shopping cart functionality.
Dependencies: unittest, requests
Author: QA Engineer
"""

import unittest
import requests

BASE_URL = "http://localhost:3000/api/cart"  # Update this URL as per your backend setup
AUTH_TOKEN = "Bearer <your-token>"  # Replace with a valid token for testing


class TestShoppingCart(unittest.TestCase):
    """
    Test cases for the shopping cart functionality.
    """

    def setUp(self):
        """
        Setup method to initialize headers for authenticated requests.
        """
        self.headers = {"Authorization": AUTH_TOKEN}

    def test_add_item_to_cart_success(self):
        """
        Test adding an item to the shopping cart successfully.
        """
        payload = {"productId": "12345", "quantity": 2}
        response = requests.post(BASE_URL, json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 200, "API should return status code 200")
        self.assertIn("cartId", response.json(), "Response should contain 'cartId'")
        self.assertIn("items", response.json(), "Response should contain 'items'")

    def test_add_item_to_cart_no_auth(self):
        """
        Test adding an item to the shopping cart without authentication.
        """
        payload = {"productId": "12345", "quantity": 2}
        response = requests.post(BASE_URL, json=payload)
        self.assertEqual(
            response.status_code, 401, "API should return status code 401 for unauthorized requests"
        )

    def test_add_item_to_cart_invalid_product(self):
        """
        Test adding an invalid product ID to the shopping cart.
        """
        payload = {"productId": "invalid-id", "quantity": 2}
        response = requests.post(BASE_URL, json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 400, "API should return status code 400 for invalid product ID")
        self.assertIn("error", response.json(), "Response should contain 'error' key")


if __name__ == "__main__":
    unittest.main()