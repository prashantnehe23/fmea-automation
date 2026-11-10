package com.example.orders;

public class OrderService {
    private final OrderRepository repo = new OrderRepository();

    public Object search(String term) {
        return repo.find(term);
    }

    public void purgeOlder(int days) {
        repo.deleteOlderThan(days);
    }
}
