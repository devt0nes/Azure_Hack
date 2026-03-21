"""
Purpose: Unit and Integration tests for the product catalog functionality.
Dependencies: unittest, requests
Author: QA Engineer
"""

import unittest
import requests  # For sending HTTP requests to the API

BASE_URL = "http://localhost:3000/api/products"  # Update this URL as per your backend setup


class TestProductCatalog(unittest.TestCase):
    """
    Test cases for the product catalog functionality.
    """

    def test_get_products_success(self):
        """
        Test that the product catalog API returns a successful response
        and contains the expected data.
        """
        response = requests.get(BASE_URL)
        self.assertEqual(response.status_code, 200, "Expected status code 200")
        self.assertIsInstance(response.json(), list, "Expected response to be a list of products")

    def test_get_products_invalid_method(self):
        """
        Test that using an invalid HTTP method (e.g., POST) on the product catalog endpoint
        returns the correct error response.
        """
        response = requests.post(BASE_URL)
        self.assertEqual(response.status_code, 405, "Expected status code 405 for invalid method")


if __name__ == "__main__":
    unittest.main()