-- Purpose: Define the database schema for the e-commerce coffee website
-- Dependencies: PostgreSQL
-- Author: Database Architect Agent, Agentic Nexus

-- Table: users
-- Stores information about registered users
CREATE TABLE users (
    id SERIAL PRIMARY KEY, -- Unique identifier for each user
    username VARCHAR(255) NOT NULL UNIQUE, -- Unique username
    email VARCHAR(255) NOT NULL UNIQUE, -- Unique email address
    password_hash VARCHAR(255) NOT NULL, -- Hashed password for secure storage
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Timestamp of account creation
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- Timestamp of last account update
);

-- Table: products
-- Stores information about available coffee products
CREATE TABLE products (
    id SERIAL PRIMARY KEY, -- Unique identifier for each product
    name VARCHAR(255) NOT NULL, -- Name of the product
    description TEXT, -- Description of the product
    price DECIMAL(10, 2) NOT NULL, -- Price of the product
    image_url VARCHAR(255), -- URL for the product image
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Timestamp of product creation
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- Timestamp of last product update
);

-- Table: orders
-- Stores information about user orders
CREATE TABLE orders (
    id SERIAL PRIMARY KEY, -- Unique identifier for each order
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE, -- Reference to the user who placed the order
    status VARCHAR(50) NOT NULL, -- Status of the order (e.g., pending, completed, canceled)
    total_price DECIMAL(10, 2) NOT NULL, -- Total price of the order
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Timestamp of order creation
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- Timestamp of last order update
);

-- Table: order_items
-- Stores information about individual items in an order
CREATE TABLE order_items (
    id SERIAL PRIMARY KEY, -- Unique identifier for each order item
    order_id INT NOT NULL REFERENCES orders(id) ON DELETE CASCADE, -- Reference to the order
    product_id INT NOT NULL REFERENCES products(id), -- Reference to the product
    quantity INT NOT NULL, -- Quantity of the product ordered
    price DECIMAL(10, 2) NOT NULL -- Price of the product at the time of order
);

-- Table: cart_items
-- Temporary storage for items added to the shopping cart
CREATE TABLE cart_items (
    id SERIAL PRIMARY KEY, -- Unique identifier for each cart item
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE, -- Reference to the user
    product_id INT NOT NULL REFERENCES products(id), -- Reference to the product
    quantity INT NOT NULL -- Quantity of the product in the cart
);

-- Indices for performance optimization
CREATE INDEX idx_user_email ON users(email); -- Index for quick lookup of users by email
CREATE INDEX idx_product_name ON products(name); -- Index for quick lookup of products by name
CREATE INDEX idx_order_user ON orders(user_id); -- Index for quick lookup of orders by user

-- Constraints for data integrity
ALTER TABLE users
ADD CONSTRAINT chk_email_format CHECK (email LIKE '%@%'); -- Ensure valid email format

-- Security and compliance
-- Encrypt sensitive fields such as password_hash during application-level operations