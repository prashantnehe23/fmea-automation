"""
B-028 phase B (ADR-015, ADR-032): a component map built from the code index, and work packets for the exploit-path hunt.

The hunt must see the pieces that depend on each other together: the handlers and the layer that is supposed to guard them.
A packet is a seed file plus the files it is wired to, within a byte budget. No model is involved here.
"""

from core.component_map import build_component_map, make_packets

ROUTES = ('from fastapi import FastAPI\nfrom api import auth, store\napp = FastAPI()\n\n'
          '@app.post("/files/{fid}")\ndef upload(fid: str, body: bytes):\n    auth.check_user(fid)\n    return store.save(fid, body)\n\n'
          '@app.get("/admin/export")\ndef export():\n    return store.dump()\n')
AUTH = 'def check_user(fid):\n    return True\n'
STORE = ('import os\n\ndef save(fid, body):\n    path = "data/" + fid\n    open(path, "wb").write(body)\n    return path\n\n'
         'def dump():\n    return os.listdir("data")\n')
LONELY = 'def helper():\n    return 1\n'
FILES = {"api/routes.py": ROUTES, "api/auth.py": AUTH, "api/store.py": STORE, "api/util.py": LONELY}


def test_the_map_records_entry_points_sinks_policy_files_and_cross_file_edges():
    cmap = build_component_map(FILES)
    assert sorted(cmap.files["api/routes.py"].routes) == ["/admin/export", "/files/{fid}"]
    assert cmap.files["api/store.py"].sinks == ["file"]
    assert cmap.files["api/auth.py"].policy and not cmap.files["api/store.py"].policy
    assert cmap.edges[("api/routes.py", "api/auth.py")] == 1 and cmap.edges[("api/routes.py", "api/store.py")] == 2
    assert ("api/util.py", "api/routes.py") not in cmap.edges


def test_neighbours_include_callers_and_callees_strongest_first():
    cmap = build_component_map(FILES)
    assert [p for p, _ in cmap.neighbours("api/routes.py")] == ["api/store.py", "api/auth.py"]
    assert [p for p, _ in cmap.neighbours("api/auth.py")] == ["api/routes.py"]            # a callee sees who calls it


def test_a_guard_that_only_the_framework_wires_up_still_travels_with_the_handlers():
    files = dict(FILES)
    files["api/middleware.py"] = "def require_login(request):\n    return True\n"     # nothing calls it directly
    packets, _ = make_packets(build_component_map(files), files, budget_bytes=10_000)
    assert any({"api/routes.py", "api/middleware.py"} <= set(p.files) for p in packets)


def test_a_table_built_from_another_modules_function_links_the_two_files():
    files = {"server/handlers.py": "def get_endpoints(pick):\n    return [('/x', pick('X'))]\n",
             "server/auth.py": "from server.handlers import get_endpoints\nVALIDATORS = get_endpoints(lambda c: c)\n"}
    cmap = build_component_map(files)
    assert cmap.edges.get(("server/auth.py", "server/handlers.py")) == 1                 # the module-level call counts
    packets, _ = make_packets(cmap, files, budget_bytes=10_000)
    assert any(set(p.files) == set(files) for p in packets)


def test_everything_fits_in_one_packet_when_the_budget_allows():
    packets, uncovered = make_packets(build_component_map(FILES), FILES, budget_bytes=100_000)
    assert len(packets) == 1 and set(packets[0].files) >= {"api/routes.py", "api/auth.py", "api/store.py"}
    assert uncovered == ["api/util.py"]                                    # no route, sink or guard: listed, not hunted


def test_a_small_budget_splits_into_packets_that_respect_it_and_keep_each_entry_file_with_its_guard():
    budget = len(ROUTES) + len(AUTH) + 20
    packets, uncovered = make_packets(build_component_map(FILES), FILES, budget_bytes=budget)
    assert len(packets) >= 1 and all(p.bytes <= budget or len(p.files) == 1 for p in packets)
    routes_packet = next(p for p in packets if "api/routes.py" in p.files)
    assert "api/auth.py" in routes_packet.files
    assert "api/store.py" not in routes_packet.files or routes_packet.bytes <= budget


def test_a_file_larger_than_the_budget_gets_its_own_flagged_packet():
    big = {"api/big.py": "@app.get('/x')\ndef x():\n    return 1\n" + "# pad\n" * 5000}
    packets, _ = make_packets(build_component_map(big), big, budget_bytes=1000)
    assert packets and packets[0].oversize and packets[0].files == ["api/big.py"]


