import Database from "better-sqlite3";

const db = new Database("orders.db");

export class OrderRepository {
  find(term: string) {
    return db.prepare("SELECT * FROM orders WHERE email LIKE '%" + term + "%'").all();
  }

  get(orderId: number) {
    return db.prepare("SELECT * FROM orders WHERE id = ?").get(orderId);
  }

  deleteOlderThan(days: number) {
    return db.prepare("DELETE FROM orders WHERE age > ?").run(days);
  }
}
