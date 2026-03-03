import unittest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

class TestIntegrationEndpoints(unittest.TestCase):
    def test_user_registration(self):
        """Test user registration API"""
        response = client.post(
            "/register",
            json={"email": "test@example.com", "password": "testpassword"}
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn("id", response.json())

    def test_user_login(self):
        """Test user login API"""
        client.post(
            "/register",
            json={"email": "test@example.com", "password": "testpassword"}
        )
        response = client.post(
            "/login",
            data={"username": "test@example.com", "password": "testpassword"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access_token", response.json())

    def test_get_user_data(self):
        """Test retrieving user data using token"""
        login_response = client.post(
            "/login",
            data={"username": "test@example.com", "password": "testpassword"}
        )
        token = login_response.json()["access_token"]

        response = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "test@example.com")

if __name__ == "__main__":
    unittest.main()