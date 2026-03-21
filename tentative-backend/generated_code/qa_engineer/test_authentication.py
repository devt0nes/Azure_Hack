"""
Purpose: Test suite for User Authentication and Account Management functionalities.
Dependencies: Pytest library for test execution, requests for API testing.
Author: QA Engineer
"""

import pytest
import requests

# Base URL of the backend API
BASE_URL = "http://localhost:5000/api"  # Replace with the actual base URL

@pytest.fixture
def user_credentials():
    """
    Fixture to provide a set of sample user credentials for testing.
    """
    return {
        "email": "testuser@example.com",
        "password": "securepassword123"
    }

def test_user_registration(user_credentials):
    """
    Test case to verify that a new user can register successfully.
    """
    response = requests.post(f"{BASE_URL}/auth/register", json=user_credentials)
    assert response.status_code == 201, "Registration failed"
    assert "user_id" in response.json(), "User ID not returned in response"

def test_user_login(user_credentials):
    """
    Test case to verify that a registered user can log in successfully.
    """
    # Ensure the user is already registered
    requests.post(f"{BASE_URL}/auth/register", json=user_credentials)

    # Attempt to log in
    response = requests.post(f"{BASE_URL}/auth/login", json=user_credentials)
    assert response.status_code == 200, "Login failed"
    assert "token" in response.json(), "Token not returned in response"

def test_duplicate_registration(user_credentials):
    """
    Test case to verify that duplicate registrations are not allowed.
    """
    # Register the user
    requests.post(f"{BASE_URL}/auth/register", json=user_credentials)
    
    # Attempt to register the same user again
    response = requests.post(f"{BASE_URL}/auth/register", json=user_credentials)
    assert response.status_code == 409, "Duplicate registration allowed"
    assert "error" in response.json(), "Error message not returned for duplicate registration"