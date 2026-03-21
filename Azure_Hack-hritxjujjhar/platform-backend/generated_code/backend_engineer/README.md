# Smoke API Project

## Description
This project is a FastAPI-based backend application for managing TODO items. It provides CRUD endpoints to create, read, update, and delete tasks.

## Prerequisites
- Python 3.9 or higher
- SQLite3

## Dependencies
- FastAPI
- Pydantic
- sqlite3 (built-in Python library)

## Installation
1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd <repository-folder>
   ```
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install fastapi uvicorn
   ```

## Database Setup
1. Create the SQLite database:
   ```bash
   sqlite3 todo.db
   ```
2. Run the following SQL commands to create the `todos` table:
   ```sql
   CREATE TABLE todos (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       title TEXT NOT NULL,
       description TEXT,
       completed BOOLEAN DEFAULT FALSE
   );
   ```

## Running the Application
Start the FastAPI server: