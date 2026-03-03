import logging
import time
import requests

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Monitoring configuration
SERVICE_URL = "http://localhost:8000"
HEALTH_ENDPOINT = f"{SERVICE_URL}/health"
GENERATE_ENDPOINT = f"{SERVICE_URL}/generate"

# Example prompts for testing
TEST_PROMPTS = [
    {"prompt": "What is the capital of France?", "max_tokens": 50, "temperature": 0.7},
    {"prompt": "Explain the concept of reinforcement learning.", "max_tokens": 100, "temperature": 0.7},
]

def monitor_service():
    """
    Monitor the ML service health and performance.
    """
    logging.info("Starting monitoring...")
    while True:
        try:
            # Health check
            health_response = requests.get(HEALTH_ENDPOINT)
            if health_response.status_code == 200:
                logging.info("Service health: OK")
            else:
                logging.error(f"Service health failed: {health_response.status_code}")

            # Test inference with predefined prompts
            for test_prompt in TEST_PROMPTS:
                response = requests.post(GENERATE_ENDPOINT, json=test_prompt)
                if response.status_code == 200:
                    logging.info(f"Test prompt success: {test_prompt['prompt']}")
                else:
                    logging.error(f"Test prompt failed: {response.status_code}")

        except Exception as e:
            logging.error(f"Error during monitoring: {e}")

        # Wait before the next check
        time.sleep(60)

if __name__ == "__main__":
    monitor_service()