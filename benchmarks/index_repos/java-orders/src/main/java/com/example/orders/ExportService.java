package com.example.orders;

import java.io.FileWriter;
import java.io.IOException;

public class ExportService {
    public String export(int orderId, String path) {
        Object data = new OrderRepository().get(orderId);
        try (FileWriter fw = new FileWriter(path)) {
            fw.write(String.valueOf(data));
        } catch (IOException e) {
            throw new RuntimeException(e);
        }
        return path;
    }

    public static void archive(String path) throws IOException {
        Runtime.getRuntime().exec(new String[] {"tar", "czf", path + ".tgz", path});
    }
}
