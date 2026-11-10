namespace Orders
{
    public static class CleanupJob
    {
        public static void Main(string[] args)
        {
            new OrderService().PurgeOlder(90);
            ExportService.Archive("exports");
        }
    }
}
