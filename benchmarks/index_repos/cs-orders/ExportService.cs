using System.Diagnostics;
using System.IO;

namespace Orders
{
    public class ExportService
    {
        public string Export(int orderId, string path)
        {
            var data = new OrderRepository().Get(orderId);
            File.WriteAllText(path, data.ToString());
            return path;
        }

        public static void Archive(string path)
        {
            Process.Start("tar", "czf " + path + ".tgz " + path);
        }
    }
}
