"""
Creates and seeds the sample SQLite database used throughout the project.

Run once:
    python setup_db.py
"""

import os
import random
import sqlite3
from datetime import datetime, timedelta

import config

random.seed(42)

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "db", "schema.sql")


def rand_date(start_days_ago=365, end_days_ago=0):
    d = random.randint(end_days_ago, start_days_ago)
    return (datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d")


def build_database():
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    if os.path.exists(config.DB_PATH):
        os.remove(config.DB_PATH)

    conn = sqlite3.connect(config.DB_PATH)
    cur = conn.cursor()

    with open(SCHEMA_PATH, "r") as f:
        cur.executescript(f.read())

    # --- customers ---
    cities = ["Delhi", "Mumbai", "Bangalore", "Pune", "Chennai", "Hyderabad"]
    first_names = ["Aarav", "Vivaan", "Ishaan", "Diya", "Ananya", "Kabir",
                   "Meera", "Rohan", "Sara", "Aditya", "Priya", "Nikhil"]
    last_names = ["Sharma", "Verma", "Gupta", "Iyer", "Reddy", "Nair",
                  "Khan", "Patel", "Singh", "Mehta"]

    customers = []
    for i in range(1, 31):
        name = f"{random.choice(first_names)} {random.choice(last_names)}"
        email = name.lower().replace(" ", ".") + f"{i}@example.com"
        customers.append((i, name, email, random.choice(cities), rand_date(700, 200)))
    cur.executemany(
        "INSERT INTO customers (customer_id, name, email, city, signup_date) VALUES (?, ?, ?, ?, ?)",
        customers,
    )

    # --- products ---
    products = [
        (1, "Wireless Mouse", "Electronics", 799.0),
        (2, "Mechanical Keyboard", "Electronics", 3499.0),
        (3, "USB-C Hub", "Electronics", 1299.0),
        (4, "Yoga Mat", "Fitness", 999.0),
        (5, "Dumbbell Set", "Fitness", 2499.0),
        (6, "Running Shoes", "Fitness", 3999.0),
        (7, "Notebook Set", "Stationery", 249.0),
        (8, "Fountain Pen", "Stationery", 599.0),
        (9, "Office Chair", "Furniture", 7999.0),
        (10, "Study Desk", "Furniture", 5999.0),
        (11, "Bluetooth Speaker", "Electronics", 1999.0),
        (12, "Water Bottle", "Fitness", 349.0),
    ]
    cur.executemany(
        "INSERT INTO products (product_id, name, category, price) VALUES (?, ?, ?, ?)",
        products,
    )

    # --- orders + order_items + payments ---
    order_id = 1
    payment_id = 1
    order_item_id = 1
    orders = []
    order_items = []
    payments = []
    statuses = ["pending", "shipped", "cancelled", "delivered"]
    pay_statuses = ["success", "failed", "refunded"]
    methods = ["card", "upi", "netbanking", "cod"]

    for cust in customers:
        n_orders = random.randint(1, 5)
        for _ in range(n_orders):
            odate = rand_date(300, 1)
            items_for_order = random.sample(products, k=random.randint(1, 3))
            order_total = 0.0
            temp_items = []
            for p in items_for_order:
                qty = random.randint(1, 3)
                unit_price = p[3]
                order_total += qty * unit_price
                temp_items.append((order_item_id, order_id, p[0], qty, unit_price))
                order_item_id += 1

            status = random.choice(statuses)
            orders.append((order_id, cust[0], odate, round(order_total, 2), status))
            order_items.extend(temp_items)

            # payment record (amount can legitimately differ from order amount,
            # e.g. partial refunds -- this is intentional realism)
            pay_amount = order_total if status != "cancelled" else round(order_total * random.choice([0, 0.5]), 2)
            pay_status = "refunded" if status == "cancelled" else random.choice(pay_statuses)
            payments.append((
                payment_id, order_id, odate, round(pay_amount, 2), pay_status,
                random.choice(methods)
            ))
            payment_id += 1
            order_id += 1

    cur.executemany(
        "INSERT INTO orders (order_id, customer_id, order_date, amount, status) VALUES (?, ?, ?, ?, ?)",
        orders,
    )
    cur.executemany(
        "INSERT INTO order_items (order_item_id, order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?, ?)",
        order_items,
    )
    cur.executemany(
        "INSERT INTO payments (payment_id, order_id, payment_date, amount, status, method) VALUES (?, ?, ?, ?, ?, ?)",
        payments,
    )

    # --- reviews ---
    reviews = []
    review_id = 1
    for cust in customers:
        for p in random.sample(products, k=random.randint(0, 4)):
            reviews.append((review_id, p[0], cust[0], random.randint(1, 5), rand_date(300, 1)))
            review_id += 1
    cur.executemany(
        "INSERT INTO reviews (review_id, product_id, customer_id, rating, review_date) VALUES (?, ?, ?, ?, ?)",
        reviews,
    )

    conn.commit()
    conn.close()
    print(f"Database created at {config.DB_PATH}")
    print(f"  customers: {len(customers)}, orders: {len(orders)}, "
          f"order_items: {len(order_items)}, payments: {len(payments)}, reviews: {len(reviews)}")


if __name__ == "__main__":
    build_database()
