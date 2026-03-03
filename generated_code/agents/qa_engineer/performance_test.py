import requests
import time
from concurrent.futures import ThreadPoolExecutor

API_URL = "http://localhost:5000"

def send_request(endpoint, payload=None):
    """Send a POST request to the API."""
    if payload:
        response = requests.post(f"{API_URL}/{endpoint}", json=payload)
    else:
        response = requests.get(f"{API_URL}/{endpoint}")
    return response.status_code

def load_test(endpoint, payload=None, num_requests=100):
    """Perform load testing on the API."""
    with ThreadPoolExecutor(max_workers=10) as executor:
        start_time = time.time()
        futures = [executor.submit(send_request, endpoint, payload) for _ in range(num_requests)]
        for future in futures:
            future.result()
        end_time = time.time()

    duration = end_time - start_time
    print(f"{num_requests} requests to {endpoint} completed in {duration:.2f} seconds.")

if __name__ == "__main__":
    # Load test the register endpoint
    print("Testing /register endpoint:")
    load_test("register", payload={"username": "testuser", "password": "securepassword123"})

    # Load test the login endpoint
    print("Testing /login endpoint:")
    load_test("login", payload={"username": "testuser", "password": "securepassword123"})