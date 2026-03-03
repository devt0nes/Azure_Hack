import unittest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

class TestEndToEnd(unittest.TestCase):
    def test_complete_user_flow(self):
        """Test end-to-end user flow: registration -> login -> data retrieval"""
        # Step 1: Register User
        register_response = client.post(
            "/register",
            json={"email": "testuser@example.com", "password": "testpassword"}
        )
        self.assertEqual(register_response.status_code, 201)
        self.assertIn("id", register_response.json())

        # Step 2: Login User
        login_response = client.post(
            "/login",
            data={"username": "testuser@example.com", "password": "testpassword"}
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertIn("access_token", login_response.json())
        token = login_response.json()["access_token"]

        # Step 3: Retrieve User Data
        user_data_response = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(user_data_response.status_code, 200)
        self.assertEqual(user_data_response.json()["email"], "testuser@example.com")

if __name__ == "__main__":
    unittest.main()