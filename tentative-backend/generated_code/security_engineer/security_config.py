"""
Purpose: Security configuration for the bakery website backend.
Dependencies: cryptography, PyJWT, flask, flask_limiter, werkzeug
Author: Security Engineer Agent
"""

import os
from cryptography.fernet import Fernet  # For encrypting sensitive data
import jwt  # For JSON Web Tokens (JWT) handling
from flask import request, jsonify  # For handling API requests and responses
from werkzeug.security import generate_password_hash, check_password_hash  # For password hashing
from flask_limiter import Limiter  # For rate limiting API endpoints

# Generate encryption keys for sensitive data
def generate_encryption_key():
    """
    Generates and returns a new encryption key for secure data storage.

    Returns:
        str: Encryption key.
    """
    key = Fernet.generate_key()
    return key.decode()

# Function for encrypting sensitive data
def encrypt_data(data: str, key: str) -> str:
    """
    Encrypts sensitive data using the provided encryption key.

    Args:
        data (str): The data to encrypt.
        key (str): The encryption key.

    Returns:
        str: Encrypted data.
    """
    fernet = Fernet(key.encode())
    encrypted_data = fernet.encrypt(data.encode())
    return encrypted_data.decode()

# Function for decrypting sensitive data
def decrypt_data(encrypted_data: str, key: str) -> str:
    """
    Decrypts sensitive data using the provided encryption key.

    Args:
        encrypted_data (str): The encrypted data.
        key (str): The encryption key.

    Returns:
        str: Decrypted data.
    """
    fernet = Fernet(key.encode())
    decrypted_data = fernet.decrypt(encrypted_data.encode())
    return decrypted_data.decode()

# JWT Utility functions
def generate_jwt(payload: dict, secret_key: str) -> str:
    """
    Generates a JWT token for API authentication.

    Args:
        payload (dict): The payload to include in the token.
        secret_key (str): The secret key for signing the token.

    Returns:
        str: Encoded JWT token.
    """
    token = jwt.encode(payload, secret_key, algorithm='HS256')
    return token

def validate_jwt(token: str, secret_key: str) -> dict:
    """
    Validates a JWT token and decodes its payload.

    Args:
        token (str): The JWT token to validate.
        secret_key (str): The secret key for decoding the token.

    Returns:
        dict: Decoded payload.
    """
    try:
        payload = jwt.decode(token, secret_key, algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        return {"error": "Token has expired"}
    except jwt.InvalidTokenError:
        return {"error": "Invalid token"}

# Password hashing utilities
def hash_password(password: str) -> str:
    """
    Hashes a password for secure storage.

    Args:
        password (str): The plain text password to hash.

    Returns:
        str: The hashed password.
    """
    return generate_password_hash(password)

def check_password(password: str, hashed_password: str) -> bool:
    """
    Checks if a password matches its hashed version.

    Args:
        password (str): The plain text password.
        hashed_password (str): The hashed password.

    Returns:
        bool: True if the password matches, False otherwise.
    """
    return check_password_hash(hashed_password, password)

# Flask Limiter setup
def setup_rate_limiting(app):
    """
    Configures rate limiting for the Flask application.

    Args:
        app (Flask): The Flask application instance.
    """
    limiter = Limiter(app, key_func=lambda: request.remote_addr)
    return limiter