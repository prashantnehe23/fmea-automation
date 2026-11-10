namespace Orders
{
    public class OrderService
    {
        private readonly OrderRepository repo = new OrderRepository();

        public object Search(string term)
        {
            return repo.Find(term);
        }

        public void PurgeOlder(int days)
        {
            repo.DeleteOlderThan(days);
        }
    }
}
