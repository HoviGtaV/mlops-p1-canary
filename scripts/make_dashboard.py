"""Generates monitoring/grafana/dashboards/canary.json (run: python scripts/make_dashboard.py)."""
import json
import pathlib

DS = {"type": "prometheus", "uid": "prometheus"}
_id = [0]


def nid():
    _id[0] += 1
    return _id[0]


def variant_colors():
    return [
        {"matcher": {"id": "byName", "options": "v1 (A)"},
         "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "blue"}}]},
        {"matcher": {"id": "byName", "options": "v2 (B)"},
         "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "orange"}}]},
    ]


def ts(title, targets, x, y, w=8, h=8, unit=None, desc="", overrides=None, log=False,
       min_=None, max_=None, thresholds=None):
    defaults = {"custom": {"lineWidth": 2, "fillOpacity": 8, "showPoints": "never",
                           "spanNulls": True}}
    if unit:
        defaults["unit"] = unit
    if log:
        defaults["custom"]["scaleDistribution"] = {"type": "log", "log": 10}
    if min_ is not None:
        defaults["min"] = min_
    if max_ is not None:
        defaults["max"] = max_
    if thresholds:
        defaults["thresholds"] = {"mode": "absolute", "steps": thresholds}
        defaults["custom"]["thresholdsStyle"] = {"mode": "line+area"}
    return {
        "id": nid(), "type": "timeseries", "title": title, "description": desc,
        "datasource": DS, "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"},
                    "tooltip": {"mode": "multi"}},
        "targets": [{"refId": chr(65 + i), "datasource": DS, "expr": e, "legendFormat": l}
                    for i, (e, l) in enumerate(targets)],
    }


def stat(title, expr, x, y, w=4, h=5, unit=None, mappings=None, desc="", decimals=None):
    defaults = {"color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": [{"color": "text", "value": None}]}}
    if unit:
        defaults["unit"] = unit
    if mappings:
        defaults["mappings"] = mappings
    if decimals is not None:
        defaults["decimals"] = decimals
    return {
        "id": nid(), "type": "stat", "title": title, "description": desc, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "background",
                    "graphMode": "none", "textMode": "value"},
        "targets": [{"refId": "A", "datasource": DS, "expr": expr}],
    }


def by_variant(expr_tpl):
    return [(expr_tpl.format(v="a"), "v1 (A)"), (expr_tpl.format(v="b"), "v2 (B)")]


state_map = [{"type": "value", "options": {
    "0": {"text": "IDLE", "color": "text"},
    "1": {"text": "ROLLING OUT", "color": "blue"},
    "2": {"text": "PASSED", "color": "green"},
    "3": {"text": "ROLLED BACK", "color": "red"},
    "4": {"text": "ABORTED", "color": "purple"}}}]

panels = [
    stat("Traffic on v2 (canary weight)", "router_canary_weight", 0, 0, unit="percentunit",
         desc="Share of users routed to variant B (v2)."),
    stat("Rollout state", "canary_rollout_state", 4, 0, mappings=state_map),
    stat("v2 requests in current step", "canary_v2_requests_in_step", 8, 0, decimals=0),
    ts("Canary weight over time", [("router_canary_weight", "weight on v2")], 12, 0, w=12, h=5,
       unit="percentunit", min_=0, max_=1),

    ts("Requests per second", by_variant(
        'sum(rate(router_requests_total{{variant="{v}"}}[30s]))'), 0, 5,
       unit="reqps", overrides=variant_colors()),
    ts("Error rate", by_variant(
        'sum(rate(router_requests_total{{variant="{v}",outcome="error"}}[1m])) / '
        'sum(rate(router_requests_total{{variant="{v}"}}[1m]))'), 8, 5,
       unit="percentunit", overrides=variant_colors(), min_=0,
       desc="HTTP 5xx and timeouts seen by the router."),
    ts("p99 latency (end to end)", by_variant(
        'histogram_quantile(0.99, sum by (le) (rate(router_request_seconds_bucket{{variant="{v}"}}[1m])))'),
       16, 5, unit="s", overrides=variant_colors()),

    ts("Mean predicted risk", by_variant(
        'sum(rate(model_score_sum{{variant="{v}"}}[1m])) / sum(rate(model_score_count{{variant="{v}"}}[1m]))'),
       0, 13, unit="percentunit", overrides=variant_colors(),
       desc="The silent schema bug shows up here: v2 keeps answering 200 but its scores shift."),
    ts("Share of high-risk scores (> 0.20)", by_variant(
        '1 - sum(rate(model_score_bucket{{variant="{v}",le="0.2"}}[1m])) / '
        'sum(rate(model_score_count{{variant="{v}"}}[1m]))'),
       8, 13, unit="percentunit", overrides=variant_colors(), min_=0),
    ts("Guardrail: score PSI (v2 vs v1)",
       [("canary_guardrail_value{guardrail=\"score_psi\"}", "PSI"),
        ("canary_guardrail_threshold{guardrail=\"score_psi\"}", "threshold")], 16, 13, min_=0),

    ts("Guardrail: error-rate z-test p-value",
       [("clamp_min(canary_error_pvalue, 1e-12)", "p-value"), ("vector(0.001)", "alpha = 0.001")],
       0, 21, log=True, unit="sci",
       desc="One-sided two-proportion z-test, v2 vs v1. Breach when p < alpha, the gap >= 1 point "
            "and an exact binomial test agrees. Floored at 1e-12 for display."),
    ts("Guardrail: p99 latency v2 vs limit",
       [("canary_guardrail_value{guardrail=\"latency_p99\"}", "v2 p99"),
        ("canary_guardrail_threshold{guardrail=\"latency_p99\"}", "limit")], 8, 21, unit="s"),
    ts("Guardrail breaches (1 = breached at last check)",
       [("canary_guardrail_breach", "{{guardrail}}")], 16, 21, min_=0, max_=1),

    ts("Injected failure flags on v2",
       [('model_injected_flag{variant="b"}', "{{flag}}")], 0, 29, w=12, h=6),
    ts("Errors by kind", [('sum by (variant, kind) (rate(model_errors_total[1m]))',
                           "{{variant}} {{kind}}")], 12, 29, w=12, h=6, unit="reqps"),
]

dashboard = {
    "uid": "p1-canary", "title": "P1 - Canary rollout (readmission model)",
    "tags": ["mlops", "canary"], "timezone": "browser", "schemaVersion": 39,
    "refresh": "5s", "time": {"from": "now-15m", "to": "now"},
    "panels": panels, "editable": True,
}

out = pathlib.Path(__file__).resolve().parents[1] / "monitoring/grafana/dashboards/canary.json"
out.write_text(json.dumps(dashboard, indent=2))
print("wrote", out)
