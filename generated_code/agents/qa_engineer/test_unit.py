import unittest
from app.routers.auth import authenticate_user
from app.utils.auth_utils import create_access_token
from app.models import User
from app.database import get_db
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

class TestAuthentication(unittest.TestCase):
    def setUp(self):
        # Setup test database connection
        self.db = next(get_db())

    def tearDown(self):
        # Close database connection
        self.db.close()

    def test_authenticate_user_valid_credentials(self):
        """Test user authentication with valid credentials"""
        test_user = User(email="test@example.com", hashed_password="hashed_password")
        self.db.add(test_user)
        self.db.commit()

        result = authenticate_user(self.db, "test@example.com", "correct_password")
        self.assertIsInstance(result, User)

    def test_authenticate_user_invalid_credentials(self):
        """Test user authentication with invalid credentials"""
        result = authenticate_user(self.db, "test@example.com", "wrong_password")
        self.assertIsNone(result)

    def test_create_access_token(self):
        """Test access token generation"""
        data = {"sub": "test_user"}
        token = create_access_token(data)
        self.assertTrue(isinstance(token, str))

    def test_login_endpoint(self):
        """Test the login endpoint"""
        response = client.post(
            "/login",
            data={"username": "test_user", "password": "test_password"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access_token", response.json())

if __name__ == "__main__":
    unittest.main()