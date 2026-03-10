"""
Purpose: Unit tests for the FastAPI TODO backend application.
Dependencies: Pytest, FastAPI, TestClient from FastAPI
Author: QA Engineer
"""

import pytest
from fastapi.testclient import TestClient
from main import app  # Importing the FastAPI application

# Initialize the TestClient for FastAPI application
client = TestClient(app)

@pytest.fixture
def sample_todo_data():
    """
    Fixture to provide sample TODO data for testing.
    Returns:
        dict: Sample TODO item data.
    """
    return {
        "title": "Test TODO",
        "description": "This is a test TODO item.",
        "status": "pending"
    }

def test_create_todo(sample_todo_data):
    """
    Test case for creating a new TODO item.
    Args:
        sample_todo_data (dict): Sample TODO item data.
    """
    response = client.post("/todos", json=sample_todo_data)
    assert response.status_code == 201
    assert "id" in response.json()
    assert response.json()["message"] == "TODO item created successfully"

def test_retrieve_all_todos():
    """
    Test case for retrieving all TODO items.
    """
    response = client.get("/todos")
    assert response.status_code == 200
    assert isinstance(response.json()["todos"], list)

def test_retrieve_todo_by_id(sample_todo_data):
    """
    Test case for retrieving a TODO item by ID.
    Args:
        sample_todo_data (dict): Sample TODO item data.
    """
    # Create a TODO first
    create_response = client.post("/todos", json=sample_todo_data)
    todo_id = create_response.json()["id"]

    # Retrieve the TODO by ID
    response = client.get(f"/todos/{todo_id}")
    assert response.status_code == 200
    assert response.json()["id"] == todo_id
    assert response.json()["title"] == sample_todo_data["title"]

def test_update_todo(sample_todo_data):
    """
    Test case for updating a TODO item.
    Args:
        sample_todo_data (dict): Sample TODO item data.
    """
    # Create a TODO first
    create_response = client.post("/todos", json=sample_todo_data)
    todo_id = create_response.json()["id"]

    # Update the TODO
    updated_data = {
        "title": "Updated TODO",
        "description": "This has been updated.",
        "status": "completed"
    }
    response = client.put(f"/todos/{todo_id}", json=updated_data)
    assert response.status_code == 200
    assert response.json()["message"] == "TODO item updated successfully"

def test_delete_todo(sample_todo_data):
    """
    Test case for deleting a TODO item.
    Args:
        sample_todo_data (dict): Sample TODO item data.
    """
    # Create a TODO first
    create_response = client.post("/todos", json=sample_todo_data)
    todo_id = create_response.json()["id"]

    # Delete the TODO
    response = client.delete(f"/todos/{todo_id}")
    assert response.status_code == 200
    assert response.json()["message"] == "TODO item deleted successfully"

def test_retrieve_nonexistent_todo():
    """
    Test case for retrieving a TODO item that does not exist.
    """
    response = client.get("/todos/9999")  # Assuming 9999 does not exist
    assert response.status_code == 404
    assert response.json()["detail"] == "TODO item not found"

def test_update_nonexistent_todo():
    """
    Test case for updating a TODO item that does not exist.
    """
    updated_data = {
        "title": "Nonexistent TODO",
        "description": "This does not exist.",
        "status": "completed"
    }
    response = client.put("/todos/9999", json=updated_data)  # Assuming 9999 does not exist
    assert response.status_code == 404
    assert response.json()["detail"] == "TODO item not found"

def test_delete_nonexistent_todo():
    """
    Test case for deleting a TODO item that does not exist.
    """
    response = client.delete("/todos/9999")  # Assuming 9999 does not exist
    assert response.status_code == 404
    assert response.json()["detail"] == "TODO item not found"