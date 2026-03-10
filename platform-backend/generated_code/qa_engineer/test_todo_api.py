"""
Purpose: Unit and integration tests for the FastAPI TODO backend.
Dependencies: pytest, httpx, FastAPI TestClient
Author: QA Engineer
"""

import pytest
from fastapi.testclient import TestClient
from main import app  # Assuming the FastAPI app is defined in main.py

# Using TestClient to simulate API requests
client = TestClient(app)


@pytest.fixture
def valid_todo_data():
    """Fixture to provide a valid TODO item."""
    return {
        "title": "Test TODO",
        "description": "This is a test TODO item.",
        "status": "pending",
        "due_date": "2026-12-31T23:59:59"
    }


@pytest.fixture
def invalid_todo_data():
    """Fixture to provide invalid TODO data."""
    return {
        "title": "",  # Title is empty, which is invalid
        "description": "This is an invalid TODO item.",
        "status": "unknown",  # Invalid status
        "due_date": "not-a-date"  # Invalid date format
    }


def test_create_todo_success(valid_todo_data):
    """Test creating a TODO item successfully."""
    response = client.post("/todos", json=valid_todo_data)
    assert response.status_code == 201
    response_data = response.json()
    assert response_data["title"] == valid_todo_data["title"]
    assert response_data["description"] == valid_todo_data["description"]
    assert response_data["status"] == valid_todo_data["status"]
    assert response_data["due_date"] == valid_todo_data["due_date"]


def test_create_todo_failure(invalid_todo_data):
    """Test failure when creating a TODO item with invalid data."""
    response = client.post("/todos", json=invalid_todo_data)
    assert response.status_code == 400
    response_data = response.json()
    assert "detail" in response_data  # Check for validation error message


def test_get_todos_pagination():
    """Test retrieving TODO items with pagination."""
    response = client.get("/todos?page=1&size=5")
    assert response.status_code == 200
    response_data = response.json()
    assert "items" in response_data
    assert "total" in response_data
    assert len(response_data["items"]) <= 5  # Ensure page size is respected


def test_get_todo_by_id_success(valid_todo_data):
    """Test retrieving a specific TODO item by ID successfully."""
    # First, create a TODO item
    create_response = client.post("/todos", json=valid_todo_data)
    created_todo = create_response.json()
    todo_id = created_todo["id"]
    
    # Then, retrieve the created TODO by ID
    response = client.get(f"/todos/{todo_id}")
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["id"] == todo_id
    assert response_data["title"] == valid_todo_data["title"]


def test_get_todo_by_id_not_found():
    """Test retrieving a TODO item by a non-existent ID."""
    response = client.get("/todos/non-existent-id")
    assert response.status_code == 404
    response_data = response.json()
    assert "detail" in response_data  # Check for not found error message


def test_update_todo_success(valid_todo_data):
    """Test updating a TODO item successfully."""
    # First, create a TODO item
    create_response = client.post("/todos", json=valid_todo_data)
    created_todo = create_response.json()
    todo_id = created_todo["id"]
    
    # Update the TODO item
    updated_data = valid_todo_data.copy()
    updated_data["title"] = "Updated TODO Title"
    response = client.put(f"/todos/{todo_id}", json=updated_data)
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["title"] == "Updated TODO Title"


def test_update_todo_not_found(valid_todo_data):
    """Test updating a TODO item that does not exist."""
    response = client.put("/todos/non-existent-id", json=valid_todo_data)
    assert response.status_code == 404
    response_data = response.json()
    assert "detail" in response_data  # Check for not found error message


def test_delete_todo_success(valid_todo_data):
    """Test deleting a TODO item successfully."""
    # First, create a TODO item
    create_response = client.post("/todos", json=valid_todo_data)
    created_todo = create_response.json()
    todo_id = created_todo["id"]
    
    # Delete the TODO item
    response = client.delete(f"/todos/{todo_id}")
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["message"] == "TODO deleted successfully."


def test_delete_todo_not_found():
    """Test deleting a TODO item that does not exist."""
    response = client.delete("/todos/non-existent-id")
    assert response.status_code == 404
    response_data = response.json()
    assert "detail" in response_data  # Check for not found error message