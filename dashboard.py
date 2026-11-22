"""
Streamlit UI: navigation pane, quick filters, RPN distribution, S/O/D breakdown,
scenario linkage, corrective and preventive actions, validator panel, workspace identity, GitHub fetch,
LLM-judge eval report with drift alerts.
Run: streamlit run dashboard.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core.actions import plan_actions
from core.models import ScenarioLinkageReport, ValidationResult
from workflows.fmea_pipeline import DEFAULT_MAX_FAILURE_MODES, run_fmea

ROOT = Path(__file__).resolve().parent
DEFAULT_CODE_PATH = ROOT / "data" / "wallet.py"

PRIORITY_COLOR = {
    "Critical": "#c0392b",
    "High":     "#e67e22",
    "Medium":   "#f1c40f",
    "Low":      "#27ae60",
}

CONFIDENCE_COLOR = {
    "high":   "#27ae60",
    "medium": "#e67e22",
    "low":    "#c0392b",
}

NAV_PAGES = [
    ("Portfolio Overview", "📊"),
    ("Risk Matrix",        "📋"),
    ("Risk Deep Dive",     "🔍"),
    ("Mitigation Plans",   "🛠️"),
    ("System Context",     "🗺️"),
    ("Eval Report",        "📈"),
    ("Auto-Remediation",   "🔧"),
]

_SS_DEFAULTS: dict = {
    "nav_page":        "Portfolio Overview",
    "selected_risk":   None,
    "filter_priority": "All",
    "filter_rpn_min":  0,
    "filter_rpn_max":  1000,
}


# ── Utility ────────────────────────────────────────────────────────────────────

def _priority_color(p: str) -> str:
    return PRIORITY_COLOR.get(p, "#7f8c8d")


def _confidence_label(c: float) -> tuple[str, str]:
    if c >= 0.7:
        return f"{c:.0%}", CONFIDENCE_COLOR["high"]
    if c >= 0.4:
        return f"{c:.0%}", CONFIDENCE_COLOR["medium"]
    return f"{c:.0%}", CONFIDENCE_COLOR["low"]


def _badge(text: str, color: str) -> str:
    return (
        f'<span style="background:{color};color:white;padding:2px 10px;'
        f'border-radius:8px;font-size:0.82em;font-weight:600">{text}</span>'
    )


def _risks_dataframe(risks) -> pd.DataFrame:
    return pd.DataFrame([r.model_dump() for r in risks])


# ── Filter ─────────────────────────────────────────────────────────────────────

def _apply_filters(risks, remediations, failures):
    pri = st.session_state["filter_priority"]
    rpn_lo = st.session_state["filter_rpn_min"]
    rpn_hi = st.session_state["filter_rpn_max"]
    kept: set[str] = set()
    f_risks = []
    for r in risks:
        if pri != "All" and r.priority != pri:
            continue
        if not (rpn_lo <= r.rpn <= rpn_hi):
            continue
        kept.add(r.failure_mode)
        f_risks.append(r)
    return (
        f_risks,
        [r for r in remediations if r.failure_mode in kept],
        [f for f in failures if f.failure_mode in kept],
    )


# ── Navigation ─────────────────────────────────────────────────────────────────

def _nav_labels() -> list[str]:
    return [f"{icon}  {name}" for name, icon in NAV_PAGES]


def _set_page(name: str) -> None:
    labels = _nav_labels()
    page_names = [n for n, _ in NAV_PAGES]
    idx = page_names.index(name) if name in page_names else 0
    st.session_state["nav_page"] = name
    st.session_state["_nav_radio"] = labels[idx]


def _on_nav_change() -> None:
    labels = _nav_labels()
    page_names = [n for n, _ in NAV_PAGES]
    raw = st.session_state.get("_nav_radio", labels[0])
    idx = labels.index(raw) if raw in labels else 0
    new_page = page_names[idx]
    if new_page != "Risk Deep Dive":
        st.session_state["selected_risk"] = None
    st.session_state["nav_page"] = new_page


def _render_nav_pane() -> None:
    labels = _nav_labels()
    page_names = [n for n, _ in NAV_PAGES]
    current = st.session_state["nav_page"]
    current_idx = page_names.index(current) if current in page_names else 0
    if "_nav_radio" not in st.session_state:
        st.session_state["_nav_radio"] = labels[current_idx]
    st.radio(
        "Navigate", labels, index=current_idx,
        label_visibility="collapsed", key="_nav_radio", on_change=_on_nav_change,
    )
    risks = st.session_state["fmea_result"]["risks"]
    crit = sum(1 for r in risks if r.priority == "Critical")
    high = sum(1 for r in risks if r.priority == "High")
    st.caption(f"🔴 {crit} Critical   🟠 {high} High")


# ── Quick filters ──────────────────────────────────────────────────────────────

def _reset_filters(rpn_min: int, rpn_max: int) -> None:
    st.session_state["filter_priority"] = "All"
    st.session_state["filter_rpn_min"] = rpn_min
    st.session_state["filter_rpn_max"] = rpn_max


def _render_quick_filters(risks) -> None:
    rpn_values = [r.rpn for r in risks]
    rpn_min_data = min(rpn_values, default=0)
    rpn_max_data = max(rpn_values, default=1000)
    if st.session_state["filter_rpn_min"] < rpn_min_data:
        st.session_state["filter_rpn_min"] = rpn_min_data
    if st.session_state["filter_rpn_max"] > rpn_max_data:
        st.session_state["filter_rpn_max"] = rpn_max_data

    priority_options = ["All", "Critical", "High", "Medium"]
    col_pill, col_slider, col_reset = st.columns([2, 3, 1])
    with col_pill:
        try:
            chosen = st.pills(
                "Priority filter", priority_options,
                default=st.session_state["filter_priority"],
                key="_pill_priority", label_visibility="collapsed",
            )
            st.session_state["filter_priority"] = chosen or "All"
        except AttributeError:
            chosen = st.radio(
                "Priority filter", priority_options,
                index=priority_options.index(st.session_state["filter_priority"]),
                horizontal=True, label_visibility="collapsed", key="_radio_priority",
            )
            st.session_state["filter_priority"] = chosen
    with col_slider:
        if rpn_min_data < rpn_max_data:
            lo = max(rpn_min_data, st.session_state["filter_rpn_min"])
            hi = min(rpn_max_data, st.session_state["filter_rpn_max"])
            rpn_range = st.slider(
                "RPN range", min_value=rpn_min_data, max_value=rpn_max_data,
                value=(lo, hi), label_visibility="collapsed", key="_slider_rpn",
            )
            st.session_state["filter_rpn_min"] = rpn_range[0]
            st.session_state["filter_rpn_max"] = rpn_range[1]
        else:
            st.caption(f"RPN: {rpn_min_data}")
    with col_reset:
        st.button("Reset", use_container_width=True,
                  on_click=_reset_filters, args=(rpn_min_data, rpn_max_data))
    st.divider()


# ── Shared validator panel ─────────────────────────────────────────────────────

def _render_validation_panel(validation: ValidationResult) -> None:
    conf_label, conf_color = _confidence_label(validation.confidence)

    flags = []
    if not validation.is_realistic:
        flags.append("⚠️ Realism questioned")
    if not validation.attack_chain_complete:
        flags.append("⚠️ Attack chain incomplete")
    if not validation.rpn_calibrated:
        flags.append("⚠️ RPN may be miscalibrated")

    adj_parts = []
    if validation.severity_adjustment:
        sign = "+" if validation.severity_adjustment > 0 else ""
        adj_parts.append(f"S{sign}{validation.severity_adjustment}")
    if validation.occurrence_adjustment:
        sign = "+" if validation.occurrence_adjustment > 0 else ""
        adj_parts.append(f"O{sign}{validation.occurrence_adjustment}")
    if validation.detection_adjustment:
        sign = "+" if validation.detection_adjustment > 0 else ""
        adj_parts.append(f"D{sign}{validation.detection_adjustment}")

    col_conf, col_flags = st.columns([1, 3])
    with col_conf:
        st.markdown(
            f'<div style="text-align:center">'
            f'<div style="font-size:0.75em;color:#aaa">Validator confidence</div>'
            f'<div style="font-size:1.6em;font-weight:700;color:{conf_color}">{conf_label}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with col_flags:
        if flags:
            for f in flags:
                st.warning(f)
        else:
            st.success("✅ FMEA entry passed all validator checks")
        if adj_parts:
            st.info(f"Score adjustments applied by validator: **{', '.join(adj_parts)}**")

    if validation.verdict:
        st.markdown(f"**Verdict:** {validation.verdict}")

    if validation.challenges:
        with st.expander(f"Validator challenges ({len(validation.challenges)})", expanded=bool(flags)):
            for ch in validation.challenges:
                st.write(f"- {ch}")


# ── Page renderers ─────────────────────────────────────────────────────────────

def render_portfolio_overview(ctx, failures, risks, remediations, validations, memory_stats, result) -> None:
    st.subheader("📊 Portfolio Overview")
    st.caption("Full risk landscape — unfiltered. Use the Risk Matrix to drill down.")

    # Workspace identity banner
    ws = result.get("workspace")
    if ws:
        st.info(
            f"**{ws.customer}** | {ws.project} | {ws.function} | "
            f"{ws.business_tier} | Users: {ws.user_type}"
        )

    # Scenario lock status banner
    registry_locked = result.get("registry_locked", False)
    workspace_id = result.get("workspace_id")
    new_scenarios = result.get("new_scenarios", [])
    if workspace_id:
        if registry_locked:
            from memory.scenario_registry import scenario_count
            sc = scenario_count(workspace_id)
            col_lock, col_btn = st.columns([5, 1])
            with col_lock:
                st.success(
                    f"🔒 **Scenarios locked** — {sc} canonical failure modes from first scan. "
                    "Results are deterministic across rescans."
                )
            with col_btn:
                if st.button("🔓 Unlock", key="_unlock_scenarios", help="Clear registry and force fresh scenarios on next run"):
                    from memory.scenario_registry import clear_registry
                    clear_registry(workspace_id)
                    st.session_state.pop("fmea_result", None)
                    st.rerun()
        else:
            st.info("🔓 **First scan** — failure modes and RPN scores will be locked after this analysis.")
        if new_scenarios:
            st.caption(f"🆕 {len(new_scenarios)} new scenario(s) discovered this run: {', '.join(new_scenarios)}")

    # Eval summary banner
    evaluation = result.get("evaluation")
    if evaluation:
        badge_color = "#27ae60" if evaluation.overall_passed else "#c0392b"
        badge_text = "✅ All agents passed" if evaluation.overall_passed else "❌ Pipeline issues"
        avg_score = round(sum(e.score for e in evaluation.agents) / max(len(evaluation.agents), 1), 2)
        st.markdown(
            f'{_badge(badge_text, badge_color)} &nbsp; '
            f'Avg quality score **{avg_score}** &nbsp;|&nbsp; '
            f'Est. cost **~${evaluation.estimated_cost_usd}**',
            unsafe_allow_html=True,
        )

    st.divider()

    # KPI row
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Failure scenarios", len(failures))
    with c2:
        st.metric("Highest RPN", max((r.rpn for r in risks), default=0))
    with c3:
        st.metric("Critical", sum(1 for r in risks if r.priority == "Critical"))
    with c4:
        st.metric("High", sum(1 for r in risks if r.priority == "High"))

    st.divider()

    df_r = _risks_dataframe(risks)
    if df_r.empty:
        st.warning("No risk rows to display.")
        return
    df_r["color"] = df_r["priority"].map(_priority_color)

    col_bar, col_donut = st.columns((1.4, 1))
    with col_bar:
        fig_bar = go.Figure(data=[go.Bar(
            x=df_r["failure_mode"], y=df_r["rpn"],
            marker_color=df_r["color"], text=df_r["rpn"], textposition="outside",
            hovertemplate=(
                "<b>%{x}</b><br>RPN: %{y}<br>"
                "S: %{customdata[0]} O: %{customdata[1]} D: %{customdata[2]}<extra></extra>"
            ),
            customdata=list(zip(df_r["severity"], df_r["occurrence"], df_r["detection"])),
        )])
        fig_bar.update_layout(
            title="RPN by failure mode", xaxis_title="Failure mode",
            yaxis_title="RPN (S \u00d7 O \u00d7 D)",
            showlegend=False, height=400, margin=dict(t=50, b=120),
        )
        fig_bar.update_xaxes(tickangle=-35)
        st.plotly_chart(fig_bar, use_container_width=True)

    with col_donut:
        pri_counts = df_r["priority"].value_counts().reset_index()
        pri_counts.columns = ["priority", "count"]
        fig_donut = px.pie(
            pri_counts, names="priority", values="count", hole=0.45,
            color="priority", color_discrete_map=PRIORITY_COLOR, title="Priority distribution",
        )
        fig_donut.update_traces(textposition="inside", textinfo="percent+label")
        fig_donut.update_layout(height=400, showlegend=False)
        st.plotly_chart(fig_donut, use_container_width=True)

    st.divider()

    # Validator summary
    if validations:
        st.markdown("### 🔬 Validator Summary")
        low_conf = [v for v in validations if v.confidence < 0.4]
        flagged = [v for v in validations if not (v.is_realistic and v.attack_chain_complete and v.rpn_calibrated)]
        adjusted = [v for v in validations if any([v.severity_adjustment, v.occurrence_adjustment, v.detection_adjustment])]
        avg_conf = sum(v.confidence for v in validations) / len(validations)

        vc1, vc2, vc3, vc4 = st.columns(4)
        with vc1:
            st.metric("Avg confidence", f"{avg_conf:.0%}")
        with vc2:
            st.metric("Flagged entries", len(flagged))
        with vc3:
            st.metric("Score adjustments", len(adjusted))
        with vc4:
            st.metric("Low confidence", len(low_conf))

    st.divider()

    # Learning memory stats
    st.markdown("### 🧠 Learning Memory")
    aggression = memory_stats.get("aggression_level", 1)
    total = memory_stats.get("total_analyses", 0)
    categories = memory_stats.get("known_categories", 0)
    chains = memory_stats.get("global_chain_count", 0)

    lc1, lc2, lc3, lc4 = st.columns(4)
    with lc1:
        st.metric("Analyses run", total)
    with lc2:
        st.metric("Aggression level", f"{aggression}/5")
    with lc3:
        st.metric("Known vuln categories", categories)
    with lc4:
        st.metric("Stored attack chains", chains)

    if aggression > 1:
        agg_descriptions = {
            2: "🟡 Probing — looking beyond standard OWASP categories",
            3: "🟠 Aggressive — chaining multi-step exploits",
            4: "🔴 Highly adversarial — assuming all defaults are misconfigured",
            5: "🚨 APT-level — maximally creative, no assumption is safe",
        }
        st.info(agg_descriptions.get(aggression, ""))

    top_patterns = memory_stats.get("top_patterns", [])
    if top_patterns:
        st.markdown("**Top recurring vulnerability categories:**")
        for p in top_patterns:
            st.write(
                f"- **{p['category'].replace('_', ' ').title()}** — "
                f"seen {p['frequency']}\u00d7 across {total} analyses, "
                f"avg RPN {p['avg_rpn']:.0f}"
            )


def _go_deep_cb(name: str) -> None:
    _set_page("Risk Deep Dive")
    st.session_state["selected_risk"] = name


def render_risk_matrix(risks, remediations, failures, validations, result: dict | None = None) -> None:
    st.subheader("📋 Risk Matrix")
    st.caption("All failure modes with scores. Click **Deep Dive** to explore any risk in detail.")
    st.divider()

    new_scenarios = set((result or {}).get("new_scenarios", []))
    filtered_risks, filtered_rems, filtered_fails = _apply_filters(risks, remediations, failures)
    total = len(risks)
    shown = len(filtered_risks)

    if shown == 0:
        st.warning("No risks match the current filters.")
        st.button(
            "Clear filters", key="matrix_clear",
            on_click=_reset_filters,
            args=(
                min((r.rpn for r in risks), default=0),
                max((r.rpn for r in risks), default=1000),
            ),
        )
        return

    st.caption(f"Showing **{shown}** of **{total}** risks")

    val_by_fm = {v.failure_mode: v for v in (validations or [])}

    h1, h2, h3, h4, h5, h6, h7, h8 = st.columns([3, 1, 1, 1, 1, 1.5, 1.2, 1.5])
    for col, label in zip(
        [h1, h2, h3, h4, h5, h6, h7, h8],
        ["**Failure mode**", "**S**", "**O**", "**D**", "**RPN**", "**Priority**", "**Confidence**", "**Action**"],
    ):
        with col:
            st.markdown(label)
    st.markdown("<hr style='margin:4px 0'>", unsafe_allow_html=True)

    for r in sorted(filtered_risks, key=lambda r: -r.rpn):
        c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([3, 1, 1, 1, 1, 1.5, 1.2, 1.5])
        with c1:
            label = r.failure_mode
            if label in new_scenarios:
                label = f"🆕 {label}"
            st.write(label)
        with c2:
            st.write(r.severity)
        with c3:
            st.write(r.occurrence)
        with c4:
            st.write(r.detection)
        with c5:
            st.write(r.rpn)
        with c6:
            st.markdown(_badge(r.priority, _priority_color(r.priority)), unsafe_allow_html=True)
        with c7:
            val = val_by_fm.get(r.failure_mode)
            if val:
                conf_label, conf_color = _confidence_label(val.confidence)
                has_issues = not (val.is_realistic and val.attack_chain_complete and val.rpn_calibrated)
                icon = "⚠️ " if has_issues else ""
                st.markdown(
                    f'<span style="color:{conf_color};font-weight:600">{icon}{conf_label}</span>',
                    unsafe_allow_html=True,
                )
        with c8:
            st.button("Deep Dive →", key=f"dd_{r.failure_mode}",
                      on_click=_go_deep_cb, args=(r.failure_mode,))

    st.divider()
    df_r = _risks_dataframe(sorted(filtered_risks, key=lambda r: -r.rpn))
    df_melt = df_r.melt(
        id_vars=["failure_mode", "priority"],
        value_vars=["severity", "occurrence", "detection"],
        var_name="factor", value_name="score",
    )
    fig_sod = px.bar(
        df_melt, x="failure_mode", y="score", color="factor",
        barmode="group", title="Severity / Occurrence / Detection breakdown", height=380,
    )
    fig_sod.update_xaxes(tickangle=-35)
    fig_sod.update_layout(legend_title_text="Factor")
    st.plotly_chart(fig_sod, use_container_width=True)
    st.caption(
        "Higher **detection** score means **weaker observability** \u2014 harder to detect or stop "
        "the failure before impact; it is \u201cnot\u201d good detection."
    )


def render_risk_deep_dive(risks, remediations, failures, controls, linkage, validations) -> None:
    st.subheader("🔍 Risk Deep Dive")
    st.caption("Full detail for one failure mode — scenario, S/O/D rationale, attack chain, controls, validator.")
    st.divider()

    filtered_risks, filtered_rems, filtered_fails = _apply_filters(risks, remediations, failures)
    if not filtered_risks:
        st.warning("No risks match the current filters.")
        return

    filtered_names = [r.failure_mode for r in sorted(filtered_risks, key=lambda r: -r.rpn)]
    selected = st.session_state.get("selected_risk")
    if selected not in filtered_names:
        selected = None

    col_sel, col_back = st.columns([4, 1])
    with col_sel:
        idx = filtered_names.index(selected) if selected in filtered_names else 0
        chosen = st.selectbox("Select failure mode", filtered_names, index=idx, label_visibility="collapsed")
        st.session_state["selected_risk"] = chosen
        selected = chosen

    with col_back:
        def _back():
            _set_page("Risk Matrix")
            st.session_state["selected_risk"] = None
        st.button("\u2190 Risk Matrix", on_click=_back, use_container_width=True)

    st.divider()

    risk = next((r for r in risks if r.failure_mode == selected), None)
    failure = next((f for f in failures if f.failure_mode == selected), None)
    rem = next((r for r in remediations if r.failure_mode == selected), None)
    control = next((c for c in controls if c.failure_mode == selected), None)
    explanation = next(
        (e for e in (linkage.explanations if linkage else []) if e.failure_mode == selected), None
    )
    validation = next((v for v in (validations or []) if v.failure_mode == selected), None)

    if risk is None:
        st.error("No risk data found for this failure mode.")
        return

    if explanation:
        st.info(f"**{explanation.scenario_summary}**")

    ca, cb, cc, cd = st.columns(4)
    with ca:
        st.metric("RPN", risk.rpn)
    with cb:
        st.markdown(
            f'<div style="margin-top:4px">{_badge(risk.priority, _priority_color(risk.priority))}</div>',
            unsafe_allow_html=True,
        )
    with cc:
        st.metric("Severity", risk.severity, help=risk.severity_rationale)
    with cd:
        st.metric("Occurrence", risk.occurrence, help=risk.occurrence_rationale)
    ca2, _, _, _ = st.columns(4)
    with ca2:
        st.metric("Detection", risk.detection, help=risk.detection_rationale)
    if risk.justification:
        st.markdown(f"**Justification:** {risk.justification}")

    st.divider()

    left, right = st.columns(2)
    with left:
        st.markdown("**Scenario explanation**")
        if explanation:
            st.markdown("*Code connection*")
            st.write(explanation.code_connection)
            st.markdown("*Links to other scenarios*")
            st.write(explanation.links_to_other_scenarios)
        else:
            st.caption("No scenario linkage data — re-run the pipeline.")

        if failure:
            st.markdown("**Attack chain**")
            for step in failure.attack_chain:
                st.write(f"\u2192 {step}")
            if failure.trigger:
                st.markdown(f"**Trigger:** {failure.trigger}")
            if failure.business_impact:
                st.markdown(f"**Business impact:** {failure.business_impact}")
            if failure.blast_radius:
                st.markdown(f"**Blast radius:** {failure.blast_radius}")

    with right:
        st.markdown("**Control assessment**")
        if control:
            maturity_color = {"low": "#c0392b", "moderate": "#e67e22", "high": "#27ae60"}.get(
                control.control_maturity.lower(), "#7f8c8d"
            )
            st.markdown(
                f'Maturity: {_badge(control.control_maturity.title(), maturity_color)}',
                unsafe_allow_html=True,
            )
            if control.controls:
                st.markdown("*Existing controls*")
                for name, desc in control.controls.items():
                    st.write(f"- **{name}**: {desc}")
            if control.gaps:
                st.markdown("*Gaps*")
                for g in control.gaps:
                    st.write(f"- {g}")
        else:
            st.caption("No control data available.")

    if validation:
        st.divider()
        st.markdown("### 🔬 Validator Findings")
        _render_validation_panel(validation)

    if rem:
        st.divider()
        def _go_mitigation():
            _set_page("Mitigation Plans")
        st.button("\U0001f6e0\ufe0f View Mitigation Plan \u2192", on_click=_go_mitigation, type="primary")


def render_mitigation_plans(risks, remediations, failures) -> None:
    st.subheader("🛠️ Mitigation Plans")
    st.caption("Corrective and preventive actions, sorted by RPN (highest risk first).")
    st.divider()

    filtered_risks, filtered_rems, filtered_fails = _apply_filters(risks, remediations, failures)
    if not filtered_risks:
        st.warning("No risks match the current filters.")
        return

    pairs = sorted(zip(filtered_risks, filtered_rems), key=lambda z: -z[0].rpn)

    for risk, rem in pairs:
        st.markdown(
            f"### {rem.failure_mode} "
            + _badge(risk.priority, _priority_color(risk.priority)),
            unsafe_allow_html=True,
        )
        c_a, c_b, c_c = st.columns(3)
        with c_a:
            st.metric("RPN", risk.rpn)
        with c_b:
            st.metric("Priority", risk.priority)
        with c_c:
            st.metric("S/O/D", f"{risk.severity}/{risk.occurrence}/{risk.detection}")

        corrective, preventive = plan_actions(rem)
        for heading, actions in (("Corrective actions", corrective), ("Preventive actions", preventive)):
            st.markdown(f"**{heading}**")
            for x in actions:
                st.write(f"- [{x.urgency}] {x.title} ({x.kind}; target: {x.target or 'not stated'}; owner: {x.owner_role})")
                if x.verification:
                    st.caption(f"Verify: {x.verification}")

        st.divider()


def render_system_context(ctx, failures, linkage) -> None:
    st.subheader("🗺️ System Context")
    st.caption("System cartography, cross-cutting themes, and per-scenario intelligence.")
    st.divider()

    with st.expander("System cartography (JSON)", expanded=False):
        st.json(ctx.model_dump())

    if linkage and linkage.cross_cutting_themes:
        st.markdown("**Cross-cutting themes**")
        st.write(linkage.cross_cutting_themes)
        st.divider()

    st.markdown("**Scenario intelligence**")
    if linkage and linkage.explanations:
        for ex in linkage.explanations:
            with st.expander(f"**{ex.failure_mode}**", expanded=False):
                st.markdown("**One-line summary**")
                st.write(ex.scenario_summary)
                st.markdown("**How this maps to the code**")
                st.write(ex.code_connection)
                st.markdown("**Relationship to other scenarios**")
                st.write(ex.links_to_other_scenarios)
    else:
        st.info("No scenario linkage payload; re-run the pipeline.")

    with st.expander("Raw failures & remediations (JSON)", expanded=False):
        result = st.session_state.get("fmea_result", {})
        st.json({"failures": [f.model_dump() for f in result.get("failures", [])]})
        st.json({"remediations": [r.model_dump() for r in result.get("remediations", [])]})


def render_eval_report(result: dict) -> None:
    st.subheader("📈 Eval Report")
    st.caption("Rule-based + LLM-judge quality scores, drift alerts, and run history.")

    evaluation = result.get("evaluation")
    judge_verdicts = result.get("judge_verdicts", [])
    drift_alerts = result.get("drift_alerts", [])
    ws = result.get("workspace")

    # Drift alerts
    if drift_alerts:
        for alert in drift_alerts:
            st.warning(f"📉 Drift detected: {alert}")
    else:
        st.success("No score drift detected vs previous runs.")

    st.divider()

    if evaluation is None:
        st.info("Run the pipeline to see evaluation results.")
        return

    # Overall badge
    badge_color = "#27ae60" if evaluation.overall_passed else "#c0392b"
    badge_text = "✅ All agents passed" if evaluation.overall_passed else "❌ Pipeline issues found"
    avg_score = round(sum(e.score for e in evaluation.agents) / max(len(evaluation.agents), 1), 2)
    col_badge, col_cost, col_calls, col_scenarios = st.columns(4)
    with col_badge:
        st.markdown(_badge(badge_text, badge_color), unsafe_allow_html=True)
    with col_cost:
        st.metric("Est. cost", f"~${evaluation.estimated_cost_usd}")
    with col_calls:
        st.metric("LLM calls", evaluation.llm_calls)
    with col_scenarios:
        st.metric("Scenarios", evaluation.scenario_count)

    st.divider()

    # Per-agent cards
    judge_by_agent = {v.agent: v for v in judge_verdicts}

    st.markdown("### Agent quality scores")
    for agent_eval in evaluation.agents:
        judge = judge_by_agent.get(agent_eval.agent)

        col_name, col_rule, col_judge, col_overall = st.columns([2, 1, 1, 1])
        with col_name:
            icon = "✅" if agent_eval.passed else "❌"
            st.markdown(f"**{icon} {agent_eval.agent}**")
        with col_rule:
            st.metric("Rule score", f"{agent_eval.score:.2f}", help="Rule-based (0–1)")
        with col_judge:
            if judge:
                st.metric("Judge score", f"{judge.overall:.2f}", help="LLM-as-judge (0–1)")
            else:
                st.metric("Judge score", "—")
        with col_overall:
            if judge:
                combined = round((agent_eval.score + judge.overall) / 2, 2)
                st.metric("Combined", f"{combined:.2f}")

        if judge and judge.commentary:
            st.caption(f"Judge: {judge.commentary}")

        issues_and_warnings = agent_eval.issues + agent_eval.warnings
        if issues_and_warnings:
            with st.expander(f"Issues & warnings ({len(issues_and_warnings)})", expanded=bool(agent_eval.issues)):
                for issue in agent_eval.issues:
                    st.error(issue)
                for warning in agent_eval.warnings:
                    st.warning(warning)

        if judge:
            with st.expander("Judge detail", expanded=False):
                j1, j2, j3 = st.columns(3)
                with j1:
                    st.metric("Reasoning quality", f"{judge.reasoning_quality:.2f}")
                with j2:
                    st.metric("Specificity", f"{judge.specificity:.2f}")
                with j3:
                    st.metric("Calibration", f"{judge.calibration:.2f}")

        st.markdown("---")

    # Eval trend chart
    st.markdown("### Run history")
    try:
        from memory import eval_store
        trend = eval_store.get_eval_trend(ws, n=15)
        if len(trend) >= 2:
            agents_in_trend = sorted({a for r in trend for a in r.get("agent_scores", {})})
            rows = []
            for rec in trend:
                ts = rec["timestamp"][:16]
                for agent in agents_in_trend:
                    score = rec.get("agent_scores", {}).get(agent)
                    if score is not None:
                        rows.append({"run": ts, "agent": agent, "score": score})
            if rows:
                df_trend = pd.DataFrame(rows)
                fig_trend = px.line(
                    df_trend, x="run", y="score", color="agent",
                    title="Agent quality scores over time",
                    labels={"score": "Score (0\u20131)", "run": "Run"},
                    range_y=[0, 1.05],
                    height=360,
                )
                fig_trend.update_traces(mode="lines+markers")
                fig_trend.update_xaxes(tickangle=-30)
                st.plotly_chart(fig_trend, use_container_width=True)

        if trend:
            st.markdown("**History table**")
            df_hist = pd.DataFrame([
                {
                    "Timestamp": r["timestamp"][:19],
                    "Passed": "✅" if r.get("overall_passed") else "❌",
                    "Avg score": f"{r.get('avg_score', 0):.3f}",
                    "Scenarios": r.get("scenario_count", "—"),
                    "LLM calls": r.get("llm_calls", "—"),
                    "Est. cost $": r.get("estimated_cost_usd", "—"),
                }
                for r in reversed(trend)
            ])
            st.dataframe(df_hist, use_container_width=True, hide_index=True)
        else:
            st.info("No history yet — run the pipeline at least twice to see trends.")
    except Exception as exc:
        st.caption(f"Could not load eval history: {exc}")


# ── Workspace sidebar form ─────────────────────────────────────────────────────

def _render_workspace_form() -> object | None:
    """Render the workspace identity form and return a WorkspaceContext or None."""
    from core.workspace import WorkspaceContext, list_workspaces, load_workspace_metadata, save_workspace_metadata

    st.markdown("### Workspace")

    saved = list_workspaces()
    saved_labels = ["(new workspace)"] + [ws.display_name for ws in saved]
    chosen_label = st.selectbox("Load saved workspace", saved_labels, key="_ws_select")

    if chosen_label != "(new workspace)":
        idx = saved_labels.index(chosen_label) - 1
        ws = saved[idx]
    else:
        ws = None

    with st.form("workspace_form", border=False):
        customer = st.text_input("Customer", value=ws.customer if ws else "", placeholder="Acme Corp")
        project = st.text_input("Project", value=ws.project if ws else "", placeholder="Payment API")
        function = st.text_input("Business function", value=ws.function if ws else "", placeholder="Fraud detection")
        tier = st.selectbox(
            "System tier",
            ["Tier 1", "Tier 2", "Tier 3"],
            index=["Tier 1", "Tier 2", "Tier 3"].index(ws.business_tier) if ws else 0,
        )
        user_type = st.selectbox(
            "Primary users",
            ["external_customers", "internal_staff", "b2b"],
            index=["external_customers", "internal_staff", "b2b"].index(ws.user_type) if ws else 0,
        )
        cust_learning = st.checkbox(
            "Enable customer learning",
            value=ws.customer_learning if ws else True,
            help="Store failure patterns for this workspace. Disable for privacy-sensitive projects.",
        )
        submitted = st.form_submit_button("Save workspace", use_container_width=True)

    if submitted and customer and project:
        new_ws = WorkspaceContext(
            customer=customer,
            project=project,
            function=function,
            business_tier=tier,
            user_type=user_type,
            business_context=ws.business_context if ws else "",
            customer_learning=cust_learning,
        )
        save_workspace_metadata(new_ws)
        st.session_state["_active_workspace"] = new_ws
        st.success(f"Workspace saved: {new_ws.display_name}")
        return new_ws

    if ws:
        st.session_state["_active_workspace"] = ws
        return ws

    return st.session_state.get("_active_workspace")


# ── GitHub browser (main content area) ────────────────────────────────────────
#
# Session state keys:
#   _gh_step        : None | "scanned" | "fetched"
#   _gh_ref         : RepoRef
#   _gh_all_files   : list[str] all non-binary file paths
#   _gh_readme_path : str | None
#   _gh_code        : str (concatenated, after fetch)
#   _gh_paths       : list[str] actually fetched paths
#
# Renders entirely in the main content column (not the sidebar).
# Returns the fetched code string, or "" while file selection is in progress.


def _render_github_main() -> str:
    """
    Full-width GitHub repository browser rendered in the main content area.
    Returns code string when files have been fetched; "" otherwise.
    """
    from core.github_fetcher import (
        fetch_readme,
        fetch_selected_files,
        get_category,
        scan_repo,
    )

    step = st.session_state.get("_gh_step")

    st.subheader("🐙 GitHub Repository Browser")

    # ── URL row ────────────────────────────────────────────────────────────────
    c_url, c_skip, c_scan, c_reset = st.columns([5, 2, 1, 1])
    with c_url:
        url = st.text_input(
            "Repository URL",
            placeholder="https://github.com/owner/repo",
            key="_gh_url",
            label_visibility="collapsed",
        )
    with c_skip:
        skip_tests = st.checkbox(
            "Skip test files", value=True, key="_gh_skip_tests",
            help="Excludes paths matching test_*, /tests/, /test/, .spec., __tests__/",
        )
    with c_scan:
        scan_clicked = st.button(
            "🔍 Scan", use_container_width=True,
            disabled=not bool(url), key="_gh_scan",
        )
    with c_reset:
        if step is not None:
            if st.button("↺ Reset", use_container_width=True, key="_gh_reset"):
                for k in ("_gh_step", "_gh_ref", "_gh_all_files",
                          "_gh_readme_path", "_gh_code", "_gh_paths"):
                    st.session_state.pop(k, None)
                st.rerun()

    # ── Scan action ────────────────────────────────────────────────────────────
    if scan_clicked and url:
        try:
            with st.spinner(f"Scanning {url} …"):
                ref, files, readme_path = scan_repo(url, skip_tests=skip_tests)
            st.session_state.update({
                "_gh_ref": ref,
                "_gh_all_files": files,
                "_gh_readme_path": readme_path,
                "_gh_step": "scanned",
            })
            st.session_state.pop("_gh_code", None)
            st.session_state.pop("_gh_paths", None)
            st.rerun()
        except Exception as exc:
            st.error(f"Scan failed: {exc}")
            return ""

    if step not in ("scanned", "fetched"):
        st.caption("Enter a public GitHub URL and click **Scan** to browse files.")
        return ""

    ref = st.session_state["_gh_ref"]
    all_files: list[str] = st.session_state.get("_gh_all_files", [])
    readme_path: str | None = st.session_state.get("_gh_readme_path")

    # ── Already fetched — summary view ────────────────────────────────────────
    if step == "fetched":
        fetched_paths: list[str] = st.session_state.get("_gh_paths", [])
        code: str = st.session_state.get("_gh_code", "")

        st.success(
            f"✅ **{len(fetched_paths)} files loaded** from "
            f"`{ref.owner}/{ref.repo}` — click **Run FMEA pipeline** in the sidebar."
        )

        col_files, col_re = st.columns([3, 1])
        with col_files:
            cats = [get_category(p) for p in fetched_paths]
            cat_icons = {"readme": "📋", "code": "📄", "config": "⚙️", "doc": "📖", "other": "📎"}
            with st.expander(f"Loaded files ({len(fetched_paths)})", expanded=False):
                for p, c in zip(fetched_paths, cats):
                    st.caption(f"{cat_icons.get(c,'📎')} `{p}`")
        with col_re:
            if st.button("↩ Change selection", use_container_width=True, key="_gh_resel"):
                st.session_state["_gh_step"] = "scanned"
                st.rerun()

        # README → workspace context (only if README was fetched)
        if readme_path and readme_path in fetched_paths:
            ws_state = st.session_state.get("_active_workspace")
            if ws_state and not ws_state.business_context:
                if st.button(f"📄 Set business context from {readme_path}", key="_gh_readme_ctx"):
                    try:
                        readme_text = fetch_readme(ref, readme_path)
                        ws_state.business_context = readme_text[:800]
                        from core.workspace import save_workspace_metadata
                        save_workspace_metadata(ws_state)
                        st.session_state["_active_workspace"] = ws_state
                        st.success("Business context set from README.")
                    except Exception as exc:
                        st.error(f"Could not read README: {exc}")

        return code

    # ── File selection view ────────────────────────────────────────────────────
    cats = [get_category(p) for p in all_files]
    cat_icons = {"readme": "📋", "code": "📄", "config": "⚙️", "doc": "📖", "other": "📎"}
    avail_cats = sorted(set(cats))

    st.caption(
        f"**{ref.owner}/{ref.repo}** (`{ref.branch}`) — "
        f"{len(all_files)} files found"
        + (f" | README: `{readme_path}`" if readme_path else "")
    )

    # Category filter pills
    filter_cols = st.columns(len(avail_cats) + 1)
    cat_on: dict[str, bool] = {}
    for i, cat in enumerate(avail_cats):
        count = cats.count(cat)
        with filter_cols[i]:
            cat_on[cat] = st.checkbox(
                f"{cat_icons.get(cat, '📎')} {cat} ({count})",
                value=True,
                key=f"_gh_cat_{cat}",
            )
    with filter_cols[-1]:
        st.write("")  # spacer

    # Apply category filter
    visible = [(p, c) for p, c in zip(all_files, cats) if cat_on.get(c, True)]
    if not visible:
        st.warning("No files match the selected categories.")
        return ""

    vis_paths, vis_cats = zip(*visible)

    # Select / Deselect all buttons
    sa_col, da_col, info_col = st.columns([1, 1, 6])
    with sa_col:
        if st.button("✅ Select all", key="_gh_sel_all", use_container_width=True):
            st.session_state["_gh_editor_all"] = True
    with da_col:
        if st.button("⬜ Deselect all", key="_gh_des_all", use_container_width=True):
            st.session_state["_gh_editor_all"] = False

    # Compute defaults (code + readme = True by default; first scan)
    override = st.session_state.pop("_gh_editor_all", None)
    defaults = [override if override is not None else (c in ("code", "readme"))
                for c in vis_cats]

    df_files = pd.DataFrame({
        "Include": defaults,
        "File": list(vis_paths),
        "Type": list(vis_cats),
    })

    edited = st.data_editor(
        df_files,
        hide_index=True,
        key="_gh_file_editor",
        use_container_width=True,
        height=min(560, max(180, len(df_files) * 35 + 45)),
        column_config={
            "Include": st.column_config.CheckboxColumn(
                "Include", default=True, width="small",
            ),
            "File": st.column_config.TextColumn(
                "File path", disabled=True,
            ),
            "Type": st.column_config.TextColumn(
                "Type", disabled=True, width="small",
            ),
        },
    )

    selected = edited[edited["Include"]]["File"].tolist()

    # Byte limit info
    st.caption(
        f"**{len(selected)}** of {len(df_files)} files selected. "
        "A 300 KB byte-soft-limit applies to the concatenated output — "
        "files beyond the limit are noted but not included."
    )

    # Fetch button
    fetch_btn = st.button(
        f"⬇️  Fetch {len(selected)} file(s) & prepare for analysis",
        type="primary",
        disabled=not selected,
        key="_gh_fetch",
        use_container_width=True,
    )

    if fetch_btn and selected:
        with st.spinner(f"Fetching {len(selected)} files from GitHub…"):
            code, fetched = fetch_selected_files(ref, selected)

        st.session_state.update({
            "_gh_code": code,
            "_gh_paths": fetched,
            "_gh_step": "fetched",
        })
        st.rerun()

    return ""


# ── Auto-Remediation page ─────────────────────────────────────────────────────

def render_auto_remediation(result: dict) -> None:
    st.subheader("🔧 Auto-Remediation")
    st.caption(
        "AI-generated code fixes with test stubs. "
        "Fixes are applied in descending RPN order. "
        "The modified code is rescanned to compute before/after RPN."
    )
    st.divider()

    failures = result.get("failures", [])
    remediations = result.get("remediations", [])
    risks = result.get("risks", [])

    if not failures:
        st.warning("No failure modes found. Run the FMEA pipeline first.")
        return

    # Priority queue table
    rows = sorted(
        [{"Failure Mode": r.failure_mode, "Before RPN": r.rpn, "Priority": r.priority,
          "Status": "✅ Fixed" if r.failure_mode in {
              x.failure_mode for x in st.session_state.get("_remed_results", []) if x.applied
          } else "⏳ Pending"}
         for r in risks],
        key=lambda x: -x["Before RPN"],
    )
    st.dataframe(rows, use_container_width=True, hide_index=True)

    col_run, col_clear = st.columns([2, 1])
    with col_run:
        run_all = st.button(
            "🚀 Remediate All by Priority",
            type="primary",
            use_container_width=True,
            help="Apply fixes in descending RPN order, then rescan the patched code.",
        )
    with col_clear:
        if st.button("🗑 Clear Results", use_container_width=True):
            st.session_state.pop("_remed_results", None)
            st.rerun()

    if run_all:
        code = st.session_state.get("_fmea_last_code", "")
        if not code:
            st.error("Original code not found in session. Run the pipeline again.")
        else:
            from agents.remediator import apply_and_rescan
            ws = result.get("workspace")
            with st.spinner("Generating fixes and rescanning… (this may take 1–2 minutes)"):
                try:
                    remed_results = apply_and_rescan(failures, remediations, risks, code, workspace=ws)
                    st.session_state["_remed_results"] = remed_results
                except Exception as exc:
                    st.error(f"Remediation failed: {exc}")
                    return
            st.success("✅ Remediation complete. See results below.")
            st.rerun()

    remed_results = st.session_state.get("_remed_results", [])
    if not remed_results:
        st.info("Click **Remediate All by Priority** to generate fixes and rescan.")
        return

    st.divider()

    # Before/After summary table
    summary_rows = sorted([
        {
            "Failure Mode": r.failure_mode,
            "Before RPN": r.before_rpn,
            "After RPN": r.after_rpn,
            "Δ RPN": r.rpn_delta,
            "Status": "✅ Improved" if r.rpn_delta > 0 else ("⚠️ No change" if r.rpn_delta == 0 else "🔴 Regressed"),
        }
        for r in remed_results
    ], key=lambda x: -x["Before RPN"])

    st.markdown("### 📊 Before / After RPN Summary")
    st.dataframe(summary_rows, use_container_width=True, hide_index=True)

    # Per-scenario expanders
    st.markdown("### 🔍 Fix Details")
    for r in sorted(remed_results, key=lambda x: -x.before_rpn):
        delta_icon = "🟢" if r.rpn_delta > 0 else ("🔴" if r.rpn_delta < 0 else "⚪")
        delta_str = f"{delta_icon} {r.before_rpn} → {r.after_rpn} (Δ {r.rpn_delta:+d})"
        with st.expander(f"**{r.failure_mode}** — RPN: {delta_str}", expanded=False):
            if r.test_description:
                st.info(f"**Test verifies:** {r.test_description}")

            if r.code_diff:
                st.markdown("**Code diff:**")
                st.code(r.code_diff, language="diff")
            else:
                st.warning("No code diff generated.")

            if r.test_code:
                st.markdown("**Test stub (paste into your test suite):**")
                st.code(r.test_code, language="python")
            else:
                st.warning("No test stub generated.")


# ── Main dispatcher ────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="FMEA Automation",
        page_icon="🛡️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    for _k, _v in _SS_DEFAULTS.items():
        if _k not in st.session_state:
            st.session_state[_k] = _v

    st.title("FMEA automation")
    st.caption(
        "Resilience pipeline: cartography → adversary → scenario linkage → "
        "controls → RPN → validator → remediation → LLM judge"
    )

    # ── Sidebar ────────────────────────────────────────────────────────────────
    with st.sidebar:
        # Zone 0: Workspace identity
        active_ws = _render_workspace_form()
        st.divider()

        # Zone 1: Source selector (GitHub browser renders in main area)
        st.header("Source code")
        source = st.radio(
            "Input",
            ("Default `data/wallet.py`", "Paste code", "Upload file", "GitHub URL"),
            key="_source_radio",
        )
        code = ""
        if source == "Default `data/wallet.py`":
            code = DEFAULT_CODE_PATH.read_text(encoding="utf-8")
            st.text_area("Preview", code, height=120, disabled=True)
        elif source == "Paste code":
            code = st.text_area("Python source", height=200, placeholder="Paste code…")
        elif source == "Upload file":
            up = st.file_uploader("Source file", type=["py", "js", "ts", "java", "go", "rb"])
            if up:
                code = up.getvalue().decode("utf-8", errors="replace")
                st.text_area("Preview", code[:4000], height=120, disabled=True)
        else:
            # Code comes from GitHub browser (main area); pull from session state
            code = st.session_state.get("_gh_code", "")
            if code:
                st.success(
                    f"✅ {len(st.session_state.get('_gh_paths', []))} files loaded from GitHub"
                )
            else:
                st.caption("Use the GitHub browser on the right →")

        # Enrich business context (non-GitHub sources)
        if source != "GitHub URL" and active_ws and not active_ws.business_context and code:
            if st.button("Enrich business context (1 LLM call)", key="_enrich_biz"):
                from core.workspace import enrich_business_context
                with st.spinner("Enriching…"):
                    ctx = enrich_business_context(active_ws, code)
                st.success("Business context set.")
                st.caption(ctx[:160])

        force_rerun = st.checkbox(
            "Force re-run (ignore cache)",
            value=False,
            help="Bypass the code-fingerprint cache and run the full pipeline.",
        )
        run = st.button("Run FMEA pipeline", type="primary", use_container_width=True)

        if "fmea_result" in st.session_state:
            st.divider()
            st.markdown("### Navigation")
            _render_nav_pane()

    # ── GitHub browser takes over main area until files are fetched ──────────
    if source == "GitHub URL":
        gh_code = _render_github_main()
        if not gh_code:
            return  # Browser is showing; pipeline not ready yet
        code = gh_code  # Files fetched — fall through to pipeline

    # ── Guard ──────────────────────────────────────────────────────────────────
    if not code.strip():
        st.info("Choose a code source in the sidebar and run the pipeline.")
        return

    # ── Run or restore ─────────────────────────────────────────────────────────
    if not run:
        if "fmea_result" in st.session_state:
            result = st.session_state["fmea_result"]
        else:
            st.info("Click **Run FMEA pipeline** in the sidebar to analyze the code.")
            return
    else:
        with st.spinner("Running pipeline…"):
            try:
                result = run_fmea(
                    code,
                    max_failure_modes=DEFAULT_MAX_FAILURE_MODES,
                    force_rerun=force_rerun,
                    workspace=active_ws,
                )
            except RuntimeError as e:
                st.error(str(e))
                st.stop()
            except Exception as e:
                st.error(f"Pipeline failed: {e}")
                st.stop()
        st.session_state["fmea_result"] = result
        st.session_state["_fmea_last_code"] = code
        st.session_state["filter_priority"] = "All"
        st.session_state["filter_rpn_min"] = 0
        st.session_state["filter_rpn_max"] = 1000
        st.session_state["selected_risk"] = None
        st.session_state["nav_page"] = "Portfolio Overview"

    result = st.session_state["fmea_result"]
    if st.session_state.get("_fmea_last_code") != code:
        st.warning("Source code changed since last run. Click **Run FMEA pipeline** again to refresh.")

    # ── Cache / fingerprint status banner ──────────────────────────────────────
    fingerprint = result.get("fingerprint", "")
    from_cache = result.get("from_cache", False)
    cached_at = result.get("cached_at", "")
    if from_cache:
        st.success(
            f"📦 **Loaded from cache** (fingerprint `{fingerprint}`, "
            f"analyzed {cached_at[:10] if cached_at else 'previously'}). "
            "Tick **Force re-run** to re-analyze."
        )
    else:
        st.info(f"🔄 **Fresh analysis** — fingerprint `{fingerprint}`")

    # Drift alert banner
    drift_alerts = result.get("drift_alerts", [])
    for alert in drift_alerts:
        st.warning(f"📉 **Score drift:** {alert}")

    # ── Unpack result ──────────────────────────────────────────────────────────
    ctx = result["context"]
    failures = result["failures"]
    risks = result["risks"]
    remediations = result["remediations"]
    controls = result.get("controls", [])
    linkage = result.get("scenario_linkage")
    validations = result.get("validations", [])
    memory_stats = result.get("memory_stats", {})

    if linkage is None:
        st.warning("This result predates scenario linkage. Click **Run FMEA pipeline** again.")
        linkage = ScenarioLinkageReport(explanations=[], cross_cutting_themes="")

    # ── Quick filter bar ───────────────────────────────────────────────────────
    page = st.session_state["nav_page"]
    if page not in ("Portfolio Overview", "System Context", "Eval Report", "Auto-Remediation"):
        _render_quick_filters(risks)

    # ── Dispatcher ────────────────────────────────────────────────────────────
    if page == "Portfolio Overview":
        render_portfolio_overview(ctx, failures, risks, remediations, validations, memory_stats, result)
    elif page == "Risk Matrix":
        render_risk_matrix(risks, remediations, failures, validations, result=result)
    elif page == "Risk Deep Dive":
        render_risk_deep_dive(risks, remediations, failures, controls, linkage, validations)
    elif page == "Mitigation Plans":
        render_mitigation_plans(risks, remediations, failures)
    elif page == "System Context":
        render_system_context(ctx, failures, linkage)
    elif page == "Eval Report":
        render_eval_report(result)
    elif page == "Auto-Remediation":
        render_auto_remediation(result)


if __name__ == "__main__":
    main()
