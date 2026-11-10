package com.example.orders;

import org.springframework.web.bind.annotation.*;

@RestController
public class OrderController {
    private final OrderService orders = new OrderService();
    private final ExportService exports = new ExportService();

    @GetMapping("/orders/search")
    public Object searchOrders(@RequestParam String q) {
        return orders.search(q);
    }

    @PostMapping("/orders/{orderId}/export")
    public String exportOrder(@PathVariable int orderId, @RequestParam String path) {
        return exports.export(orderId, path);
    }
}
