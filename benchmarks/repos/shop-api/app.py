"""Shop API - orders and refunds."""
import sqlite3
from flask import Flask, request, jsonify, g
import jwt
from config import JWT_SECRET, DB_PATH

app = Flask(__name__)


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def current_user():
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


@app.get("/orders/search")
def search_orders():
    user = current_user()
    if not user:
        return jsonify(error="unauthorised"), 401
    term = request.args.get("q", "")
    rows = db().execute(
        f"SELECT id, email, card_token, total FROM orders WHERE email LIKE '%{term}%'"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/admin/refund")
def refund():
    if not current_user():
        return jsonify(error="unauthorised"), 401
    body = request.get_json()
    db().execute(
        "UPDATE orders SET refunded = ? WHERE id = ?", (body["amount"], body["order_id"])
    )
    db().commit()
    return jsonify(ok=True)


@app.errorhandler(Exception)
def on_error(exc):
    import traceback
    return jsonify(error=str(exc), trace=traceback.format_exc()), 500
