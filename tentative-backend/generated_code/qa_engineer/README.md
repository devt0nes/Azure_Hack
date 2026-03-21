# Cancer Awareness Website Testing Suite

## Overview
This repository contains the testing suite for the Cancer Awareness website. The tests cover unit tests for the frontend, integration tests for API endpoints, and responsiveness checks.

## Prerequisites
- Python 3.8 or higher
- Google Chrome and ChromeDriver
- Required Python packages (see below)

## Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/cancer-awareness-tests.git
   ```
2. Install required Python packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Ensure ChromeDriver is installed and added to your PATH.

## Running Tests
1. Run frontend tests:
   ```bash
   pytest test_homepage.py
   ```
2. Run API tests:
   ```bash
   pytest test_api.py
   ```

## Configuration
- Update the `BASE_URL` variable in `test_api.py` with the actual URL of the deployed API.
- Ensure the local server is running before executing tests.

## Dependencies
- pytest: Unit testing framework for Python.
- selenium: Browser automation for frontend testing.
- requests: HTTP client for API testing.