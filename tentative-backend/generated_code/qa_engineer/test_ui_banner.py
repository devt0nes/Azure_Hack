"""
Purpose: Test suite for the cookie awareness website banner functionality.
Dependencies: selenium, pytest.
Author: QA Engineer
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import pytest


@pytest.fixture
def driver():
    """Fixture to initialize and teardown Selenium WebDriver."""
    driver = webdriver.Chrome()  # Ensure chromedriver is installed and in PATH.
    yield driver
    driver.quit()


def test_banner_display(driver):
    """
    Test if the cookie awareness banner is displayed on page load.
    Args:
        driver (WebDriver): Selenium WebDriver instance.
    Returns:
        None. Asserts banner visibility and content.
    """
    driver.get("https://example.com")
    banner = driver.find_element(By.ID, "cookie-banner")
    assert banner.is_displayed()
    assert "We use cookies" in banner.text


def test_accept_cookies(driver):
    """
    Test the functionality of accepting cookies via the banner.
    Args:
        driver (WebDriver): Selenium WebDriver instance.
    Returns:
        None. Asserts user preference storage after action.
    """
    driver.get("https://example.com")
    accept_button = driver.find_element(By.ID, "accept-cookies")
    accept_button.click()
    # Verify that a success message or preference confirmation is displayed.
    success_message = driver.find_element(By.ID, "cookie-success")
    assert success_message.is_displayed()
    assert "Preferences saved" in success_message.text


def test_decline_cookies(driver):
    """
    Test the functionality of declining cookies via the banner.
    Args:
        driver (WebDriver): Selenium WebDriver instance.
    Returns:
        None. Asserts user preference storage after action.
    """
    driver.get("https://example.com")
    decline_button = driver.find_element(By.ID, "decline-cookies")
    decline_button.click()
    # Verify that a success message or preference confirmation is displayed.
    success_message = driver.find_element(By.ID, "cookie-success")
    assert success_message.is_displayed()
    assert "Preferences saved" in success_message.text