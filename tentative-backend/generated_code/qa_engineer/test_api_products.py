"""
Purpose: Unit testing for the `/api/products` endpoint.
Dependencies: unittest, requests
Author: QA Engineer
"""

import unittest
import requests  # For making HTTP requests to the API

# Base URL of the API
BASE_URL = "http://localhost:3000/api/products"

class TestProductsAPI(unittest.TestCase):
    """
    Unit tests for the `/api/products` endpoint.
    """

    def test_fetch_products_success(self):
        """
        Test to ensure fetching products returns a successful response
        and the response data matches the expected format.
        """
        response = requests.get(BASE_URL)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_fetch_products_rate_limit(self):
        """
        Test to ensure the API handles rate-limiting correctly.
        Simulate exceeding the rate limit defined as 100 requests/minute.
        """
        for _ in range(101):  # Simulate 101 requests
            response = requests.get(BASE_URL)
        self.assertEqual(response.status_code, 429)  # 429 Too Many Requests

    def test_fetch_products_error_handling(self):
        """
        Test to ensure the API responds correctly when the endpoint is unavailable.
        Simulate a server-side error.
        """
        invalid_url = BASE_URL + "/invalid"
        response = requests.get(invalid_url)
        self.assertEqual(response.status_code, 404)  # 404 Not Found


if __name__ == "__main__":
    unittest.main()