"""
Entry-point idiom probe (B-036): which common framework idioms, with their route prefixes, does the index detect?

    <python with tree-sitter wheels> -m benchmarks.index_spike.idiom_probe

The fixtures in idioms/ are one tiny file per idiom. EXPECTED lists what a complete detector should report.
"""

from __future__ import annotations

from pathlib import Path

from benchmarks.index_spike.inhouse import index_repo

HERE = Path(__file__).resolve().parent / "idioms"
EXPECTED = {
    "flask_route.py": [("a", "/a")], "fastapi_prefix.py": [("b", "/v1/b")], "flask_blueprint.py": [("h", "/bp/h")],
    "django_urls.py": [("c", "c/")], "express_arrow.js": [("<anonymous>", "/d")], "aspnet_minimal.cs": [("<anonymous>", "/e")],
    "SpringMapping.java": [("f", "/f")], "Jaxrs.java": [("g", "/g")],
    # route prefixes and mounts
    "spring_prefix.java": [("items", "/api/items"), ("create", "/api")],
    "JaxrsMethodPath.java": [("one", "/g/{id}"), ("add", "/g")],
    "aspnet_controller.cs": [("Search", "api/Orders/search"), ("Absolute", "/absolute")],
    "aspnet_group.cs": [("<anonymous>", "/api/x"), ("Create", "/api/y")],
    "express_router.js": [("getX", "/api/x")],
    "fastapi_include.py": [("z", "/api/z")],
    "django_variants.py": [("a", "a/"), ("BView", "^b/$")],
}


def probe() -> dict[str, bool]:
    """file -> True when every expected (handler, route) of that file is reported."""
    found = {(e["file"], e["symbol"], e["route"]) for e in index_repo(HERE)["entry_points"] if e["kind"] == "http"}
    return {f: all((f, symbol, route) in found for symbol, route in expected) for f, expected in EXPECTED.items()}


if __name__ == "__main__":
    result = probe()
    for f, ok in result.items():
        print(f"{f:<22}{'detected' if ok else 'MISSED'}")
    print(f"{sum(result.values())}/{len(result)} idioms detected")
