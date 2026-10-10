-- ---------------------------------------------------------------------------
-- SAMPLE DATA — development/verification only.
-- A small e-commerce analytics schema used to prove QueryMind generates SQL
-- dynamically against whatever schema the user connects.
-- ---------------------------------------------------------------------------

CREATE TABLE regions (
    region_id   BIGSERIAL PRIMARY KEY,
    region_name TEXT NOT NULL UNIQUE,
    country     TEXT NOT NULL
);

CREATE TABLE customers (
    customer_id BIGSERIAL PRIMARY KEY,
    full_name   TEXT NOT NULL,
    email       TEXT NOT NULL,
    region_id   BIGINT REFERENCES regions(region_id),
    signup_date DATE NOT NULL
);
CREATE INDEX idx_customers_region ON customers(region_id);
CREATE INDEX idx_customers_email ON customers(email);

CREATE TABLE products (
    product_id   BIGSERIAL PRIMARY KEY,
    product_name TEXT NOT NULL,
    category     TEXT NOT NULL,
    unit_price   NUMERIC(10,2) NOT NULL
);

CREATE TABLE orders (
    order_id    BIGSERIAL PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    order_date  DATE NOT NULL,
    status      TEXT NOT NULL
);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_date ON orders(order_date);

CREATE TABLE order_items (
    order_item_id BIGSERIAL PRIMARY KEY,
    order_id      BIGINT NOT NULL REFERENCES orders(order_id),
    product_id    BIGINT NOT NULL REFERENCES products(product_id),
    quantity      INT NOT NULL,
    unit_price    NUMERIC(10,2) NOT NULL
);
CREATE INDEX idx_order_items_order ON order_items(order_id);
CREATE INDEX idx_order_items_product ON order_items(product_id);

-- Regions -------------------------------------------------------------------
INSERT INTO regions (region_name, country) VALUES
  ('North America', 'USA'),
  ('Europe', 'Germany'),
  ('Asia Pacific', 'Japan'),
  ('Latin America', 'Brazil');

-- Customers -----------------------------------------------------------------
INSERT INTO customers (full_name, email, region_id, signup_date) VALUES
  ('Alice Johnson',   'alice@example.com',   1, '2024-01-15'),
  ('Bob Smith',       'bob@example.com',     1, '2024-02-20'),
  ('Carla Mendes',    'carla@example.com',   4, '2024-03-05'),
  ('Diego Fischer',   'diego@example.com',   2, '2024-04-11'),
  ('Emma Watson',     'emma@example.com',    2, '2024-05-02'),
  ('Farid Khan',      'farid@example.com',   3, '2024-05-19'),
  ('Grace Lee',       'grace@example.com',   3, '2024-06-08'),
  ('Hiro Tanaka',     'hiro@example.com',    3, '2024-07-23'),
  ('Isla Murphey',    'isla@example.com',    1, '2024-08-14'),
  ('Jack Miller',     'jack@example.com',    1, '2024-09-01'),
  ('Kira Novak',      'kira@example.com',    2, '2024-10-17'),
  ('Lucas Silva',     'lucas@example.com',   4, '2024-11-03'),
  ('Maya Patel',      'maya@example.com',    1, '2025-01-09'),
  ('Noah Kim',        'noah@example.com',    3, '2025-02-14'),
  ('Olga Petrova',    'olga@example.com',    2, '2025-03-27'),
  ('Duplicate Email', 'alice@example.com',   1, '2025-04-02');

-- Products ------------------------------------------------------------------
INSERT INTO products (product_name, category, unit_price) VALUES
  ('Aurora Laptop 14',   'Electronics', 1299.00),
  ('Nimbus Headphones',  'Electronics', 199.50),
  ('Trail Runner Shoes', 'Footwear',     89.90),
  ('Canvas Backpack',    'Accessories',  59.00),
  ('Steel Water Bottle', 'Accessories',  24.50),
  ('Ergo Keyboard',      'Electronics',  149.00),
  ('Merino Hoodie',      'Apparel',      79.00),
  ('Desk Lamp Pro',      'Home Office',  45.00);

-- Orders (spread across 2024-2025 for date-grouping questions) ---------------
INSERT INTO orders (customer_id, order_date, status) VALUES
  (1,  '2024-02-01', 'completed'),
  (1,  '2024-06-15', 'completed'),
  (1,  '2025-01-20', 'completed'),
  (2,  '2024-03-10', 'completed'),
  (2,  '2024-03-25', 'cancelled'),
  (3,  '2024-04-05', 'completed'),
  (4,  '2024-05-12', 'completed'),
  (4,  '2024-11-28', 'completed'),
  (5,  '2024-07-19', 'completed'),
  (6,  '2024-08-02', 'completed'),
  (6,  '2025-02-11', 'completed'),
  (7,  '2024-09-14', 'completed'),
  (8,  '2024-10-06', 'completed'),
  (9,  '2024-12-01', 'completed'),
  (9,  '2025-03-08', 'completed'),
  (10, '2025-01-05', 'completed'),
  (11, '2025-02-22', 'completed'),
  (12, '2025-03-15', 'completed'),
  (13, '2025-04-09', 'completed'),
  (14, '2025-05-21', 'completed'),
  (15, '2025-06-02', 'completed'),
  (1,  '2025-06-18', 'completed'),
  (5,  '2025-07-04', 'completed'),
  (10, '2025-07-15', 'pending');

-- Order items ---------------------------------------------------------------
INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
  (1, 1, 1, 1299.00), (1, 3, 2,  89.90),
  (2, 2, 1,  199.50),
  (3, 6, 1,  149.00), (3, 8, 2,  45.00),
  (4, 4, 3,  59.00),
  (5, 5, 1,  24.50),
  (6, 1, 1, 1299.00),
  (7, 7, 2,  79.00), (7, 5, 4,  24.50),
  (8, 2, 2,  199.50),
  (9, 3, 1,  89.90),
  (10, 6, 2, 149.00),
  (11, 1, 1, 1299.00), (11, 4, 1, 59.00),
  (12, 8, 5,  45.00),
  (13, 7, 1,  79.00),
  (14, 2, 1,  199.50), (14, 3, 2, 89.90),
  (15, 4, 2,  59.00),
  (16, 1, 1, 1299.00),
  (17, 5, 6,  24.50),
  (18, 6, 1,  149.00), (18, 8, 1, 45.00),
  (19, 2, 3,  199.50),
  (20, 7, 2,  79.00),
  (21, 3, 1,  89.90), (21, 4, 1, 59.00),
  (22, 1, 1, 1299.00), (22, 6, 1, 149.00),
  (23, 8, 2,  45.00),
  (24, 2, 1,  199.50);

-- A view used to prove view discovery works ------------------------------------------------
CREATE VIEW monthly_sales AS
SELECT date_trunc('month', o.order_date) AS month,
       SUM(oi.quantity * oi.unit_price)  AS revenue,
       COUNT(DISTINCT o.order_id)        AS order_count
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
WHERE o.status = 'completed'
GROUP BY 1;
