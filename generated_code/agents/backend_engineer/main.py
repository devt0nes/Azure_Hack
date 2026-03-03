from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import SessionLocal, engine, Base
from app.routers import auth, users

# Initialize the database
Base.metadata.create_all(bind=engine)

# Create FastAPI app
app = FastAPI(
    title="Agentic Nexus API",
    description="Backend API for the Agentic Nexus platform",
    version="1.0.0",
)

# Dependency to get database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Include routers
app.include_router(auth.router)
app.include_router(users.router)

# Health check endpoint
@app.get("/health", tags=["System"])
def health_check():
    return {"status": "healthy"}