"""
Workspace identity: customer + project + business function.

Each workspace maps to an isolated directory under memory/workspaces/ so that
caches, learning memory, and eval history are scoped per customer/project.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.paths import data_dir

_MEMORY_ROOT = data_dir(Path(__file__).resolve().parents[1] / "memory")


def _slugify(text: str) -> str:
    """Convert a display name to a filesystem-safe slug."""
    slug = text.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug[:40] or "default"


def workspace_dir(ws: "WorkspaceContext") -> Path:
    """Return (and create) the per-workspace directory."""
    d = _MEMORY_ROOT / "workspaces" / _slugify(ws.customer) / _slugify(ws.project)
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class WorkspaceContext:
    customer: str               # "Acme Corp"
    project: str                # "Payment API"
    function: str               # "Fraud detection"
    business_tier: str          # "Tier 1" / "Tier 2" / "Tier 3"
    user_type: str              # "external_customers" / "internal_staff" / "b2b"
    business_context: str = ""  # LLM-enriched paragraph (empty until enriched)
    customer_learning: bool = True  # opt-in for per-workspace learning

    @property
    def display_name(self) -> str:
        return f"{self.customer} / {self.project}"


def make_workspace(
    customer: str,
    project: str,
    function: str,
    tier: str,
    user_type: str,
    customer_learning: bool = True,
) -> "WorkspaceContext":
    return WorkspaceContext(
        customer=customer,
        project=project,
        function=function,
        business_tier=tier,
        user_type=user_type,
        customer_learning=customer_learning,
    )


# ── Persistence ──────────────────────────────────────────────────────────────────

def save_workspace_metadata(ws: WorkspaceContext) -> None:
    path = workspace_dir(ws) / "metadata.json"
    data = {
        "customer": ws.customer,
        "project": ws.project,
        "function": ws.function,
        "business_tier": ws.business_tier,
        "user_type": ws.user_type,
        "business_context": ws.business_context,
        "customer_learning": ws.customer_learning,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_workspace_metadata(customer: str, project: str) -> WorkspaceContext | None:
    d = _MEMORY_ROOT / "workspaces" / _slugify(customer) / _slugify(project)
    path = d / "metadata.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return WorkspaceContext(**data)
    except Exception:
        return None


def list_workspaces() -> list[WorkspaceContext]:
    """Return all saved workspaces, sorted by customer then project."""
    ws_root = _MEMORY_ROOT / "workspaces"
    results: list[WorkspaceContext] = []
    if not ws_root.exists():
        return results
    for cust_dir in sorted(ws_root.iterdir()):
        if not cust_dir.is_dir():
            continue
        for proj_dir in sorted(cust_dir.iterdir()):
            meta = proj_dir / "metadata.json"
            if meta.exists():
                try:
                    data = json.loads(meta.read_text(encoding="utf-8"))
                    results.append(WorkspaceContext(**data))
                except Exception:
                    pass
    return results


# ── Business context enrichment ──────────────────────────────────────────────────

def enrich_business_context(ws: WorkspaceContext, code_snippet: str) -> str:
    """
    Produce a 2-3 sentence business context paragraph via one small LLM call.
    Writes the result back to ws.business_context and persists metadata.
    Returns the enriched string.
    """
    from core.llm import call_llm

    prompt = f"""
You are a business analyst. Write 2-3 sentences describing the business context
of the system below, suitable for calibrating a risk analysis.

Customer: {ws.customer}
Project: {ws.project}
Business function: {ws.function}
System tier: {ws.business_tier}
Primary users: {ws.user_type}

Code excerpt (first 1500 chars):
{code_snippet[:1500]}

Output: plain prose only, 2-3 sentences, no headings or bullet points.
""".strip()

    result = call_llm(prompt, max_tokens=200)
    ctx = result.strip()
    ws.business_context = ctx
    save_workspace_metadata(ws)
    return ctx
