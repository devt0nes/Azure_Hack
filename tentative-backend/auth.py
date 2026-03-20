import firebase_admin
from firebase_admin import credentials, auth as firebase_auth
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
import os

load_dotenv()

# Initialize Firebase Admin — point to your downloaded service account JSON
cred = credentials.Certificate(os.environ["FIREBASE_SERVICE_ACCOUNT_PATH"])
firebase_admin.initialize_app(cred)

bearer_scheme = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)
):
    token = credentials.credentials
    try:
        decoded = firebase_auth.verify_id_token(token)
        return {
            "id": decoded["uid"],           # stable Firebase user ID
            "email": decoded.get("email", ""),
            "name": decoded.get("name", ""),
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")