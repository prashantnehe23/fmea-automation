"""
tests/test_code_index_entries.py — B-036 phase 2: framework entry-point idioms and route prefixes

  AC1  Django urlpatterns, ASP.NET minimal APIs and controllers, JAX-RS, Spring, FastAPI, Flask and Express routes are found
  AC2  class, router, blueprint and group prefixes and mounts are joined into the route
Cases use shapes beyond the probe fixtures.
"""

import pytest

from benchmarks.index_spike.idiom_probe import probe
from core.code_index import build_index, join_route


def routes(files):
    return sorted((e.symbol, e.route) for e in build_index(files).entry_points if e.kind == "http")


def test_the_probe_detects_every_idiom_with_its_route():
    assert [f for f, ok in probe().items() if not ok] == []


@pytest.mark.parametrize("prefix, route, expected", [
    ("", "/x", "/x"), ("/api", "", "/api"), ("/api", "/x", "/api/x"), ("/api/", "x", "/api/x"),
    ("api/Orders", "search", "api/Orders/search"), ("", "", ""), ("/api", "/", "/api"),
])
def test_join_route(prefix, route, expected):
    assert join_route(prefix, route) == expected


# ── Python ────────────────────────────────────────────────────────────────────

def test_fastapi_prefixes_nested_includes_and_direct_app_routes():
    src = ('from fastapi import APIRouter, FastAPI\napp = FastAPI()\nparent = APIRouter(prefix="/p")\nchild = APIRouter(prefix="/c")\n\n'
           '@child.get("/x")\ndef x():\n    pass\n\n@app.post("/direct")\ndef direct():\n    pass\n\n'
           'parent.include_router(child, prefix="/inner")\napp.include_router(parent, prefix="/api")\n')
    assert routes({"a.py": src}) == [("direct", "/direct"), ("x", "/api/p/inner/c/x")]


def test_flask_registration_prefix_replaces_the_blueprint_prefix():
    src = ('from flask import Blueprint, Flask\napp = Flask(__name__)\nbp = Blueprint("bp", __name__, url_prefix="/own")\n\n'
           '@bp.route("/h", methods=["POST"])\ndef h():\n    pass\n\napp.register_blueprint(bp, url_prefix="/reg")\n')
    assert routes({"a.py": src}) == [("h", "/reg/h")]


def test_django_paths_keywords_class_views_and_includes():
    src = ('from django.urls import include, path, re_path\nfrom . import views\n\n'
           'urlpatterns = [\n    path("a/", views.a, name="a"),\n    re_path(r"^b/$", views.BView.as_view()),\n'
           '    path("sub/", include("shop.urls")),\n    path("c/", viewfunc),\n]\n')
    assert routes({"u.py": src}) == [("BView", "^b/$"), ("a", "a/"), ("viewfunc", "c/")]


def test_calls_that_are_not_routes_are_not_entry_points():
    src = 'cache = {}\nvalue = cache.get("/x", 1)\n\ndef handler():\n    return cache.get("/y")\n'
    assert routes({"a.py": src}) == []


# ── Java ──────────────────────────────────────────────────────────────────────

def test_spring_class_prefix_method_mappings_and_no_path_mappings():
    java = ('@RestController\n@RequestMapping("/api")\nclass A {\n  @GetMapping("/items") String items() { return ""; }\n'
            '  @PostMapping String create() { return ""; }\n  @RequestMapping(value = "/f", method = RequestMethod.PUT) String f() { return ""; }\n'
            '  String helper() { return ""; }\n}')
    assert routes({"A.java": java}) == [("create", "/api"), ("f", "/api/f"), ("items", "/api/items")]


def test_jaxrs_class_and_method_paths_and_verbs():
    java = ('@Path("/orders")\nclass B {\n  @GET @Path("/{id}") String one() { return ""; }\n  @DELETE @Path("/{id}") void drop() { }\n'
            '  @POST String add() { return ""; }\n  String helper() { return ""; }\n}')
    assert routes({"B.java": java}) == [("add", "/orders"), ("drop", "/orders/{id}"), ("one", "/orders/{id}")]


# ── C# ────────────────────────────────────────────────────────────────────────

def test_aspnet_controller_routes_tokens_and_absolute_overrides():
    cs = ('[ApiController]\n[Route("api/[controller]")]\npublic class OrdersController : ControllerBase {\n'
          '  [HttpGet] public string All() { return ""; }\n  [HttpGet("{id:int}")] public string One(int id) { return ""; }\n'
          '  [HttpPost("/top")] public string Top() { return ""; }\n}')
    assert routes({"O.cs": cs}) == [("All", "api/Orders"), ("One", "api/Orders/{id:int}"), ("Top", "/top")]


def test_aspnet_minimal_apis_handlers_and_nested_groups():
    cs = ('var app = WebApplication.CreateBuilder(args).Build();\napp.MapGet("/health", () => "ok");\n'
          'var v1 = app.MapGroup("/v1");\nvar orders = v1.MapGroup("/orders");\n'
          'orders.MapGet("/{id}", Handlers.Get);\norders.MapPost("/", async (HttpContext c) => { });\n')
    assert routes({"P.cs": cs}) == [("<anonymous>", "/health"), ("<anonymous>", "/v1/orders"), ("Get", "/v1/orders/{id}")]


# ── TypeScript / JavaScript ───────────────────────────────────────────────────

def test_express_routers_nested_mounts_and_multiple_handlers():
    js = ('const express = require("express");\nconst app = express();\nconst api = express.Router();\nconst items = express.Router();\n'
          'items.get("/:id", auth, getItem);\napi.use("/items", items);\napp.use("/api", api);\napp.post("/login", login);\n')
    assert routes({"r.js": js}) == [("getItem", "/api/items/:id"), ("login", "/login")]


def test_single_argument_get_calls_on_maps_are_not_routes():
    assert routes({"a.js": 'const m = new Map();\nm.get("/x");\n'}) == []


def test_mount_cycles_do_not_hang():
    js = 'const a = express.Router();\nconst b = express.Router();\na.use("/x", b);\nb.use("/y", a);\na.get("/z", h);\n'
    assert routes({"c.js": js})[0][0] == "h"
