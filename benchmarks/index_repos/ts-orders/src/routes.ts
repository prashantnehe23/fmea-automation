import express from "express";
import { ExportService, OrderService } from "./service";

const app = express();
const orders = new OrderService();
const exports = new ExportService();

function searchOrders(req: express.Request, res: express.Response) {
  res.json(orders.search(String(req.query.q)));
}

function exportOrder(req: express.Request, res: express.Response) {
  res.send(exports.exportOrder(Number(req.params.orderId), String(req.query.path)));
}

app.get("/orders/search", searchOrders);
app.post("/orders/:orderId/export", exportOrder);
app.listen(3000);
