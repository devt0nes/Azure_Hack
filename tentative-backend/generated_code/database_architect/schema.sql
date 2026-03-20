/*
Purpose: Define the database schema for the bakery website to support product catalog, orders, customer reviews, newsletter subscriptions, and contact inquiries.
Dependencies: PostgreSQL 12+
Author: Database Architect
*/

/* Table: users
   Purpose: Store user information for customers and admins.
*/
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL, -- Storing securely hashed passwords
    role VARCHAR(50) NOT NULL DEFAULT 'customer', -- Role can be 'customer' or 'admin'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

/* Table: products
   Purpose: Store information about bakery products.
*/
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price DECIMAL(10, 2) NOT NULL,
    category VARCHAR(255) NOT NULL,
    stock INT DEFAULT 0 NOT NULL, -- Tracks inventory
    image_url TEXT, -- URL for product images
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

/* Table: orders
   Purpose: Store orders placed by customers.
*/
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    total DECIMAL(10, 2) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending', -- Status can be 'pending', 'completed', 'cancelled'
    shipping_address TEXT,
    payment_details JSONB -- Storing payment details securely
);

/* Table: order_items
   Purpose: Store items within an order.
*/
CREATE TABLE order_items (
    id SERIAL PRIMARY KEY,
    order_id INT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    quantity INT NOT NULL,
    price DECIMAL(10, 2) NOT NULL
);

/* Table: contact_inquiries
   Purpose: Store customer inquiries from the contact page.
*/
CREATE TABLE contact_inquiries (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

/* Table: reviews
   Purpose: Store customer reviews and testimonials.
*/
CREATE TABLE reviews (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    rating INT CHECK (rating BETWEEN 1 AND 5), -- Rating between 1 and 5
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

/* Table: newsletter_subscriptions
   Purpose: Store email addresses for newsletter subscribers.
*/
CREATE TABLE newsletter_subscriptions (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

/* Indexes for optimized querying */
CREATE INDEX idx_products_category ON products(category);
CREATE INDEX idx_orders_user_id ON orders(user_id);
CREATE INDEX idx_reviews_product_id ON reviews(product_id);
CREATE INDEX idx_contact_inquiries_email ON contact_inquiries(email);
CREATE INDEX idx_newsletter_subscriptions_email ON newsletter_subscriptions(email);