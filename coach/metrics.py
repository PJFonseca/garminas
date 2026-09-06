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
            "max_hr": (r["max_hr"] if "max_hr" in r.keys() else None),
            "id": (r["id"] if "id" in r.keys() else None),
            "aerobic_te": (r["aerobic_te"] if "aerobic_te" in r.keys() else None),
            "anaerobic_te": (r["anaerobic_te"] if "anaerobic_te" in r.keys() else None),
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
        "id": a.get("id"),
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


def detalhe_sessao(con, activity_id) -> dict:
    """Parciais, zonas cardíacas e tempo, para a sessão que acabou de ser feita.

    Isto vive numas tabelas que o relatório nunca tinha aberto: activity_splits
    traz um registo por quilómetro, activity_hr_zones traz os segundos em cada
    zona com os respetivos limites, e activity_weather traz a temperatura, que
    explica bastante de um ritmo mau num dia quente.
    """
    if activity_id is None:
        return {}
    saida: dict = {}

    try:
        linhas = con.execute(
            "SELECT split_number, distance_meters, duration_seconds, average_hr, max_hr,"
            " avg_cadence, calories FROM activity_splits WHERE activity_id = ?"
            " ORDER BY split_number", (activity_id,)).fetchall()
    except sqlite3.Error:
        linhas = []
    parciais = []
    for r in linhas:
        metros, segundos = r[1] or 0, r[2] or 0
        if metros < 200 or not segundos:
            continue                     # o resto do último quilómetro não conta
        por_km = segundos / (metros / 1000)
        parciais.append({
            "n": r[0], "km": round(metros / 1000, 2),
            "seconds": round(segundos),
            # Segundos por quilómetro, não a duração bruta. O último parcial é
            # quase sempre uma fração de quilómetro: comparar durações fazia o
            # mais lento passar por mais rápido só por ser mais curto.
            "pace_seconds": round(por_km),
            "pace": f"{int(por_km // 60)}:{int(por_km % 60):02d}",
            "kmh": round((metros / 1000) / (segundos / 3600), 1),
            "hr": round(r[3]) if r[3] else None,
            "max_hr": round(r[4]) if r[4] else None,
            "cadence": round(r[5]) if r[5] else None,
        })
    if parciais:
        saida["splits"] = parciais

    try:
        z = con.execute(
            "SELECT zone1_seconds, zone2_seconds, zone3_seconds, zone4_seconds,"
            " zone5_seconds, raw_json FROM activity_hr_zones WHERE activity_id = ?",
            (activity_id,)).fetchone()
    except sqlite3.Error:
        z = None
    if z:
        limites = {}
        try:
            for bloco in json.loads(z[5] or "[]"):
                limites[bloco.get("zoneNumber")] = bloco.get("zoneLowBoundary")
        except (json.JSONDecodeError, TypeError):
            pass
        zonas = [{"n": i + 1, "seconds": round(z[i] or 0), "low": limites.get(i + 1)}
                 for i in range(5)]
        if sum(x["seconds"] for x in zonas):
            saida["zones"] = zonas

    try:
        w = con.execute("SELECT temperature, humidity FROM activity_weather"
                        " WHERE activity_id = ?", (activity_id,)).fetchone()
    except sqlite3.Error:
        w = None
    if w and w[0] is not None:
        saida["weather"] = {"temp": round(w[0]), "humidity": round(w[1]) if w[1] else None}
    return saida


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
        "max_hr": round(ultima["max_hr"]) if ultima.get("max_hr") else None,
        "aerobic_te": round(ultima["aerobic_te"], 1) if ultima.get("aerobic_te") else None,
        "anaerobic_te": round(ultima["anaerobic_te"], 1) if ultima.get("anaerobic_te") else None,
        "id": ultima.get("id"),
    }


