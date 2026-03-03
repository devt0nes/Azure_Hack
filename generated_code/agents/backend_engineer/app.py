from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager, create_access_token, jwt_required
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///test.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'supersecretkey')

# Initialize extensions
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
jwt = JWTManager(app)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True)
    email = db.Column(db.String(120), nullable=False, unique=True)
    password = db.Column(db.String(200), nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email
        }

# Routes
@app.route('/api/v1/users', methods=['POST'])
def create_user():
    """
    Create a new user.
    """
    data = request.get_json()
    if not data or not all(key in data for key in ('username', 'email', 'password')):
        return jsonify({"message": "Invalid input"}), 400

    hashed_password = bcrypt.generate_password_hash(data['password']).decode('utf-8')
    new_user = User(username=data['username'], email=data['email'], password=hashed_password)
    
    try:
        db.session.add(new_user)
        db.session.commit()
        return jsonify(new_user.to_dict()), 201
    except Exception as e:
        return jsonify({"message": "Error creating user", "error": str(e)}), 500

@app.route('/api/v1/users/<int:user_id>', methods=['GET'])
@jwt_required()
def get_user(user_id):
    """
    Get a specific user by ID.
    """
    user = User.query.get_or_404(user_id)
    return jsonify(user.to_dict())

@app.route('/api/v1/users/login', methods=['POST'])
def login_user():
    """
    Authenticate a user and return a JWT token.
    """
    data = request.get_json()
    if not data or not all(key in data for key in ('email', 'password')):
        return jsonify({"message": "Invalid input"}), 400

    user = User.query.filter_by(email=data['email']).first()
    if user and bcrypt.check_password_hash(user.password, data['password']):
        token = create_access_token(identity=user.id)
        return jsonify({"token": token}), 200

    return jsonify({"message": "Invalid email or password"}), 401

@app.route('/api/v1/users/<int:user_id>', methods=['DELETE'])
@jwt_required()
def delete_user(user_id):
    """
    Delete a user by ID.
    """
    user = User.query.get_or_404(user_id)
    try:
        db.session.delete(user)
        db.session.commit()
        return jsonify({"message": "User deleted successfully"}), 200
    except Exception as e:
        return jsonify({"message": "Error deleting user", "error": str(e)}), 500

# Error Handlers
@app.errorhandler(404)
def not_found(e):
    return jsonify({"message": "Resource not found"}), 404

@app.errorhandler(500)
def internal_server_error(e):
    return jsonify({"message": "Internal server error", "error": str(e)}), 500

# Main entry point
if __name__ == '__main__':
    app.run(debug=True)