from fastapi import APIRouter

from app.service import ExportService, OrderService

router = APIRouter()
orders = OrderService()
exports = ExportService()


@router.get("/orders/search")
def search_orders(q: str):
    return orders.search(q)


@router.post("/orders/{order_id}/export")
def export_order(order_id: int, path: str):
    return exports.export(order_id, path)