def eficiencia(acts: list[dict]) -> dict:
    """Estás a melhorar? Ritmo à mesma frequência cardíaca.

    O ritmo sozinho não responde: correr mais depressa com o coração a 170 não
    é melhorar, é esforçar-se mais. O que mede progresso é a velocidade que se
    consegue com o mesmo esforço, e é isso que este índice é, metros por minuto
    a dividir pela frequência cardíaca média.

    Não serve para tudo: calor, passadeira contra rua, e uma FC média puxada
    por um único tiro deslocam o valor. Por isso compara-se a média de várias
    sessões, nunca uma só.
    """
    validos = [
        (a["date"], (a["distance_m"] / (a["duration_s"] / 60)) / a["avg_hr"])
        for a in acts
        if a["avg_hr"] and a["avg_hr"] > 80 and a["distance_m"] > 1000 and a["duration_s"] > 600
    ]
    if len(validos) < 8:
        return {"has_data": False}

    recentes = [v for _, v in validos[-5:]]
    anteriores = [v for _, v in validos[-25:-5]]
    if not anteriores:
        return {"has_data": False}

    agora = sum(recentes) / len(recentes)
    antes = sum(anteriores) / len(anteriores)
    pct = (agora / antes - 1) * 100

    return {
        "has_data": True,
        "now": round(agora, 3),
        "before": round(antes, 3),
        "pct": round(pct, 1),
        "n_recent": len(recentes),
        "n_before": len(anteriores),
        "series": [{"date": d.isoformat(), "ef": round(v, 3)} for d, v in validos[-20:]],
    }


def series_bem_estar(con, today: date, dias: int = 56) -> dict:
    """Sono, stress e Body Battery, dia a dia.

    O contexto_extra traz o último valor de cada um, que responde "como está
    hoje" e nunca "para onde vai". São três medidas em escalas diferentes,
    horas contra dois índices de 0 a 100, por isso saem em três gráficos
    pequenos e nunca com dois eixos no mesmo.
    """
    desde = (today - timedelta(days=dias)).isoformat()

    def puxa(sql):
        try:
            return [{"date": r[0], "v": round(float(r[1]), 2)}
                    for r in con.execute(sql, (desde,)) if r[1] is not None]
        except sqlite3.Error:
            return []

    saida = {
        "sono": puxa("SELECT calendar_date, sleep_time_seconds/3600.0 FROM sleep"
                     " WHERE calendar_date >= ? AND sleep_time_seconds"
                     " ORDER BY calendar_date"),
        "stress": puxa("SELECT calendar_date, avg_stress FROM stress"
                       " WHERE calendar_date >= ? AND avg_stress"
                       " ORDER BY calendar_date"),
        "body_battery": puxa("SELECT calendar_date, at_wake FROM body_battery"
                             " WHERE calendar_date >= ? AND at_wake"
                             " ORDER BY calendar_date"),
    }
    saida["has_data"] = any(saida[k] for k in ("sono", "stress", "body_battery"))
    saida["desde"] = desde
    return saida


# Para cada medida da composição corporal, se subir é bom ou mau. Sem isto uma
# seta verde não significa nada: perder peso e perder músculo são a mesma
# direção no eixo e o contrário um do outro na realidade.
COMPOSICAO = [
    ("weight", "kg", False, 1),
    ("bmi", "", False, 1),
    ("body_fat", "%", False, 1),
    ("muscle_mass", "kg", True, 1),
]


def series_peso(con, spec, today: date, dias: int = 180) -> dict:
    """Peso e composição ao longo do tempo, e o que mudou em cada medida.

    O body() responde "quanto pesas agora e para onde vais". Isto responde
    outra coisa: o que subiu e o que desceu, medida a medida, para se ver de
    relance que a balança pode estar quieta enquanto a gordura e o músculo
    trocam de lugar.
    """
    limite = today - timedelta(days=dias)
    series = {campo: daily_series(con, spec, campo, limite)
              for campo, _, _, _ in COMPOSICAO}
    if not series.get("weight"):
        return {"has_data": False}

    def em_kg(campo, v):
        # A Garmin dá gramas quando a balança é dela e quilos quando o valor
        # entra à mão. A mesma regra do body(), pela mesma razão.
        return v / 1000 if campo in ("weight", "muscle_mass") and v > 1000 else v

    medidas = []
    for campo, unidade, sobe_e_bom, casas in COMPOSICAO:
        pontos = sorted((series.get(campo) or {}).items())
        if len(pontos) < 2:
            continue
        agora = em_kg(campo, pontos[-1][1])
        # A referência é a leitura mais antiga da janela, não a anterior: entre
        # duas pesagens seguidas cabe o que se bebeu ao almoço.
        antes = em_kg(campo, pontos[0][1])
        medidas.append({
            "campo": campo, "unidade": unidade, "sobe_e_bom": sobe_e_bom,
            "agora": round(agora, casas), "antes": round(antes, casas),
            "delta": round(agora - antes, casas),
            "desde": pontos[0][0].isoformat(), "n": len(pontos),
        })

    peso = sorted(series["weight"].items())
    return {
        "has_data": bool(medidas),
        "serie": [{"date": d.isoformat(), "v": round(em_kg("weight", v), 1)}
                  for d, v in peso],
        "medidas": medidas,
    }


