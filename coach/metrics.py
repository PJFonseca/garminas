#!/usr/bin/env python3
"""Calcula métricas de treino a partir da base de dados do garmin-givemydata.

Tudo o que é número é calculado aqui, em SQL e Python. O modelo de linguagem
nunca vê aritmética por fazer, recebe apenas resultados prontos. Um modelo de
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

DATA_DIR = Path(os.environ.get("GARMIN_DATA_DIR", "/data"))
DB = Path(os.environ.get("GARMIN_DB") or DATA_DIR / "garmin.db")
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
            "avg_hr": (r["avg_hr"] if "avg_hr" in r.keys() else None),
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


def summarise_window(acts: list[dict], today: date, days: int) -> dict:
    """Resumo fechado de uma janela. Existe para que o modelo não tenha de
    contar nada: recebe os totais já feitos e limita-se a citá-los."""
    block = [a for a in acts if a["date"] >= today - timedelta(days=days - 1)]
    minutes = [a["duration_s"] / 60 for a in block]
    return {
        "sessions": len(block),
        "minutes": round(sum(minutes)),
        "mean_min": round(sum(minutes) / len(minutes)) if minutes else 0,
        "longest_min": round(max(minutes)) if minutes else 0,
        "shortest_min": round(min(minutes)) if minutes else 0,
        "km": round(sum(a["distance_m"] for a in block) / 1000, 1),
        "hard": len([a for a in block if a["load"] >= 100]),
        "rest_days": days - len({a["date"] for a in block}),
    }


def recent_sessions(acts: list[dict], n: int = 12) -> list[dict]:
    """As últimas n sessões, da mais recente para a mais antiga."""
    return [{
        "date": a["date"].isoformat(),
        "sport": a["sport"],
        "minutes": round(a["duration_s"] / 60),
        "km": round(a["distance_m"] / 1000, 1),
        "avg_hr": round(a["avg_hr"]) if a["avg_hr"] else None,
        "load": round(a["load"]),
    } for a in reversed(acts[-n:])]


def month_review(acts: list[dict], today: date) -> dict:
    """Retrato dos últimos 28 dias, em quatro semanas fechadas.

    A taxa de progressão compara a semana mais recente com a média das três
    anteriores. Acima de 1.3 é o território onde as lesões por excesso
    aparecem; abaixo de 0.8 há perda de forma.
    """
    weeks = []
    for w in range(4):
        end = today - timedelta(days=7 * w)
        start = end - timedelta(days=6)
        block = [a for a in acts if start <= a["date"] <= end]
        weeks.append({
            "start": start.isoformat(),
            "end": end.isoformat(),
            "sessions": len(block),
            "minutes": round(sum(a["duration_s"] for a in block) / 60),
            "km": round(sum(a["distance_m"] for a in block) / 1000, 1),
            "load": round(sum(a["load"] for a in block)),
        })

    loads = [w["load"] for w in weeks]
    previous = [w["load"] for w in weeks[1:] if w["load"] > 0]
    ramp = round(weeks[0]["load"] / (sum(previous) / len(previous)), 2) if previous else None

    last28 = [a for a in acts if a["date"] >= today - timedelta(days=27)]
    runs = [a for a in last28 if a["distance_m"] > 0]
    return {
        "weeks": weeks,
        "ramp": ramp,
        "mean_week_load": round(sum(loads) / len(loads)) if loads else 0,
        "mean_week_minutes": round(sum(w["minutes"] for w in weeks) / len(weeks)) if weeks else 0,
        # Só as semanas com treino. Uma semana a zero é uma pausa ou uma falha
        # de dados; em qualquer dos casos não deve definir o tecto da próxima
        # quinzena, senão uma paragem passa a ser o novo normal.
        "mean_week_minutes_active": (
            round(sum(w["minutes"] for w in weeks if w["sessions"])
                  / len([w for w in weeks if w["sessions"]]))
            if any(w["sessions"] for w in weeks) else 0),
        "hard_sessions": len([a for a in last28 if a["load"] >= 100]),
        "rest_days": 28 - len({a["date"] for a in last28}),
        "longest_km": round(max((a["distance_m"] for a in runs), default=0) / 1000, 1),
        "longest_min": round(max((a["duration_s"] for a in last28), default=0) / 60),
        "total_load": round(sum(a["load"] for a in last28)),
    }


def percentil(valores: list[float], q: float) -> float:
    ordenados = sorted(valores)
    if not ordenados:
        return 0.0
    i = min(len(ordenados) - 1, max(0, round(q * (len(ordenados) - 1))))
    return ordenados[i]


def paces(acts: list[dict]) -> dict:
    """Velocidades de passadeira tiradas do próprio historial.

    Recomendar "8 km/h" a alguém sem olhar para o que essa pessoa corre é um
    palpite. Aqui ajusta-se uma reta entre frequência cardíaca média e
    velocidade, e lê-se essa reta nas frequências que a pessoa costuma ter em
    esforço fácil e em esforço forte. O resultado nunca sai do intervalo que
    ela já correu.
    """
    corridas = [(a["avg_hr"], (a["distance_m"] / 1000) / (a["duration_s"] / 3600))
                for a in acts
                if a["avg_hr"] and a["distance_m"] > 500 and a["duration_s"] > 300
                and "walk" not in a["sport"]]
    caminhadas = [(a["distance_m"] / 1000) / (a["duration_s"] / 3600)
                  for a in acts
                  if "walk" in a["sport"] and a["distance_m"] > 500 and a["duration_s"] > 300]

    if len(corridas) < 4:
        return {"has_data": False}

    hrs = [h for h, _ in corridas]
    kmhs = [v for _, v in corridas]
    n = len(corridas)
    mh, mv = sum(hrs) / n, sum(kmhs) / n
    denom = sum((h - mh) ** 2 for h in hrs)
    slope = sum((h - mh) * (v - mv) for h, v in corridas) / denom if denom else 0.0

    baixo, alto = min(kmhs), max(kmhs)

    def em(hr_alvo: float) -> float:
        return round(min(alto, max(baixo, mv + slope * (hr_alvo - mh))) * 2) / 2

    return {
        "has_data": True,
        "facil": em(percentil(hrs, 0.35)),
        "forte": em(percentil(hrs, 0.9)),
        "tempo": round((em(percentil(hrs, 0.35)) + em(percentil(hrs, 0.9))) / 2 * 2) / 2,
        "caminhada": round((sorted(caminhadas)[len(caminhadas) // 2] if caminhadas else 5.5) * 2) / 2,
        "sessoes": n,
    }


def body(con, spec, today: date) -> dict:
    """Peso e composição corporal, com a tendência recente.

    A Garmin devolve gramas quando a balança é dela e quilos quando o valor
    entra à mão, por isso qualquer coisa acima de 1000 é convertida.

    A frescura do dado importa tanto como o valor: uma pesagem de há dois
    meses não sustenta uma tendência, e fingir que sustenta seria pior do que
    não mostrar nada.
    """
    serie = daily_series(con, spec, "weight", today - timedelta(days=400))
    if not serie:
        return {"has_data": False}

    kg = {d: (v / 1000 if v > 1000 else v) for d, v in serie.items()}
    dias = sorted(kg)
    ultimo = dias[-1]

    # Inclinação por mínimos quadrados sobre os últimos 90 dias com dados.
    recentes = [(d, kg[d]) for d in dias if (ultimo - d).days <= 90]
    kg_semana = None
    if len(recentes) >= 3:
        xs = [(d - recentes[0][0]).days for d, _ in recentes]
        ys = [v for _, v in recentes]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        denom = sum((x - mx) ** 2 for x in xs)
        if denom:
            kg_semana = round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom * 7, 3)

    outros = {campo: daily_series(con, spec, campo, today - timedelta(days=400))
              for campo in ("bmi", "body_fat", "muscle_mass")}

    def ultimo_de(campo):
        s = outros.get(campo) or {}
        if not s:
            return None
        v = s[max(s)]
        return round(v / 1000 if campo == "muscle_mass" and v > 1000 else v, 1)

    return {
        "has_data": True,
        "kg": round(kg[ultimo], 1),
        "date": ultimo.isoformat(),
        "days_old": (today - ultimo).days,
        "kg_per_week": kg_semana,
        "pontos_90d": len(recentes),
        "bmi": ultimo_de("bmi"),
        "body_fat": ultimo_de("body_fat"),
        "muscle_kg": ultimo_de("muscle_mass"),
    }


def sessao_recente(acts: list[dict], ritmos: dict, today: date, ln: str = "en") -> dict:
    """Como correu a última sessão, comparada com as anteriores.

    Tudo o que é comparação fica feito aqui. O modelo recebe frases prontas e
    limita-se a juntá-las; já se viu o que acontece quando lhe pedem para
    comparar números sozinho.
    """
    if not acts:
        return {"has_data": False}

    ultima = acts[-1]
    if not ultima["duration_s"]:
        return {"has_data": False}

    minutos = ultima["duration_s"] / 60
    kmh = (ultima["distance_m"] / 1000) / (ultima["duration_s"] / 3600) if ultima["distance_m"] else 0

    anteriores = [a for a in acts[:-1] if a["date"] >= today - timedelta(days=56)]
    com_ritmo = [((a["distance_m"] / 1000) / (a["duration_s"] / 3600))
                 for a in anteriores if a["distance_m"] and a["duration_s"]]

    from language import t as _t

    notas = []
    if kmh and com_ritmo:
        mais_rapidas = [v for v in com_ritmo if v > kmh]
        if not mais_rapidas:
            notas.append(_t("s.fastest", ln))
        elif len(mais_rapidas) == 1:
            notas.append(_t("s.one_faster", ln))
        elif len(mais_rapidas) == 2:
            notas.append(_t("s.few_faster", ln, n=2))
        media = sum(com_ritmo) / len(com_ritmo)
        if kmh > media * 1.08:
            notas.append(_t("s.above_avg", ln, kmh=f"{kmh:.1f}", media=f"{media:.1f}"))
        elif kmh < media * 0.92:
            notas.append(_t("s.below_avg", ln, kmh=f"{kmh:.1f}", media=f"{media:.1f}"))

    duracoes = [a["duration_s"] / 60 for a in anteriores]
    if duracoes:
        media_min = sum(duracoes) / len(duracoes)
        if minutos > media_min * 1.25:
            notas.append(_t("s.longer", ln, min=round(minutos), media=round(media_min)))
        elif minutos < media_min * 0.75:
            notas.append(_t("s.shorter", ln, min=round(minutos), media=round(media_min)))

    if ultima["avg_hr"] and ritmos.get("has_data") and kmh:
        if kmh >= ritmos["forte"] - 0.2:
            notas.append(_t("s.hard_ground", ln, kmh=f"{kmh:.1f}"))
        elif kmh <= ritmos["facil"] + 0.2:
            notas.append(_t("s.easy_ground", ln, kmh=f"{kmh:.1f}"))

    hrs = [a["avg_hr"] for a in anteriores if a["avg_hr"]]
    if ultima["avg_hr"] and hrs:
        media_hr = sum(hrs) / len(hrs)
        if ultima["avg_hr"] > media_hr + 8:
            notas.append(_t("s.hr_high", ln, hr=round(ultima["avg_hr"]), media=round(media_hr)))
        elif ultima["avg_hr"] < media_hr - 8:
            notas.append(_t("s.hr_low", ln, hr=round(ultima["avg_hr"]), media=round(media_hr)))

    # O veredicto, para a pessoa não ter de o deduzir dos números. Uma sessão
    # não é boa ou má em absoluto: é boa se serviu para alguma coisa.
    rapida = bool(kmh and com_ritmo and kmh > (sum(com_ritmo) / len(com_ritmo)) * 1.08)
    longa = bool(duracoes and minutos > (sum(duracoes) / len(duracoes)) * 1.25)
    facil = bool(kmh and ritmos.get("has_data") and kmh <= ritmos["facil"] + 0.2)

    if rapida and longa:
        estado, veredicto = "forte", _t("v.session.strong_long", ln)
    elif rapida:
        estado, veredicto = "forte", _t("v.session.strong", ln)
    elif longa:
        estado, veredicto = "boa", _t("v.session.volume", ln)
    elif facil:
        estado, veredicto = "base", _t("v.session.base", ln)
    else:
        estado, veredicto = "normal", _t("v.session.normal", ln)

    return {
        "has_data": True,
        "estado": estado,
        "veredicto": veredicto,
        "date": ultima["date"].isoformat(),
        "hoje": ultima["date"] == today,
        "sport": ultima["sport"],
        "minutes": round(minutos),
        "km": round(ultima["distance_m"] / 1000, 1),
        "kmh": round(kmh, 1) if kmh else None,
        "avg_hr": round(ultima["avg_hr"]) if ultima["avg_hr"] else None,
        "load": round(ultima["load"]),
        "notas": notas,
    }


def build(con, ln: str = "en") -> dict:
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
    # A mesma média há quatro semanas, para se saber se a forma sobe ou desce.
    # O valor absoluto do CTL não diz nada sem saber para onde vai.
    ctl_prev = ewma_load(acts, today - timedelta(days=28), 90, CTL_TC)

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
            "ctl_28d_ago": round(ctl_prev, 1),
            "ctl_delta": round(ctl - ctl_prev, 1),
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
        "recent": recent_sessions(acts),
        "body": body(con, spec.get("weight", {"table": []}), today),
        "paces": paces(acts),
        "sessao": sessao_recente(acts, paces(acts), today, ln),
        "windows": {"7d": summarise_window(acts, today, 7),
                    "14d": summarise_window(acts, today, 14)},
        "month": month_review(acts, today),
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
