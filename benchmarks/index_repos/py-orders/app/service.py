import subprocess

from app.repository import OrderRepository


class OrderService:
    def __init__(self):
        self.repo = OrderRepository()

    def search(self, term):
        return self.repo.find(term)

    def purge_old(self, days):
        return self.repo.delete_older_than(days)


class ExportService:
    def export(self, order_id, path):
        data = OrderRepository().get(order_id)
        with open(path, "w") as fh:
            fh.write(str(data))
        return path


def archive(path):
    subprocess.run(["tar", "czf", path + ".tgz", path])
