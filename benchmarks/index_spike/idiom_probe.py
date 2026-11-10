"""
Entry-point idiom probe (B-036 spike): which common framework idioms does the in-house index detect?

    <python with tree-sitter wheels> -m benchmarks.index_spike.idiom_probe

The fixtures in idioms/ are one tiny file per idiom. EXPECTED lists what a complete detector should report.
"""

from __future__ import annotations

from pathlib import Path

from benchmarks.index_spike.inhouse import index_repo

HERE = Path(__file__).resolve().parent / "idioms"
EXPECTED = {
    "flask_route.py": "a", "fastapi_prefix.py": "b", "flask_blueprint.py": "h", "django_urls.py": "c",
    "express_arrow.js": "<anonymous>", "aspnet_minimal.cs": "<anonymous>", "SpringMapping.java": "f", "Jaxrs.java": "g",
}


def probe() -> dict[str, bool]:
    found = {(e["file"], e["symbol"]) for e in index_repo(HERE)["entry_points"] if e["kind"] == "http"}
    return {f: (f, symbol) in found for f, symbol in EXPECTED.items()}


if __name__ == "__main__":
    result = probe()
    for f, ok in result.items():
        print(f"{f:<22}{'detected' if ok else 'MISSED'}")
    print(f"{sum(result.values())}/{len(result)} idioms detected")
