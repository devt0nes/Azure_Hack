"""
Purpose: Unit and integration tests for the API endpoints.
Dependencies: unittest, requests
Author: QA Engineer
"""

import unittest
import requests  # For making HTTP requests to the API

BASE_URL = "http://localhost:3000/api/colors"

class TestColorsAPI(unittest.TestCase):
    """
    Unit and integration tests for the colors API.
    """

    def test_get_all_colors(self):
        """
        Test the /api/colors endpoint for retrieving all colors.
        Ensure the response contains a list of colors with proper attributes.
        """
        response = requests.get(BASE_URL)
        self.assertEqual(response.status_code, 200)
        colors = response.json()
        self.assertIsInstance(colors, list)
        for color in colors:
            self.assertIn("id", color)
            self.assertIn("name", color)
            self.assertIn("hex", color)
            self.assertIn("rgb", color)

    def test_get_color_by_id(self):
        """
        Test the /api/colors/:id endpoint for retrieving a specific color by ID.
        Validate the response contains correct color attributes.
        """
        test_id = 1  # Assuming valid ID exists in the database
        response = requests.get(f"{BASE_URL}/{test_id}")
        self.assertEqual(response.status_code, 200)
        color = response.json()
        self.assertIn("id", color)
        self.assertIn("name", color)
        self.assertIn("hex", color)
        self.assertIn("rgb", color)
        self.assertEqual(color["id"], test_id)

    def test_invalid_color_id(self):
        """
        Test the /api/colors/:id endpoint with an invalid ID.
        Ensure the response returns a 404 status code.
        """
        invalid_id = 99999  # Assuming this ID does not exist
        response = requests.get(f"{BASE_URL}/{invalid_id}")
        self.assertEqual(response.status_code, 404)

    def test_search_colors(self):
        """
        Test the search functionality to filter colors by name or hex code.
        Ensure the response returns relevant results.
        """
        search_query = "Red"
        response = requests.get(f"{BASE_URL}?search={search_query}")
        self.assertEqual(response.status_code, 200)
        colors = response.json()
        self.assertIsInstance(colors, list)
        for color in colors:
            self.assertIn(search_query.lower(), color["name"].lower() or color["hex"].lower())

if __name__ == "__main__":
    unittest.main()