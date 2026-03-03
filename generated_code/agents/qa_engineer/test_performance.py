import time
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_performance_load():
    """Test high-load performance of the login endpoint"""
    start_time = time.time()
    for _ in range(1000):  # Simulating 1000 login requests
        response = client.post(
            "/login",
            data={"username": "testuser@example.com", "password": "testpassword"}
        )
        assert response.status_code == 200
    end_time = time.time()

    elapsed_time = end_time - start_time
    print(f"Processed 1000 requests in {elapsed_time:.2f} seconds")