"""
Purpose: End-to-end tests for the online ordering functionality of the bakery website.
Dependencies: unittest (standard Python testing library), requests (for HTTP requests)
Author: QA Engineer
"""

import unittest
import requests

# Base URL where the application is hosted
BASE_URL = "http://localhost:3000/api/orders"

class TestOnlineOrdering(unittest.TestCase):
    """
    Test cases for the online ordering functionality.
    """

    def test_place_order(self):
        """
        Verify the API endpoint for placing an order works correctly.
        """
        order_details = {
            "customer_name": "John Doe",
            "email": "john.doe@example.com",
            "phone": "1234567890",
            "order_items": [
                {"product_id": "1", "quantity": 2},
                {"product_id": "2", "quantity": 1}
            ],
            "total_price": 30.00
        }
        response = requests.post(BASE_URL, json=order_details)
        self.assertEqual(response.status_code, 201, "Failed to place order.")
        self.assertIn("Order placed successfully", response.json().get("message", ""), "Order placement response incorrect.")

if __name__ == "__main__":
    unittest.main()