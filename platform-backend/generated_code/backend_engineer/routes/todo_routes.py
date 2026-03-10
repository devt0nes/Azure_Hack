"""
Purpose: Define routes for CRUD operations on TODO items.
Dependencies:
- FastAPI: To define REST API endpoints.
- Pydantic: For request validation and response models.
- SQLAlchemy: For PostgreSQL database interaction.
Author: Backend Engineer
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from databases import Database
from sqlalchemy import Table, Column, Integer, String, MetaData

# Database connection and table definition
metadata = MetaData()

todos_table = Table(
    "todos",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("title", String(length=255), nullable=False),
    Column("description", String, nullable=True),
    Column("status", String(length=50), nullable=False),
)

database = Database("postgresql://user:password@localhost/todo_db")

# Define the APIRouter
router = APIRouter()


class TodoCreate(BaseModel):
    title: str
    description: str | None
    status: str


class TodoResponse(BaseModel):
    id: int
    title: str
    description: str | None
    status: str


@router.post("/", response_model=TodoResponse, status_code=201)
async def create_todo(todo: TodoCreate):
    """
    Create a new TODO item.
    Args:
        todo (TodoCreate): The TODO item to create.
    Returns:
        TodoResponse: The created TODO item.
    """
    query = todos_table.insert().values(
        title=todo.title, description=todo.description, status=todo.status
    )
    last_record_id = await database.execute(query)
    return TodoResponse(id=last_record_id, **todo.dict())


@router.get("/", response_model=list[TodoResponse])
async def get_todos():
    """
    Retrieve all TODO items.
    Returns:
        list[TodoResponse]: List of all TODO items.
    """
    query = todos_table.select()
    rows = await database.fetch_all(query)
    return [TodoResponse(**dict(row)) for row in rows]


@router.get("/{id}", response_model=TodoResponse)
async def get_todo_by_id(id: int):
    """
    Retrieve a TODO item by its ID.
    Args:
        id (int): The ID of the TODO item to retrieve.
    Returns:
        TodoResponse: The TODO item with the specified ID.
    """
    query = todos_table.select().where(todos_table.c.id == id)
    row = await database.fetch_one(query)
    if row is None:
        raise HTTPException(status_code=404, detail="TODO item not found")
    return TodoResponse(**dict(row))


@router.put("/{id}", status_code=200)
async def update_todo(id: int, todo: TodoCreate):
    """
    Update a TODO item by its ID.
    Args:
        id (int): The ID of the TODO item to update.
        todo (TodoCreate): The updated TODO attributes.
    Returns:
        dict: A success message.
    """
    query = todos_table.update().where(todos_table.c.id == id).values(
        title=todo.title, description=todo.description, status=todo.status
    )
    result = await database.execute(query)
    if result == 0:
        raise HTTPException(status_code=404, detail="TODO item not found")
    return {"message": "TODO item updated successfully"}


@router.delete("/{id}", status_code=200)
async def delete_todo_by_id(id: int):
    """
    Delete a TODO item by its ID.
    Args:
        id (int): The ID of the TODO item to delete.
    Returns:
        dict: A success message.
    """
    query = todos_table.delete().where(todos_table.c.id == id)
    result = await database.execute(query)
    if result == 0:
        raise HTTPException(status_code=404, detail="TODO item not found")
    return {"message": "TODO item deleted successfully"}