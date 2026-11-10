package com.example.orders;

public class CleanupJob {
    public static void main(String[] args) throws Exception {
        new OrderService().purgeOlder(90);
        ExportService.archive("exports");
    }
}
