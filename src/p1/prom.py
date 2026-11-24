"""Tiny Prometheus HTTP API client used by the rollout controller and analyses."""
from __future__ import annotations

import math
from collections import defaultdict

import httpx


class Prometheus:
    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.client = httpx.Client(timeout=10)

    def instant(self, query: str, t: float | None = None) -> list[tuple[dict, float]]:
        params = {"query": query}
        if t is not None:
            params["time"] = f"{t:.3f}"
        r = self.client.get(self.url + "/api/v1/query", params=params)
        r.raise_for_status()
        data = r.json()["data"]["result"]
        return [(item["metric"], float(item["value"][1])) for item in data]

    def range(self, query: str, start: float, end: float, step: float) -> list[tuple[dict, list]]:
        r = self.client.get(self.url + "/api/v1/query_range",
                            params={"query": query, "start": start, "end": end, "step": step})
        r.raise_for_status()
        return [(item["metric"], [(float(t), float(v)) for t, v in item["values"]])
                for item in r.json()["data"]["result"]]

    def delta(self, query: str, t0: float, t1: float, keys: tuple[str, ...]) -> dict:
        """Increase of summed counters between t0 and t1, keyed by label tuple.

        Uses two instant queries and a subtraction (exact for counters that did
        not reset), instead of PromQL increase() which extrapolates.
        """
        before = {tuple(m.get(k, "") for k in keys): v for m, v in self.instant(query, t0)}
        after = {tuple(m.get(k, "") for k in keys): v for m, v in self.instant(query, t1)}
        out = defaultdict(float)
        for key, v in after.items():
            out[key] = max(v - before.get(key, 0.0), 0.0)
        return out


def histogram_from_delta(delta: dict, variant: str) -> tuple[list[float], list[float]]:
    """{(variant, le): cumulative count} -> (finite upper bounds, cumulative counts incl. +Inf)."""
    rows = [(le, c) for (v, le), c in delta.items() if v == variant]
    finite = sorted((float(le), c) for le, c in rows if le != "+Inf")
    inf = [c for le, c in rows if le == "+Inf"]
    bounds = [b for b, _ in finite]
    cum = [c for _, c in finite] + [inf[0] if inf else (finite[-1][1] if finite else 0.0)]
    return bounds, cum


def cumulative_to_bins(cum: list[float]) -> list[float]:
    out, prev = [], 0.0
    for c in cum:
        out.append(max(c - prev, 0.0))
        prev = c
    return out


def is_nan(x) -> bool:
    return isinstance(x, float) and math.isnan(x)
