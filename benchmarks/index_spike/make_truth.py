"""
Generate benchmarks/index_repos/*/index_truth.json from anchors, so the labelled lines can never drift
from the code. Run once after editing the repositories:  python -m benchmarks.index_spike.make_truth
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "index_repos"
J = "src/main/java/com/example/orders/"


def line_of(repo: str, file: str, anchor: str) -> int:
    lines = (ROOT / repo / file).read_text(encoding="utf-8").splitlines()
    hits = [i for i, l in enumerate(lines, 1) if anchor in l]
    assert len(hits) == 1, f"{repo}/{file}: anchor {anchor!r} matched {len(hits)} lines"
    return hits[0]


def entry(repo, id_, file, kind, symbol, anchor, route=None):
    e = {"id": id_, "file": file, "kind": kind, "symbol": symbol, "line": line_of(repo, file, anchor)}
    if route:
        e["route"] = route
    return e


def sink(repo, id_, file, kind, anchor):
    return {"id": id_, "file": file, "kind": kind, "line": line_of(repo, file, anchor)}


def call(callee_file, callee, caller_file, caller):
    return {"callee": {"file": callee_file, "symbol": callee}, "caller": {"file": caller_file, "symbol": caller}}


def build() -> dict[str, dict]:
    out: dict[str, dict] = {}

    r = "py-orders"
    out[r] = {
        "language": "python",
        "entry_points": [
            entry(r, "e1", "app/routes.py", "http", "search_orders", "def search_orders", "GET /orders/search"),
            entry(r, "e2", "app/routes.py", "http", "export_order", "def export_order", "POST /orders/{order_id}/export"),
            entry(r, "e3", "jobs.py", "main", "__main__", 'if __name__ == "__main__"'),
        ],
        "sinks": [
            sink(r, "s1", "app/repository.py", "sql", '.execute(f"SELECT'),
            sink(r, "s2", "app/repository.py", "sql", '.execute("SELECT * FROM orders WHERE id'),
            sink(r, "s3", "app/repository.py", "sql", '.execute("DELETE'),
            sink(r, "s4", "app/service.py", "file", 'open(path, "w")'),
            sink(r, "s5", "app/service.py", "command", "subprocess.run"),
        ],
        "calls": [
            call("app/repository.py", "find", "app/service.py", "search"),
            call("app/service.py", "search", "app/routes.py", "search_orders"),
            call("app/repository.py", "get", "app/service.py", "export"),
            call("app/service.py", "export", "app/routes.py", "export_order"),
            call("app/repository.py", "delete_older_than", "app/service.py", "purge_old"),
            call("app/service.py", "purge_old", "jobs.py", "nightly_cleanup"),
            call("app/service.py", "archive", "jobs.py", "nightly_cleanup"),
        ],
    }

    r = "java-orders"
    out[r] = {
        "language": "java",
        "entry_points": [
            entry(r, "e1", J + "OrderController.java", "http", "searchOrders", "public Object searchOrders", "GET /orders/search"),
            entry(r, "e2", J + "OrderController.java", "http", "exportOrder", "public String exportOrder", "POST /orders/{orderId}/export"),
            entry(r, "e3", J + "CleanupJob.java", "main", "main", "public static void main"),
        ],
        "sinks": [
            sink(r, "s1", J + "OrderRepository.java", "sql", "st.executeQuery("),
            sink(r, "s2", J + "OrderRepository.java", "sql", "ps.executeQuery()"),
            sink(r, "s3", J + "OrderRepository.java", "sql", "ps.executeUpdate()"),
            sink(r, "s4", J + "ExportService.java", "file", "new FileWriter(path)"),
            sink(r, "s5", J + "ExportService.java", "command", "Runtime.getRuntime().exec"),
        ],
        "calls": [
            call(J + "OrderRepository.java", "find", J + "OrderService.java", "search"),
            call(J + "OrderService.java", "search", J + "OrderController.java", "searchOrders"),
            call(J + "OrderRepository.java", "get", J + "ExportService.java", "export"),
            call(J + "ExportService.java", "export", J + "OrderController.java", "exportOrder"),
            call(J + "OrderRepository.java", "deleteOlderThan", J + "OrderService.java", "purgeOlder"),
            call(J + "OrderService.java", "purgeOlder", J + "CleanupJob.java", "main"),
            call(J + "ExportService.java", "archive", J + "CleanupJob.java", "main"),
        ],
    }

    r = "cs-orders"
    out[r] = {
        "language": "csharp",
        "entry_points": [
            entry(r, "e1", "OrdersController.cs", "http", "SearchOrders", "public object SearchOrders", "GET /orders/search"),
            entry(r, "e2", "OrdersController.cs", "http", "ExportOrder", "public string ExportOrder", "POST /orders/{orderId}/export"),
            entry(r, "e3", "CleanupJob.cs", "main", "Main", "public static void Main"),
        ],
        "sinks": [
            sink(r, "s1", "OrderRepository.cs", "sql", "cmd.ExecuteReader()"),
            sink(r, "s2", "OrderRepository.cs", "sql", "cmd.ExecuteScalar()"),
            sink(r, "s3", "OrderRepository.cs", "sql", "cmd.ExecuteNonQuery()"),
            sink(r, "s4", "ExportService.cs", "file", "File.WriteAllText"),
            sink(r, "s5", "ExportService.cs", "command", "Process.Start"),
        ],
        "calls": [
            call("OrderRepository.cs", "Find", "OrderService.cs", "Search"),
            call("OrderService.cs", "Search", "OrdersController.cs", "SearchOrders"),
            call("OrderRepository.cs", "Get", "ExportService.cs", "Export"),
            call("ExportService.cs", "Export", "OrdersController.cs", "ExportOrder"),
            call("OrderRepository.cs", "DeleteOlderThan", "OrderService.cs", "PurgeOlder"),
            call("OrderService.cs", "PurgeOlder", "CleanupJob.cs", "Main"),
            call("ExportService.cs", "Archive", "CleanupJob.cs", "Main"),
        ],
    }

    r = "ts-orders"
    out[r] = {
        "language": "typescript",
        "entry_points": [
            entry(r, "e1", "src/routes.ts", "http", "searchOrders", "function searchOrders", "GET /orders/search"),
            entry(r, "e2", "src/routes.ts", "http", "exportOrder", "function exportOrder", "POST /orders/:orderId/export"),
            entry(r, "e3", "src/jobs.ts", "main", "<main>", "if (require.main === module)"),
        ],
        "sinks": [
            sink(r, "s1", "src/repository.ts", "sql", ".all()"),
            sink(r, "s2", "src/repository.ts", "sql", ".get(orderId)"),
            sink(r, "s3", "src/repository.ts", "sql", ".run(days)"),
            sink(r, "s4", "src/service.ts", "file", "writeFileSync(path"),
            sink(r, "s5", "src/service.ts", "command", "execSync("),
        ],
        "calls": [
            call("src/repository.ts", "find", "src/service.ts", "search"),
            call("src/service.ts", "search", "src/routes.ts", "searchOrders"),
            call("src/repository.ts", "get", "src/service.ts", "exportOrder"),
            call("src/service.ts", "exportOrder", "src/routes.ts", "exportOrder"),
            call("src/repository.ts", "deleteOlderThan", "src/service.ts", "purgeOlder"),
            call("src/service.ts", "purgeOlder", "src/jobs.ts", "nightlyCleanup"),
            call("src/service.ts", "archive", "src/jobs.ts", "nightlyCleanup"),
        ],
    }
    return out


def main() -> None:
    for repo, truth in build().items():
        (ROOT / repo / "index_truth.json").write_text(json.dumps(truth, indent=2) + "\n", encoding="utf-8")
        print(repo, {k: len(v) for k, v in truth.items() if isinstance(v, list)})


if __name__ == "__main__":
    main()
