-- Sample e-commerce schema.
-- Deliberately contains overlapping naming so ambiguity is realistic:
--   - "amount" exists in both orders and payments (different meanings)
--   - "date" exists in orders, payments, and reviews
--   - "name" exists in customers and products
--   - "status" exists in orders and payments
-- This gives the clarification engine real work to do.

CREATE TABLE customers (
    customer_id   INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL,
    city          TEXT,
    signup_date   TEXT
);

CREATE TABLE products (
    product_id    INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    category      TEXT,
    price         REAL NOT NULL
);

CREATE TABLE orders (
    order_id      INTEGER PRIMARY KEY,
    customer_id   INTEGER NOT NULL,
    order_date    TEXT NOT NULL,   -- "date" ambiguity source
    amount        REAL NOT NULL,   -- "amount" ambiguity source (order total)
    status        TEXT NOT NULL,   -- "status" ambiguity source (pending/shipped/cancelled)
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL,
    product_id    INTEGER NOT NULL,
    quantity      INTEGER NOT NULL,
    unit_price    REAL NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(order_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE payments (
    payment_id    INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL,
    payment_date  TEXT NOT NULL,   -- "date" ambiguity source
    amount        REAL NOT NULL,   -- "amount" ambiguity source (amount actually paid)
    status        TEXT NOT NULL,   -- "status" ambiguity source (success/failed/refunded)
    method        TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);

CREATE TABLE reviews (
    review_id     INTEGER PRIMARY KEY,
    product_id    INTEGER NOT NULL,
    customer_id   INTEGER NOT NULL,
    rating        INTEGER NOT NULL,
    review_date   TEXT NOT NULL,   -- "date" ambiguity source
    FOREIGN KEY (product_id) REFERENCES products(product_id),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);