def contexto_extra(con, today: date) -> dict:
    """Tudo o que a Garmin sabe e o relatório ainda não usava.

    Stress, Body Battery, fases do sono e as previsões de tempo de prova. A
    previsão de 5 km é a que mais interessa a quem tem isso como objetivo, e
    estava guardada sem nunca ser mostrada.
    """
    saida: dict = {}

    def uma(sql, *args):
        try:
            return con.execute(sql, args).fetchone()
        except sqlite3.Error:
            return None

    r = uma("SELECT calendar_date, avg_stress, max_stress FROM stress"
            " ORDER BY calendar_date DESC LIMIT 1")
    if r and r[1] is not None:
        saida["stress"] = {"date": r[0], "avg": round(r[1]), "max": round(r[2] or 0)}

    r = uma("SELECT calendar_date, highest, lowest, at_wake FROM body_battery"
            " ORDER BY calendar_date DESC LIMIT 1")
    if r and r[1] is not None:
        saida["body_battery"] = {"date": r[0], "high": r[1], "low": r[2], "at_wake": r[3]}

    r = uma("SELECT calendar_date, deep_sleep_seconds, light_sleep_seconds,"
            " rem_sleep_seconds, awake_sleep_seconds FROM sleep"
            " ORDER BY calendar_date DESC LIMIT 1")
    if r and r[1] is not None:
        saida["sleep_phases"] = {
            "date": r[0], "deep_min": round((r[1] or 0) / 60),
            "light_min": round((r[2] or 0) / 60), "rem_min": round((r[3] or 0) / 60),
            "awake_min": round((r[4] or 0) / 60)}

    r = uma("SELECT calendar_date, time_5k, time_10k, time_half_marathon"
            " FROM race_predictions WHERE time_5k IS NOT NULL"
            " ORDER BY calendar_date DESC LIMIT 1")
    if r:
        def mmss(s):
            s = int(s or 0)
            return f"{s // 60}:{s % 60:02d}"
        saida["race"] = {"date": r[0], "5k": mmss(r[1]), "10k": mmss(r[2]),
                         "half": mmss(r[3])}
    return saida


