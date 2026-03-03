import hashlib
import hmac
import os

class AuthenticationManager:
    """
    Class to handle authentication securely.
    Implements password hashing and token generation.
    """
    def __init__(self):
        self.secret = os.getenv("SECRET_KEY", "default_secret_key")

    def hash_password(self, password: str) -> str:
        """
        Hash a password using SHA256.
        """
        return hashlib.sha256(password.encode()).hexdigest()

    def verify_password(self, password: str, hashed_password: str) -> bool:
        """
        Verify if the hashed password matches the input password.
        """
        return self.hash_password(password) == hashed_password

    def generate_token(self, data: str) -> str:
        """
        Generate a secure token using HMAC.
        """
        return hmac.new(self.secret.encode(), data.encode(), hashlib.sha256).hexdigest()

    def verify_token(self, token: str, data: str) -> bool:
        """
        Verify if the token matches the data.
        """
        expected_token = self.generate_token(data)
        return hmac.compare_digest(expected_token, token)

# Example usage
if __name__ == "__main__":
    auth_manager = AuthenticationManager()
    hashed_pwd = auth_manager.hash_password("my_secure_password")
    print(f"Hashed password: {hashed_pwd}")
    print(f"Password verification: {auth_manager.verify_password('my_secure_password', hashed_pwd)}")

    token = auth_manager.generate_token("user_id_12345")
    print(f"Generated token: {token}")
    print(f"Token verification: {auth_manager.verify_token(token, 'user_id_12345')}")