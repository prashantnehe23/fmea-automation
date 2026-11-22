import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


def _flatten_to_str_dict(obj: Any) -> Dict[str, str]:
    """Coerce nested tier maps into Dict[str, str] for stable downstream prompts."""
    if obj is None:
        return {}
    if isinstance(obj, list):
        return {str(i): str(x) for i, x in enumerate(obj)}
    if not isinstance(obj, dict):
        return {"_": str(obj)}
    out: Dict[str, str] = {}
    if "tiers" in obj and isinstance(obj["tiers"], dict):
        obj = obj["tiers"]
    for k, v in obj.items():
        key = str(k)
        if isinstance(v, dict):
            for k2, v2 in v.items():
                sk = f"{key}.{k2}"
                out[sk] = json.dumps(v2) if isinstance(v2, (list, dict)) else str(v2)
        elif isinstance(v, list):
            out[key] = ", ".join(str(x) for x in v)
        else:
            out[key] = str(v)
    return out


def _mixed_to_str_list(obj: Any) -> List[str]:
    """Coerce list or categorized dict (LLM habit) into List[str]."""
    if obj is None:
        return []
    if isinstance(obj, list):
        return [str(x) for x in obj]
    if isinstance(obj, dict):
        lines: List[str] = []
        for k, v in obj.items():
            if isinstance(v, list):
                for x in v:
                    lines.append(f"{k}: {x}")
            elif isinstance(v, dict):
                lines.append(f"{k}: {json.dumps(v)}")
            else:
                lines.append(f"{k}: {v}")
        return lines
    return [str(obj)]


class SystemContext(BaseModel):
    tiering: Dict[str, str]
    attack_surfaces: List[str]
    failure_domains: List[str]

    @model_validator(mode="before")
    @classmethod
    def normalize_cartographer_json(cls, data: Any) -> Any:
        """LLMs often return service_tiering or dict-shaped surfaces/domains."""
        if not isinstance(data, dict):
            return data
        d = dict(data)
        if "tiering" not in d and "service_tiering" in d:
            d["tiering"] = d.pop("service_tiering")
        d["tiering"] = _flatten_to_str_dict(d.get("tiering"))
        d["attack_surfaces"] = _mixed_to_str_list(d.get("attack_surfaces"))
        d["failure_domains"] = _mixed_to_str_list(d.get("failure_domains"))
        return d


class FailureMode(BaseModel):
    failure_mode: str
    attack_chain: List[str]
    business_impact: str
    blast_radius: str
    trigger: str
    evidence: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_failure_payload(cls, data: Any) -> Any:
        from core.llm_coercion import coerce_failure_mode_payload

        if isinstance(data, dict):
            return coerce_failure_mode_payload(data)
        return data


class ControlAssessment(BaseModel):
    failure_mode: str
    controls: Dict[str, str]
    control_maturity: str
    gaps: List[str]


class RiskScore(BaseModel):
    failure_mode: str
    severity: int
    occurrence: int
    detection: int
    rpn: int
    priority: str
    priority_reason: str = ""
    justification: str
    severity_rationale: str
    occurrence_rationale: str
    detection_rationale: str


class Action(BaseModel):
    """One corrective or preventive action (B-030, ADR-018). Urgency is an ordering band, never a date."""
    id: str
    title: str
    detail: str = ""
    kind: str
    target: str = ""
    verification: str = ""
    owner_role: str = "developer"
    urgency: str = "next"


class RemediationPlan(BaseModel):
    failure_mode: str
    corrective: List[Action] = Field(default_factory=list)
    preventive: List[Action] = Field(default_factory=list)
    # Plans stored before B-030 carry text lists only; core.actions.plan_actions maps them to actions.
    fixes: List[str] = Field(default_factory=list)
    monitoring: List[str] = Field(default_factory=list)
    resilience_upgrades: List[str] = Field(default_factory=list)


class ScenarioExplanation(BaseModel):
    failure_mode: str
    scenario_summary: str
    code_connection: str
    links_to_other_scenarios: str


class ScenarioLinkageReport(BaseModel):
    explanations: List[ScenarioExplanation]
    cross_cutting_themes: str = ""


class ValidationResult(BaseModel):
    """Validator agent output: peer-review challenges and score adjustments."""
    failure_mode: str
    is_realistic: bool = True
    attack_chain_complete: bool = True
    rpn_calibrated: bool = True
    challenges: List[str] = Field(default_factory=list)
    severity_adjustment: int = 0       # -2 to +2 recommended delta
    occurrence_adjustment: int = 0
    detection_adjustment: int = 0
    confidence: float = 0.5            # 0.0–1.0
    verdict: str = ""


class RemediationResult(BaseModel):
    """Output of the auto-remediation agent for a single failure mode."""
    failure_mode: str
    before_rpn: int
    after_rpn: int = 0               # populated after rescan; 0 until then
    rpn_delta: int = 0               # before_rpn - after_rpn (positive = improvement)
    code_diff: str = ""              # unified diff string for display
    test_code: str = ""              # pytest-style test stub
    test_description: str = ""       # plain-English: what the test verifies
    patched_snippet: str = ""        # complete fixed function/block (for in-memory apply)
    applied: bool = False
