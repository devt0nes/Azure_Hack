'''
Purpose: Unit and integration tests for the /menu API endpoint.
Dependencies: unittest (standard library), requests (for HTTP requests).
Author: QA Engineer
'''

import unittest
import requests  # For sending HTTP requests to the API

BASE_URL = "http://localhost:3000"  # Update with your actual base URL


class TestMenuAPI(unittest.TestCase):
    '''
    Tests for the /menu endpoint.
    '''

    def test_menu_response_status(self):
        '''
        Test that the /menu endpoint returns a 200 status code.
        '''
        response = requests.get(f"{BASE_URL}/menu")
        self.assertEqual(response.status_code, 200, "Expected status code 200")

    def test_menu_data_format(self):
        '''
        Test that the /menu endpoint returns data in the correct format.
        '''
        response = requests.get(f"{BASE_URL}/menu")
        data = response.json()

        self.assertIsInstance(data, dict, "Response should be a dictionary")
        self.assertIn("menuItems", data, "Response should contain 'menuItems'")
        self.assertIsInstance(data["menuItems"], list, "'menuItems' should be a list")

        if data["menuItems"]:
            for item in data["menuItems"]:
                self.assertIn("name", item, "Each menu item should have a 'name'")
                self.assertIn("price", item, "Each menu item should have a 'price'")
                self.assertIn("description", item, "Each menu item should have a 'description'")


if __name__ == "__main__":
    unittest.main()