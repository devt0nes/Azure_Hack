# Backend for Agentic Nexus User Management

This is the backend implementation for the user management API of the Agentic Nexus platform. It provides RESTful endpoints for creating, retrieving, authenticating, and deleting users.

## Features
- User creation with hashed passwords
- User authentication using JWT
- Secure endpoints with JWT-based authorization
- Basic error handling and proper status codes
- Scalable and configurable via environment variables

## Setup Instructions
1. Clone the repository.
2. Install required dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Set up a `.env` file with the following variables:
   ```
   DATABASE_URL=<Your Database URL>
   JWT_SECRET_KEY=<Your JWT Secret Key>
   ```
4. Initialize the database:
   ```
   from app import db
   db.create_all()
   ```
5. Run the application:
   ```
   python app.py
   ```

## API Endpoints
- `POST /api/v1/users`: Create a new user.
- `GET /api/v1/users/<id>`: Retrieve a specific user (JWT token required).
- `POST /api/v1/users/login`: Authenticate a user and receive a JWT token.
- `DELETE /api/v1/users/<id>`: Delete a user (JWT token required).

## Next Steps
- Integrate with Azure App Service for deployment.
- Conduct a security audit with the security engineer.
- Enhance the API with additional features such as pagination and search.

## Dependencies
- Flask
- SQLAlchemy
- Flask-Bcrypt
- Flask-JWT-Extended
- python-dotenv