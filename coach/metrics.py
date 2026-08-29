#!/usr/bin/env python3
"""Calcula métricas de treino a partir da base de dados do garmin-givemydata.

Tudo o que é número é calculado aqui, em SQL e Python. O modelo de linguagem
nunca vê aritmética por fazer — recebe apenas resultados prontos. Um modelo de
4B erra contas com frequência, e métricas de saúde inventadas seriam pior do
que não ter métrica nenhuma.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

DB = Path(os.environ.get("GARMIN_DB", "/data/garmin.db"))
SCHEMA = Path(__file__).with_name("schema.yaml")

# Constantes de periodização clássicas (Coggan): CTL a 42 dias, ATL a 7.
CTL_TC, ATL_TC = 42, 7


def connect() -> sqlite3.Connection:
    if not DB.exists():
        sys.exit(f"Base de dados não encontrada em {DB}. Correr a sincronização primeiro.")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def tables(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def columns(con, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def resolve(con, spec: dict) -> tuple[str, dict] | None:
    """Escolhe a primeira tabela e as primeiras colunas que existam de facto."""
    available = tables(con)
    table = next((t for t in spec["table"] if t in available), None)
    if not table:
        return None
    cols = columns(con, table)
    mapping = {}
    for field, candidates in spec.items():
        if field == "table":
            continue
        hit = next((c for c in candidates if c in cols), None)
        if hit:
            mapping[field] = hit
    return (table, mapping) if "date" in mapping else None


def discover(con) -> None:
    """Imprime o esquema real, para ajustar o schema.yaml."""
    for t in sorted(tables(con)):
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"\n{t}  ({n} linhas)")
        for c in con.execute(f"PRAGMA table_info({t})"):
            print(f"    {c[1]:<34} {c[2]}")


def as_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 1e11 else value).date()
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def trimp(duration_s, avg_hr, rest_hr=55, max_hr=190) -> float:
    """Carga aproximada quando a Garmin não fornece training load.

    Banister TRIMP com o factor exponencial masculino. É uma aproximação; a
    carga da própria Garmin é sempre preferida quando existe.
    """
    if not duration_s:
        return 0.0
    minutes = duration_s / 60
    if not avg_hr or avg_hr <= rest_hr:
        return minutes * 0.5
    reserve = max(0.0, min(1.0, (avg_hr - rest_hr) / max(1, max_hr - rest_hr)))
    return minutes * reserve * 0.64 * math.exp(1.92 * reserve)


def load_activities(con, spec, since: date) -> list[dict]:
    resolved = resolve(con, spec)
    if not resolved:
        return []
    table, m = resolved
    fields = ", ".join(f"{col} AS {name}" for name, col in m.items())
    rows = con.execute(f"SELECT {fields} FROM {table}").fetchall()

    out = []
    for r in rows:
        d = as_date(r["date"])
        if not d or d < since:
            continue
        load = r["training_load"] if "training_load" in r.keys() else None
        if not load:
            load = trimp(
                r["duration_s"] if "duration_s" in r.keys() else None,
                r["avg_hr"] if "avg_hr" in r.keys() else None,
            )
        out.append({
            "date": d,
            "sport": (r["sport"] if "sport" in r.keys() else "unknown") or "unknown",
            "duration_s": (r["duration_s"] if "duration_s" in r.keys() else 0) or 0,
            "distance_m": (r["distance_m"] if "distance_m" in r.keys() else 0) or 0,
            "load": float(load or 0),
        })
    return sorted(out, key=lambda a: a["date"])


def daily_series(con, spec, field: str, since: date) -> dict[date, float]:
    resolved = resolve(con, spec)
    if not resolved:
        return {}
    table, m = resolved
    if field not in m:
        return {}
    rows = con.execute(f"SELECT {m['date']} AS d, {m[field]} AS v FROM {table}").fetchall()
    series = {}
    for r in rows:
        d = as_date(r["d"])
        if d and d >= since and r["v"] is not None:
            series[d] = float(r["v"])
    return series


def ewma_load(acts: list[dict], today: date, days: int, tc: int) -> float:
    """Média móvel exponencial da carga diária, ao estilo CTL/ATL."""
    by_day: dict[date, float] = {}
    for a in acts:
        by_day[a["date"]] = by_day.get(a["date"], 0.0) + a["load"]

    value, alpha = 0.0, 2 / (tc + 1)
    start = today - timedelta(days=days)
    d = start
    while d <= today:
        value = by_day.get(d, 0.0) * alpha + value * (1 - alpha)
        d += timedelta(days=1)
    return value


def mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def build(con) -> dict:
    spec = yaml.safe_load(SCHEMA.read_text())
    today = date.today()
    window = today - timedelta(days=180)

    acts = load_activities(con, spec["activities"], window)
    rhr = daily_series(con, spec["daily"], "resting_hr", window)
    sleep_h = daily_series(con, spec["sleep"], "duration_s", window)
    sleep_score = daily_series(con, spec["sleep"], "score", window)
    hrv = daily_series(con, spec["hrv"], "last_night", window)

    ctl = ewma_load(acts, today, 90, CTL_TC)
    atl = ewma_load(acts, today, 28, ATL_TC)

    def recent(series, n):
        return [series[today - timedelta(days=i)] for i in range(n) if today - timedelta(days=i) in series]

    last7 = [a for a in acts if a["date"] >= today - timedelta(days=7)]
    last28 = [a for a in acts if a["date"] >= today - timedelta(days=28)]

    hard = [a for a in acts if a["load"] >= 100]
    days_since_hard = (today - hard[-1]["date"]).days if hard else None

    rhr7, rhr28 = mean(recent(rhr, 7)), mean(recent(rhr, 28))
    hrv7, hrv28 = mean(recent(hrv, 7)), mean(recent(hrv, 28))

    by_sport: dict[str, dict] = {}
    for a in last28:
        s = by_sport.setdefault(a["sport"], {"sessions": 0, "minutes": 0.0, "km": 0.0})
        s["sessions"] += 1
        s["minutes"] += a["duration_s"] / 60
        s["km"] += a["distance_m"] / 1000
    for s in by_sport.values():
        s["minutes"] = round(s["minutes"])
        s["km"] = round(s["km"], 1)

    return {
        "generated": today.isoformat(),
        "load": {
            "ctl": round(ctl, 1),
            "atl": round(atl, 1),
            "tsb": round(ctl - atl, 1),
            "sessions_7d": len(last7),
            "minutes_7d": round(sum(a["duration_s"] for a in last7) / 60),
            "minutes_28d": round(sum(a["duration_s"] for a in last28) / 60),
            "days_since_hard": days_since_hard,
        },
        "recovery": {
            "rhr_7d": rhr7,
            "rhr_28d": rhr28,
            "rhr_delta": round(rhr7 - rhr28, 1) if rhr7 and rhr28 else None,
            "hrv_7d": hrv7,
            "hrv_28d": hrv28,
            "hrv_delta_pct": round((hrv7 - hrv28) / hrv28 * 100, 1) if hrv7 and hrv28 else None,
            "sleep_h_7d": round(mean(recent(sleep_h, 7)) / 3600, 1) if recent(sleep_h, 7) else None,
            "sleep_score_7d": mean(recent(sleep_score, 7)),
        },
        "by_sport_28d": by_sport,
        "coverage": {
            "activities": len(acts),
            "has_rhr": bool(rhr),
            "has_hrv": bool(hrv),
            "has_sleep": bool(sleep_h),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true", help="imprimir o esquema real da base de dados")
    args = ap.parse_args()

    con = connect()
    if args.discover:
        discover(con)
        return
    print(json.dumps(build(con), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
