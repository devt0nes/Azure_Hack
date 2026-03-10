-- Purpose: Schema definition for the TODO application database using SQLite.
-- Dependencies: SQLite (default library for relational database operations in Python).
-- Author: Database Architect Agent

-- This script creates the 'todos' table to store TODO items based on the project requirements.

CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, -- Unique identifier for each TODO item.
    title TEXT NOT NULL,                 -- Title of the TODO item.
    description TEXT,                    -- Description of the TODO item.
    completed BOOLEAN DEFAULT FALSE      -- Status of completion for the TODO item.
);