def forma_da_sessao(parciais: list[dict]) -> dict:
    """Que forma teve a sessão, para não se confundir estrutura com desleixo.

    Um modelo que só vê 8:10, 6:23, 6:31, 6:27, 7:14, 9:15 chama àquilo ritmo
    inconsistente. Mas o primeiro quilómetro é aquecimento e o último é
    arrefecimento, e o que está no meio é o treino: aquilo é execução correta.
    A diferença entre estrutura e desleixo não se vê nos números soltos, vê-se
    na forma, por isso a forma é classificada aqui e entregue já decidida.
    """
    uteis = [p for p in parciais if p.get("pace_seconds") and p["km"] >= 0.4]
    if len(uteis) < 3:
        return {}

    ritmos = [p["pace_seconds"] for p in uteis]
    miolo = ritmos[1:-1]
    mais_rapido, mais_lento = min(ritmos), max(ritmos)
    amplitude = (mais_lento - mais_rapido) / mais_rapido

    # Alternância: quantas vezes o ritmo troca de sentido, contando só as
    # mudanças que valem alguma coisa. Entre 6:23 e 6:31 vão 2%, que é ruído de
    # passadeira, e contá-las fazia qualquer rodagem passar por séries.
    minimo = mais_rapido * 0.05
    def sentido(a, b):
        return 0 if abs(b - a) < minimo else (1 if b > a else -1)
    passos = [sentido(ritmos[i - 1], ritmos[i]) for i in range(1, len(ritmos))]
    reais = [p for p in passos if p]
    trocas = sum(1 for i in range(1, len(reais)) if reais[i] != reais[i - 1])

    primeiro_lento = ritmos[0] > min(miolo) * 1.10 if miolo else False
    ultimo_lento = ritmos[-1] > min(miolo) * 1.10 if miolo else False

    if amplitude < 0.06:
        forma = "even"
    elif trocas >= max(2, len(ritmos) // 2):
        forma = "intervals"
    elif primeiro_lento and ultimo_lento:
        forma = "warmup_work_cooldown"
    elif primeiro_lento:
        forma = "progressive"
    elif ultimo_lento:
        forma = "faded"
    else:
        forma = "mixed"

    return {"shape": forma, "spread_pct": round(amplitude * 100),
            "fastest": min(uteis, key=lambda p: p["pace_seconds"])["pace"],
            "slowest": max(uteis, key=lambda p: p["pace_seconds"])["pace"]}


def notas_do_detalhe(s: dict, ln: str) -> dict:
    """Acrescenta às notas o que só os parciais e as zonas sabem.

    O ritmo médio esconde a forma da sessão: 8:10 no primeiro quilómetro e
    9:15 no último, com 6:23 pelo meio, não é a mesma coisa que seis
    quilómetros iguais, e é isso que vale a pena dizer a quem correu.
    """
    from language import t as _t

    if not s.get("has_data"):
        return s
    notas = s.get("notas") or []

    parciais = s.get("splits") or []
    # Ritmo é ritmo: um parcial de 600 metros compara-se com um de mil. O que
    # não se compara é a duração bruta, que foi o erro anterior. Abaixo de 400
    # metros é ruído e fica de fora.
    inteiros = [p for p in parciais if p["km"] >= 0.4]
    if len(inteiros) >= 3:
        rapido = min(inteiros, key=lambda p: p["pace_seconds"])
        ultimo = inteiros[-1]
        if (s.get("shape", {}).get("shape") not in ("warmup_work_cooldown", "intervals")
                and ultimo["pace_seconds"] > rapido["pace_seconds"] * 1.15):
            notas.append(_t("s.faded", ln, last=ultimo["pace"], best=rapido["pace"]))
        elif ultimo["pace_seconds"] <= rapido["pace_seconds"] * 1.02:
            notas.append(_t("s.built", ln))

    forma = forma_da_sessao(s.get("splits") or [])
    if forma:
        forma["label"] = _t("shape." + forma["shape"], ln)
        s["shape"] = forma
        notas.append(forma["label"])

    ef = s.get("_efficiency") or {}
    if ef.get("has_data") and abs(ef["pct"]) >= 3:
        chave = "s.eff" if ef["pct"] > 0 else "s.eff_down"
        notas.append(_t(chave, ln, pct=f"{abs(ef['pct']):.1f}"))

    zonas = s.get("zones") or []
    total = sum(z["seconds"] for z in zonas)
    if total:
        z5 = next((z["seconds"] for z in zonas if z["n"] == 5), 0)
        z12 = sum(z["seconds"] for z in zonas if z["n"] <= 2)
        if z5 / total > 0.25:
            notas.append(_t("s.z5", ln, min=round(z5 / 60), pct=round(z5 / total * 100)))
        elif z12 / total > 0.6:
            notas.append(_t("s.z12", ln, pct=round(z12 / total * 100)))

    s["notas"] = notas
    return s


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
        # Com os parciais e as zonas de cada uma, não só da última. A tabela
        # dizia a data e a carga e mais nada, e quem quer ver como correu um
        # treino de há duas semanas não tinha onde carregar.
        "recent": [{**s, **detalhe_sessao(con, s["id"])} for s in recent_sessions(acts)],
        "body": body(con, spec.get("weight", {"table": []}), today),
        "paces": paces(acts),
        "efficiency": eficiencia(acts),
        "extra": contexto_extra(con, today),
        "bem_estar": series_bem_estar(con, today),
        "peso": series_peso(con, spec.get("weight", {"table": []}), today),
        "sessao": notas_do_detalhe(
            {**sessao_recente(acts, paces(acts), today, ln),
             **detalhe_sessao(con, (acts[-1].get("id") if acts else None)),
             "_efficiency": eficiencia(acts)}, ln),
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