def test_test_files_and_unsupported_languages_are_not_hunted_and_are_listed():
    files = dict(FILES)
    files["tests/test_routes.py"] = "def test_upload():\n    assert True\n"
    files["worker/main.go"] = "package main\nfunc main() {}\n"
    packets, uncovered = make_packets(build_component_map(files), files, budget_bytes=100_000)
    assert all("tests/test_routes.py" not in p.files for p in packets)
    assert "worker/main.go" in uncovered and "tests/test_routes.py" not in uncovered


def test_packets_are_deterministic():
    a = make_packets(build_component_map(FILES), FILES, budget_bytes=500)
    b = make_packets(build_component_map(dict(reversed(list(FILES.items())))), dict(reversed(list(FILES.items()))), budget_bytes=500)
    assert [p.files for p in a[0]] == [p.files for p in b[0]]


def test_the_summary_is_a_bounded_digest_a_model_can_read():
    cmap = build_component_map(FILES)
    text = cmap.summary(max_chars=2000)
    assert "api/routes.py" in text and "/files/{fid}" in text and "file sink" in text and "guard" in text
    assert "api/routes.py -> api/auth.py" in text
    assert len(cmap.summary(max_chars=120)) <= 120


# ── services linked only by where they run ────────────────────────────────────

PUBLIC = ('import requests\nfrom flask import Flask, request\napp = Flask(__name__)\n\n@app.get("/preview")\n'
          'def preview():\n    return requests.get(request.args["url"], timeout=5).text\n')
ADMIN = ('from flask import Flask\nadmin = Flask(__name__)\n\n@admin.get("/wipe-backups")\ndef wipe():\n    return "done"\n\n'
         'if __name__ == "__main__":\n    admin.run(host="127.0.0.1", port=9000)\n')


def test_a_service_that_makes_outbound_requests_is_linked_to_the_servers_it_could_reach():
    files = {"public.py": PUBLIC, "internal_admin.py": ADMIN}
    cmap = build_component_map(files)
    assert cmap.files["public.py"].outbound and not cmap.files["internal_admin.py"].outbound
    assert cmap.files["internal_admin.py"].listens == ["127.0.0.1:9000"]
    assert ("public.py", "internal_admin.py") in cmap.service_edges and ("internal_admin.py", "public.py") not in cmap.service_edges
    assert [p for p, _ in cmap.neighbours("public.py")] == ["internal_admin.py"]
    packets, _ = make_packets(cmap, files, budget_bytes=10_000)
    assert any(set(p.files) == set(files) for p in packets)
    text = cmap.summary()
    assert "public.py -> internal_admin.py" in text and "outbound" in text and "127.0.0.1:9000" in text


def test_without_outbound_requests_there_is_no_network_link():
    files = {"a.py": ADMIN, "b.py": ADMIN.replace("admin", "other")}
    assert build_component_map(files).service_edges == {}


def test_a_file_is_never_linked_to_itself_and_clients_are_detected_in_javascript():
    js = "const app = require('express')();\napp.get('/p', async (req, res) => { res.send(await fetch(req.query.u)); });\napp.listen(3000);\n"
    other = "const a = require('express')();\na.post('/x', (req, res) => res.send('ok'));\na.listen(4000);\n"
    cmap = build_component_map({"web.js": js, "api.js": other})
    assert cmap.files["web.js"].outbound and cmap.files["web.js"].listens == ["3000"]
    assert set(cmap.service_edges) == {("web.js", "api.js")}


def test_a_library_with_no_routes_sinks_or_guard_names_is_still_read_in_packets():
    nl = chr(10)
    lib = {"lib/keys.py": nl.join(["from lib import codec", "", "def load(raw):", "    return codec.decode(raw)", ""]),
           "lib/codec.py": nl.join(["def decode(raw):", "    return raw.strip()", ""]),
           "tests/test_keys.py": nl.join(["def test_x():", "    assert True", ""]),
           "src/lib.rs": "pub fn parse() {}" + nl}
    packets, uncovered = make_packets(build_component_map(lib), lib, budget_bytes=100_000)
    assert packets and {"lib/keys.py", "lib/codec.py"} <= {f for p in packets for f in p.files}
    assert "tests/test_keys.py" not in uncovered and all("tests/test_keys.py" not in p.files for p in packets)
    assert make_packets(build_component_map({}), {}, 1000) == ([], [])          # nothing at all still means nothing to hunt
