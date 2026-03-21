"""
Purpose: UI Testing for the website on types of colours.
Dependencies: selenium, pytest
Author: QA Engineer Agent
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import pytest

@pytest.fixture(scope="module")
def setup_driver():
    """Setup Selenium WebDriver for testing"""
    driver = webdriver.Chrome()  # Ensure ChromeDriver is installed
    driver.get("http://localhost:3000")  # Update URL if hosted
    yield driver
    driver.quit()

def test_homepage_title(setup_driver):
    """
    Test to verify the homepage title.
    Args:
        setup_driver: Selenium WebDriver instance
    """
    driver = setup_driver
    assert "Types of Colours" in driver.title, "Homepage title does not match."

def test_navigation_bar(setup_driver):
    """
    Test to verify the navigation bar functionality.
    Args:
        setup_driver: Selenium WebDriver instance
    """
    driver = setup_driver
    navbar = driver.find_element(By.ID, "navbar")
    assert navbar.is_displayed(), "Navigation bar is not visible."
    
    links = navbar.find_elements(By.TAG_NAME, "a")
    assert len(links) > 0, "No navigation links found in the navigation bar."
    for link in links:
        assert link.is_displayed(), f"Navigation link '{link.text}' is not visible."

def test_colour_sections(setup_driver):
    """
    Test to ensure each colour type section is present and properly displayed.
    Args:
        setup_driver: Selenium WebDriver instance
    """
    driver = setup_driver
    sections = driver.find_elements(By.CLASS_NAME, "colour-section")
    assert len(sections) > 0, "No colour sections found on the website."

    for section in sections:
        title = section.find_element(By.TAG_NAME, "h2")
        description = section.find_element(By.TAG_NAME, "p")
        examples = section.find_elements(By.CLASS_NAME, "colour-example")
        assert title.is_displayed(), "Section title is not visible."
        assert description.is_displayed(), "Section description is not visible."
        assert len(examples) > 0, "No examples found in colour section."

def test_responsive_design(setup_driver):
    """
    Test to verify website responsiveness using window resizing.
    Args:
        setup_driver: Selenium WebDriver instance
    """
    driver = setup_driver
    driver.set_window_size(1024, 768)
    assert driver.find_element(By.ID, "navbar").is_displayed(), "Navigation bar not visible in desktop view."

    driver.set_window_size(375, 667)  # Typical mobile size
    assert driver.find_element(By.ID, "navbar").is_displayed(), "Navigation bar not visible in mobile view."

def test_api_integration(setup_driver):
    """
    Test to verify integration with the API endpoint.
    Args:
        setup_driver: Selenium WebDriver instance
    """
    driver = setup_driver
    api_section = driver.find_element(By.ID, "api-data")
    assert api_section.is_displayed(), "API section is not visible."

    data_items = api_section.find_elements(By.CLASS_NAME, "data-item")
    assert len(data_items) > 0, "No data items found from the API."