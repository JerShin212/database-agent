"""Script to create a sample SQLite database with sales data."""

import sqlite3
import random
from datetime import datetime, timedelta
from pathlib import Path

# Sample data
FIRST_NAMES = ["James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda", "William", "Elizabeth",
               "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
              "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin"]
CITIES = ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia", "San Antonio", "San Diego",
          "Dallas", "San Jose", "Austin", "Jacksonville", "Fort Worth", "Columbus", "Charlotte"]
COUNTRIES = ["USA", "Canada", "UK", "Germany", "France", "Australia", "Japan", "Brazil", "Mexico", "India"]
CATEGORIES = ["Electronics", "Clothing", "Home & Garden", "Sports", "Books", "Toys", "Food & Beverage", "Health"]
PRODUCT_NAMES = {
    "Electronics": ["Laptop", "Smartphone", "Tablet", "Headphones", "Smart Watch", "Camera", "Speaker", "Monitor"],
    "Clothing": ["T-Shirt", "Jeans", "Jacket", "Dress", "Sneakers", "Hat", "Scarf", "Gloves"],
    "Home & Garden": ["Chair", "Table", "Lamp", "Rug", "Planter", "Curtains", "Vase", "Mirror"],
    "Sports": ["Basketball", "Tennis Racket", "Yoga Mat", "Dumbbells", "Running Shoes", "Bike Helmet", "Golf Club"],
    "Books": ["Novel", "Cookbook", "Biography", "Science Fiction", "Mystery", "Self-Help", "History"],
    "Toys": ["Action Figure", "Board Game", "Puzzle", "Doll", "Building Blocks", "Remote Car", "Stuffed Animal"],
    "Food & Beverage": ["Coffee", "Tea", "Snacks", "Chocolate", "Energy Bar", "Juice", "Sauce"],
    "Health": ["Vitamins", "Supplements", "First Aid Kit", "Thermometer", "Blood Pressure Monitor", "Massager"],
}
REGIONS = ["North", "South", "East", "West", "Central"]
STATUSES = ["pending", "shipped", "delivered", "cancelled"]


def create_sample_database(db_path: str) -> None:
    """Create a sample SQLite database with sales data."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create tables
    cursor.executescript("""
        DROP TABLE IF EXISTS order_items;
        DROP TABLE IF EXISTS orders;
        DROP TABLE IF EXISTS customer_sales_rep;
        DROP TABLE IF EXISTS sales_reps;
        DROP TABLE IF EXISTS products;
        DROP TABLE IF EXISTS customers;

        CREATE TABLE customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE,
            phone TEXT,
            city TEXT,
            country TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT,
            price DECIMAL(10, 2) NOT NULL,
            stock_quantity INTEGER DEFAULT 0,
            description TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE sales_reps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE,
            region TEXT,
            hire_date DATE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER REFERENCES customers(id),
            sales_rep_id INTEGER REFERENCES sales_reps(id),
            order_date DATE NOT NULL,
            total_amount DECIMAL(10, 2),
            status TEXT DEFAULT 'pending',
            shipping_address TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER REFERENCES orders(id),
            product_id INTEGER REFERENCES products(id),
            quantity INTEGER NOT NULL,
            unit_price DECIMAL(10, 2) NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE customer_sales_rep (
            customer_id INTEGER REFERENCES customers(id),
            sales_rep_id INTEGER REFERENCES sales_reps(id),
            assigned_date DATE,
            PRIMARY KEY (customer_id, sales_rep_id)
        );
    """)

    # Insert customers (100)
    customers = []
    for i in range(100):
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        name = f"{first} {last}"
        email = f"{first.lower()}.{last.lower()}{i}@example.com"
        phone = f"+1-{random.randint(200, 999)}-{random.randint(100, 999)}-{random.randint(1000, 9999)}"
        city = random.choice(CITIES)
        country = random.choice(COUNTRIES)
        customers.append((name, email, phone, city, country))

    cursor.executemany(
        "INSERT INTO customers (name, email, phone, city, country) VALUES (?, ?, ?, ?, ?)",
        customers
    )

    # Insert products (50)
    products = []
    for category, names in PRODUCT_NAMES.items():
        for name in names:
            price = round(random.uniform(10, 500), 2)
            stock = random.randint(0, 200)
            desc = f"High-quality {name.lower()} in the {category.lower()} category."
            products.append((name, category, price, stock, desc))

    cursor.executemany(
        "INSERT INTO products (name, category, price, stock_quantity, description) VALUES (?, ?, ?, ?, ?)",
        products
    )

    # Insert sales reps (10)
    sales_reps = []
    for i in range(10):
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        name = f"{first} {last}"
        email = f"{first.lower()}.{last.lower()}.sales{i}@company.com"
        region = random.choice(REGIONS)
        hire_date = (datetime.now() - timedelta(days=random.randint(30, 1800))).strftime("%Y-%m-%d")
        sales_reps.append((name, email, region, hire_date))

    cursor.executemany(
        "INSERT INTO sales_reps (name, email, region, hire_date) VALUES (?, ?, ?, ?)",
        sales_reps
    )

    # Get product count for order items
    cursor.execute("SELECT COUNT(*) FROM products")
    product_count = cursor.fetchone()[0]

    # Insert orders (500) over the past year
    for _ in range(500):
        customer_id = random.randint(1, 100)
        sales_rep_id = random.randint(1, 10)
        order_date = (datetime.now() - timedelta(days=random.randint(1, 365))).strftime("%Y-%m-%d")
        status = random.choice(STATUSES)
        city = random.choice(CITIES)
        address = f"{random.randint(100, 9999)} Main St, {city}"

        cursor.execute(
            """INSERT INTO orders (customer_id, sales_rep_id, order_date, status, shipping_address, total_amount)
               VALUES (?, ?, ?, ?, ?, 0)""",
            (customer_id, sales_rep_id, order_date, status, address)
        )
        order_id = cursor.lastrowid

        # 1-5 items per order
        total = 0
        for _ in range(random.randint(1, 5)):
            product_id = random.randint(1, product_count)
            quantity = random.randint(1, 10)
            cursor.execute("SELECT price FROM products WHERE id = ?", (product_id,))
            result = cursor.fetchone()
            if result:
                unit_price = result[0]
                total += quantity * unit_price

                cursor.execute(
                    "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
                    (order_id, product_id, quantity, unit_price)
                )

        cursor.execute("UPDATE orders SET total_amount = ? WHERE id = ?", (round(total, 2), order_id))

    # Assign customers to sales reps
    for customer_id in range(1, 101):
        sales_rep_id = random.randint(1, 10)
        assigned_date = (datetime.now() - timedelta(days=random.randint(30, 365))).strftime("%Y-%m-%d")
        cursor.execute(
            "INSERT INTO customer_sales_rep (customer_id, sales_rep_id, assigned_date) VALUES (?, ?, ?)",
            (customer_id, sales_rep_id, assigned_date)
        )

    conn.commit()
    conn.close()
    print(f"Created sample database at {db_path}")
    print("Tables: customers (100), products (50+), sales_reps (10), orders (500), order_items")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = "sales_data.db"
    create_sample_database(db_path)
