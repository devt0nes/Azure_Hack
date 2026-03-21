import firebase_admin
from firebase_admin import credentials, auth as firebase_auth
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
import os
import logging

load_dotenv()

logger = logging.getLogger(__name__)

# Initialize Firebase Admin — point to your downloaded service account JSON
firebase_initialized = False
try:
    firebase_service_account_path = os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH")
    if firebase_service_account_path and os.path.exists(firebase_service_account_path):
        cred = credentials.Certificate(firebase_service_account_path)
        firebase_admin.initialize_app(cred)
        firebase_initialized = True
        logger.info("Firebase initialized successfully")
    else:
        logger.warning(f"Firebase service account file not found at {firebase_service_account_path}. Running in development mode without Firebase auth.")
except Exception as e:
    logger.warning(f"Failed to initialize Firebase: {str(e)}. Running in development mode without Firebase auth.")

bearer_scheme = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)
):
    token = credentials.credentials
    
    # If Firebase is not initialized, allow development mode (return mock user)
    if not firebase_initialized:
        logger.info("Firebase not initialized. Using development mode with mock user.")
        return {
            "id": "dev-user-123",
            "email": "dev@example.com",
            "name": "Development User",
        }
    
    try:
        decoded = firebase_auth.verify_id_token(token)
        return {
            "id": decoded["uid"],           # stable Firebase user ID
            "email": decoded.get("email", ""),
            "name": decoded.get("name", ""),
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")