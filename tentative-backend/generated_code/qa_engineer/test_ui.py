"""
Purpose: End-to-end tests for the UI functionalities.
Dependencies: unittest, selenium
Author: QA Engineer
"""

import unittest
from selenium import webdriver  # For browser automation
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

class TestColorsUI(unittest.TestCase):
    """
    End-to-end tests for the colors website UI.
    """

    @classmethod
    def setUpClass(cls):
        """
        Setup Selenium WebDriver before tests.
        """
        cls.driver = webdriver.Chrome()  # Use Chrome WebDriver
        cls.driver.get("http://localhost:3000")  # Replace with the actual URL of the website

    @classmethod
    def tearDownClass(cls):
        """
        Close Selenium WebDriver after tests.
        """
        cls.driver.quit()

    def test_homepage_loads(self):
        """
        Test if the homepage loads correctly.
        """
        self.assertIn("Colors", self.driver.title, "Homepage title is incorrect")
        grid = self.driver.find_element(By.ID, "color-grid")
        self.assertTrue(grid.is_displayed(), "Color grid is not displayed")

    def test_color_details(self):
        """
        Test if clicking on a color displays its details.
        """
        first_color = self.driver.find_element(By.CSS_SELECTOR, ".color-item:first-child")
        first_color.click()
        details = self.driver.find_element(By.ID, "color-details")
        self.assertTrue(details.is_displayed(), "Color details are not displayed")
        hex_code = details.find_element(By.ID, "color-hex")
        self.assertTrue(hex_code.text.startswith("#"), "Hex code format is incorrect")

    def test_search_functionality(self):
        """
        Test the search functionality on the homepage.
        """
        search_bar = self.driver.find_element(By.ID, "search-bar")
        search_bar.send_keys("Red")
        search_bar.send_keys(Keys.RETURN)
        search_results = self.driver.find_elements(By.CSS_SELECTOR, ".color-item")
        self.assertGreater(len(search_results), 0, "Search results are empty")

if __name__ == "__main__":
    unittest.main()