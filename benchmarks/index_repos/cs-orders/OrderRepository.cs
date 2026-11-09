using System.Data.SqlClient;

namespace Orders
{
    public class OrderRepository
    {
        private readonly SqlConnection conn = new SqlConnection("Data Source=orders.db");

        public object Find(string term)
        {
            var cmd = new SqlCommand("SELECT * FROM orders WHERE email LIKE '%" + term + "%'", conn);
            return cmd.ExecuteReader();
        }

        public object Get(int orderId)
        {
            var cmd = new SqlCommand("SELECT * FROM orders WHERE id = @id", conn);
            cmd.Parameters.AddWithValue("@id", orderId);
            return cmd.ExecuteScalar();
        }

        public void DeleteOlderThan(int days)
        {
            var cmd = new SqlCommand("DELETE FROM orders WHERE age > @days", conn);
            cmd.Parameters.AddWithValue("@days", days);
            cmd.ExecuteNonQuery();
        }
    }
}
