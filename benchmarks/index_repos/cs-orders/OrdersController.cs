using Microsoft.AspNetCore.Mvc;

namespace Orders
{
    [ApiController]
    public class OrdersController : ControllerBase
    {
        private readonly OrderService orders = new OrderService();
        private readonly ExportService exports = new ExportService();

        [HttpGet("/orders/search")]
        public object SearchOrders([FromQuery] string q)
        {
            return orders.Search(q);
        }

        [HttpPost("/orders/{orderId}/export")]
        public string ExportOrder(int orderId, [FromQuery] string path)
        {
            return exports.Export(orderId, path);
        }
    }
}
