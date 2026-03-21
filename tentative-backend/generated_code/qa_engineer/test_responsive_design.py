"""
Purpose: Responsiveness tests for the bakery website to ensure it works on various screen sizes.
Dependencies: selenium (for browser automation), unittest (standard Python testing library)
Author: QA Engineer
"""

import unittest
from selenium import webdriver

class TestResponsiveDesign(unittest.TestCase):
    """
    Test cases for the responsive design of the bakery website.
    """

    @classmethod
    def setUpClass(cls):
        """
        Set up Selenium WebDriver for testing.
        """
        cls.driver = webdriver.Chrome()

    @classmethod
    def tearDownClass(cls):
        """
        Quit the WebDriver after testing.
        """
        cls.driver.quit()

    def test_responsive_design_mobile(self):
        """
        Verify the website displays correctly on a mobile screen size.
        """
        self.driver.set_window_size(375, 667)  # iPhone 6/7/8 dimensions
        self.driver.get("http://localhost:3000")
        self.assertIn("Welcome to our bakery", self.driver.page_source, "Website not displaying correctly on mobile screen.")

    def test_responsive_design_tablet(self):
        """
        Verify the website displays correctly on a tablet screen size.
        """
        self.driver.set_window_size(768, 1024)  # iPad dimensions
        self.driver.get("http://localhost:3000")
        self.assertIn("Welcome to our bakery", self.driver.page_source, "Website not displaying correctly on tablet screen.")

    def test_responsive_design_desktop(self):
        """
        Verify the website displays correctly on a desktop screen size.
        """
        self.driver.set_window_size(1920, 1080)  # Full HD dimensions
        self.driver.get("http://localhost:3000")
        self.assertIn("Welcome to our bakery", self.driver.page_source, "Website not displaying correctly on desktop screen.")

if __name__ == "__main__":
    unittest.main()