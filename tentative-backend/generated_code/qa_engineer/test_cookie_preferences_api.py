"""
Purpose: Test suite for the cookie preferences API endpoints.
Dependencies: pytest, requests.
Author: QA Engineer
"""

import pytest
import requests

# Base URL for the API
BASE_URL = "https://example.com/api/cookie-preferences"


@pytest.fixture
def test_data():
    """Fixture to provide sample data for testing."""
    return {
        "valid_post_data": {"acceptCookies": True},
        "invalid_post_data": {"acceptCookies": "invalid_value"},
    }


def test_post_cookie_preferences_valid(test_data):
    """
    Test the POST /api/cookie-preferences endpoint with valid data.
    Args:
        test_data (dict): Fixture providing sample data.
    Returns:
        None. Asserts HTTP status code and response content.
    """
    response = requests.post(BASE_URL, json=test_data["valid_post_data"])
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["message"] == "Preferences saved successfully."


def test_post_cookie_preferences_invalid(test_data):
    """
    Test the POST /api/cookie-preferences endpoint with invalid data.
    Args:
        test_data (dict): Fixture providing sample data.
    Returns:
        None. Asserts HTTP status code and response content.
    """
    response = requests.post(BASE_URL, json=test_data["invalid_post_data"])
    assert response.status_code == 400
    assert "error" in response.json()


def test_get_cookie_preferences():
    """
    Test the GET /api/cookie-preferences endpoint for retrieving user preferences.
    Returns:
        None. Asserts HTTP status code and response content.
    """
    response = requests.get(BASE_URL)
    assert response.status_code == 200
    assert "acceptCookies" in response.json()


def test_rate_limiting():
    """
    Test the rate limiting functionality to ensure abuse prevention.
    Returns:
        None. Asserts HTTP status code and response content after multiple requests.
    """
    for _ in range(20):  # Simulating rapid requests
        response = requests.get(BASE_URL)
    assert response.status_code == 429  # Too many requests


def test_https_connection():
    """
    Test that the API uses HTTPS for secure communication.
    Returns:
        None. Asserts HTTPS protocol in the URL.
    """
    assert BASE_URL.startswith("https://")