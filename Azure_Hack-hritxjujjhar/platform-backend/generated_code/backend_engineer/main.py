"""
Purpose: Entry point for the FastAPI TODO application
Dependencies: FastAPI for the web framework, SQLite for the database, Pydantic for data validation
Author: Backend Engineer
"""

from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List
import sqlite3

# Initialize FastAPI application
app = FastAPI()

# Database setup
DATABASE = "todo.db"

def get_db_connection():
    """
    Establishes a connection to the SQLite database.

    Returns:
        sqlite3.Connection: Database connection object
    """
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# Pydantic models for request and response validation
class TodoBase(BaseModel):
    title: str = Field(..., example="Buy groceries")
    description: str = Field(..., example="Milk, Bread, Butter")
    completed: bool = Field(False, example=False)

class TodoCreate(TodoBase):
    pass

class TodoUpdate(TodoBase):
    pass

class TodoResponse(TodoBase):
    id: int = Field(..., example=1)

# Routes for CRUD operations
@app.post("/todos", response_model=TodoResponse)
def create_todo(todo: TodoCreate):
    """
    Create a new TODO item.

    Args:
        todo (TodoCreate): TODO item data

    Returns:
        TodoResponse: Created TODO item
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO todos (title, description, completed) VALUES (?, ?, ?)",
        (todo.title, todo.description, todo.completed)
    )
    conn.commit()
    todo_id = cursor.lastrowid
    conn.close()
    return TodoResponse(id=todo_id, **todo.dict())

@app.get("/todos", response_model=List[TodoResponse])
def get_all_todos():
    """
    Fetch all TODO items.

    Returns:
        List[TodoResponse]: List of TODO items
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    todos = cursor.execute("SELECT * FROM todos").fetchall()
    conn.close()
    return [TodoResponse(**todo) for todo in todos]

@app.get("/todos/{id}", response_model=TodoResponse)
def get_todo(id: int):
    """
    Fetch a specific TODO item by ID.

    Args:
        id (int): TODO item ID

    Returns:
        TodoResponse: TODO item details

    Raises:
        HTTPException: If TODO item not found
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    todo = cursor.execute("SELECT * FROM todos WHERE id = ?", (id,)).fetchone()
    conn.close()
    if todo is None:
        raise HTTPException(status_code=404, detail="TODO item not found")
    return TodoResponse(**todo)

@app.put("/todos/{id}", response_model=TodoResponse)
def update_todo(id: int, todo: TodoUpdate):
    """
    Update an existing TODO item.

    Args:
        id (int): TODO item ID
        todo (TodoUpdate): Updated TODO item data

    Returns:
        TodoResponse: Updated TODO item

    Raises:
        HTTPException: If TODO item not found
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    result = cursor.execute(
        "UPDATE todos SET title = ?, description = ?, completed = ? WHERE id = ?",
        (todo.title, todo.description, todo.completed, id)
    )
    conn.commit()
    conn.close()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="TODO item not found")
    return TodoResponse(id=id, **todo.dict())

@app.delete("/todos/{id}")
def delete_todo(id: int):
    """
    Delete a TODO item.

    Args:
        id (int): TODO item ID

    Returns:
        dict: Message confirming deletion

    Raises:
        HTTPException: If TODO item not found
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    result = cursor.execute("DELETE FROM todos WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="TODO item not found")
    return {"message": f"TODO item with ID {id} has been deleted"}