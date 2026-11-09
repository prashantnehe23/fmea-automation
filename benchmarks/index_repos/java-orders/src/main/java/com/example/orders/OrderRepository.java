package com.example.orders;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.Statement;

public class OrderRepository {
    private Connection conn() throws Exception {
        return DriverManager.getConnection("jdbc:sqlite:orders.db");
    }

    public Object find(String term) {
        try (Statement st = conn().createStatement()) {
            return st.executeQuery("SELECT * FROM orders WHERE email LIKE '%" + term + "%'");
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    public Object get(int orderId) {
        try (PreparedStatement ps = conn().prepareStatement("SELECT * FROM orders WHERE id = ?")) {
            ps.setInt(1, orderId);
            return ps.executeQuery();
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    public void deleteOlderThan(int days) {
        try (PreparedStatement ps = conn().prepareStatement("DELETE FROM orders WHERE age > ?")) {
            ps.setInt(1, days);
            ps.executeUpdate();
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }
}
