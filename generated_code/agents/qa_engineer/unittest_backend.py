import unittest
from app import app  # Importing the Flask application from the backend

class TestBackendAPI(unittest.TestCase):
    """Unit tests for backend API endpoints."""

    def setUp(self):
        """Set up the test client for the Flask app."""
        self.client = app.test_client()
        self.client.testing = True

    def test_register_user(self):
        """Test the user registration endpoint."""
        response = self.client.post(
            '/register',
            json={
                "username": "testuser",
                "password": "securepassword123"
            }
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn("message", response.json)
        self.assertEqual(response.json["message"], "User registered successfully.")

    def test_login_user(self):
        """Test the user login endpoint."""
        # First, register the user
        self.client.post(
            '/register',
            json={
                "username": "testuser",
                "password": "securepassword123"
            }
        )
        # Then, log in
        response = self.client.post(
            '/login',
            json={
                "username": "testuser",
                "password": "securepassword123"
            }
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("token", response.json)

    def test_protected_route_unauthorized(self):
        """Test accessing a protected route without a token."""
        response = self.client.get('/profile')
        self.assertEqual(response.status_code, 401)
        self.assertIn("message", response.json)
        self.assertEqual(response.json["message"], "Token is missing!")

if __name__ == "__main__":
    unittest.main()