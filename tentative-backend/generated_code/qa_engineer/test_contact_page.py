"""
Purpose: Unit tests for the contact page functionality of the bakery website.
Dependencies: unittest (standard Python testing library), requests (for HTTP requests)
Author: QA Engineer
"""

import unittest
import requests

# Base URL where the application is hosted
BASE_URL = "http://localhost:3000/contact"

class TestContactPage(unittest.TestCase):
    """
    Test cases for the contact page functionality.
    """

    def test_contact_page_loads_successfully(self):
        """
        Verify the contact page loads successfully with an HTTP 200 status code.
        """
        response = requests.get(BASE_URL)
        self.assertEqual(response.status_code, 200, "Contact page did not load successfully.")

    def test_contact_form_presence(self):
        """
        Verify the contact page contains a form for submitting inquiries.
        """
        response = requests.get(BASE_URL)
        self.assertIn("<form", response.text, "Contact form not found on contact page.")

if __name__ == "__main__":
    unittest.main()