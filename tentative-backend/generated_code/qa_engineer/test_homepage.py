"""
Purpose: Test the homepage functionality for the coffee website.
Dependencies: unittest, selenium, chromedriver_autoinstaller
Author: QA Engineer
"""

import unittest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
import chromedriver_autoinstaller

# Automatically downloads and sets up the correct ChromeDriver for Selenium
chromedriver_autoinstaller.install()

class TestHomepage(unittest.TestCase):
    """
    Test suite for the homepage functionality of the coffee website.
    """

    @classmethod
    def setUpClass(cls):
        """
        Set up the Chrome WebDriver for the test class.
        """
        cls.driver = webdriver.Chrome()

    def setUp(self):
        """
        Navigate to the homepage before each test.
        """
        self.driver.get("http://localhost:3000")  # Update with the actual URL of the homepage.

    def test_homepage_title(self):
        """
        Test if the homepage title is correct.
        """
        self.assertEqual(self.driver.title, "Coffee Enthusiasts")

    def test_featured_coffees_section(self):
        """
        Test if the featured coffees section is displayed on the homepage.
        """
        featured_section = self.driver.find_element(By.ID, "featured-coffees")
        self.assertTrue(featured_section.is_displayed())

    def test_brewing_methods_section(self):
        """
        Test if the brewing methods section is displayed on the homepage.
        """
        brewing_section = self.driver.find_element(By.ID, "brewing-methods")
        self.assertTrue(brewing_section.is_displayed())

    def test_responsive_design(self):
        """
        Test if the homepage is responsive by resizing the window.
        """
        # Test for mobile view
        self.driver.set_window_size(375, 812)
        mobile_menu = self.driver.find_element(By.ID, "mobile-menu")
        self.assertTrue(mobile_menu.is_displayed())

        # Test for desktop view
        self.driver.set_window_size(1920, 1080)
        desktop_menu = self.driver.find_element(By.ID, "desktop-menu")
        self.assertTrue(desktop_menu.is_displayed())

    def tearDown(self):
        """
        Clear cookies after each test to ensure test isolation.
        """
        self.driver.delete_all_cookies()

    @classmethod
    def tearDownClass(cls):
        """
        Close the WebDriver after all tests are complete.
        """
        cls.driver.quit()

if __name__ == "__main__":
    unittest.main()
