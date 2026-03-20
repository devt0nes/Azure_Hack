"""
Purpose: Security configuration for the cookies website.
Dependencies: Flask, Flask-OAuthlib, python-jose, cryptography
"""

from flask import Flask, request, jsonify
from flask_oauthlib.provider import OAuth2Provider
from jose import jwt
from cryptography.fernet import Fernet

# Flask application setup
app = Flask(__name__)

# Secure configurations
app.config['SECRET_KEY'] = Fernet.generate_key().decode()  # Generate a secure secret key
app.config['DEBUG'] = False  # Disable debug mode in production
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False  # Prevent verbose JSON output
app.config['PREFERRED_URL_SCHEME'] = 'https'  # Force HTTPS

# OAuth2 setup
oauth = OAuth2Provider(app)

# Example OAuth2 token generation
@app.route('/oauth/token', methods=['POST'])
def generate_token():
    """
    Generate an OAuth2 token for user authentication.
    Returns:
        JSON response: Access token
    """
    # Example - Replace this with actual token generation logic
    payload = {
        "user_id": request.json.get("user_id"),
        "exp": 3600  # Token expiration (1 hour)
    }
    token = jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')
    return jsonify({"access_token": token}), 200


# Input sanitization example
@app.route('/submit', methods=['POST'])
def secure_submit():
    """
    Securely handle user input to prevent SQL injection and XSS.
    Returns:
        JSON response: Success message
    """
    user_input = request.json.get("input")
    sanitized_input = sanitize_input(user_input)
    
    # Process sanitized input
    return jsonify({"message": f"Input processed: {sanitized_input}"}), 200


def sanitize_input(user_input: str) -> str:
    """
    Sanitize user input to prevent SQL injection and XSS attacks.
    Args:
        user_input (str): Raw user input
    Returns:
        str: Sanitized input
    """
    # Example sanitization - Replace with a robust library like bleach for HTML sanitization
    sanitized = user_input.replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
    return sanitized


if __name__ == '__main__':
    app.run(ssl_context='adhoc')  # Enable HTTPS with an ad-hoc certificate