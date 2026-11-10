import sqlite3


class OrderRepository:
    def __init__(self):
        self.db = sqlite3.connect("orders.db")

    def find(self, term):
        return self.db.execute(f"SELECT * FROM orders WHERE email LIKE '%{term}%'").fetchall()

    def get(self, order_id):
        return self.db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()

    def delete_older_than(self, days):
        self.db.execute("DELETE FROM orders WHERE age > ?", (days,))
