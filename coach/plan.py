#!/usr/bin/env python3
"""Gera o plano para hoje e os próximos 7 a 15 dias.

O plano é construído por simulação, não por opinião. Para cada dia futuro
projeta-se CTL, ATL e TSB com a carga estimada da sessão candidata, e só ficam
sessões que respeitam as mesmas regras de elegibilidade usadas para hoje.

O modelo de linguagem recebe o plano já feito e limita-se a explicá-lo. Um 4B
não tem como saber que três sessões duras em cinco dias partem uma pessoa ao
meio; a aritmética sabe.
"""

from __future__ import annotations

from datetime import date, timedelta

CTL_TC, ATL_TC = 42, 7

# Molde semanal. Segunda a descansar, qualidade a terça e quinta, força à
# sexta, longo ao sábado. É o esqueleto clássico; a elegibilidade deita-o
# abaixo quando o corpo não está para isso.
SLOTS = ["rest", "quality", "easy", "quality", "strength", "long", "easy"]

# Preferências por tipo de slot, da mais exigente para a mais branda.
PREFERENCES = {
    "rest": ["rest", "easy_walk"],
    "easy": ["easy_run", "treadmill_base", "strength", "easy_walk"],
    "quality": ["tempo", "treadmill_intervals_long", "treadmill_intervals_short"],
    "strength": ["strength", "easy_walk", "rest"],
    "long": ["long_run", "easy_run", "treadmill_base"],
}
SAFE = ["rest", "easy_walk", "strength"]

DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]

MAX_QUALITY_PER_WEEK = 2
RAMP_CAP = 1.10  # a semana planeada não excede a anterior em mais de 10%


def eligible(catalogue: list[dict], tsb: float, ctl: float,
             days_since_hard: int | None, flagged: bool) -> list[dict]:
    """Sessões admissíveis para um estado dado. Partilhada com o coach.py."""
    out = []
    for w in catalogue:
        if flagged and not w.get("recovery_safe"):
            continue
        if w.get("requires_fresh") and flagged:
            continue
        if "tsb_min" in w and tsb < w["tsb_min"]:
            continue
        if "tsb_max" in w and tsb > w["tsb_max"]:
            continue
        if "ctl_min" in w and ctl < w["ctl_min"]:
            continue
        if "days_since_hard_min" in w and days_since_hard is not None \
                and days_since_hard < w["days_since_hard_min"]:
            continue
        out.append(w)
    return out


def _pick(by_id: dict, allowed: set[str], order: list[str]) -> dict | None:
    return next((by_id[i] for i in order if i in allowed and i in by_id), None)


def build_plan(m: dict, catalogue: list[dict], flagged: bool, days: int = 14,
               skip_today: bool = False) -> dict:
    """Devolve o plano dia a dia mais um resumo do que ele provoca na carga."""
    by_id = {w["id"]: w for w in catalogue}
    load = m["load"]
    ctl, atl = float(load["ctl"]), float(load["atl"])
    dsh = load["days_since_hard"]

    a_ctl, a_atl = 2 / (CTL_TC + 1), 2 / (ATL_TC + 1)

    # O tecto semanal sai do maior entre a última semana e a média do mês. Só
    # com a última semana, uma semana de descanso passaria a ser o novo normal
    # e o plano seguinte encolhia para quase nada — visto acontecer: 111
    # minutos numa semana leve davam um tecto de 122, e o plano saía com oito
    # dias de descanso em catorze.
    mes = m.get("month", {})
    base_minutes = max(load["minutes_7d"], mes.get("mean_week_minutes_active", 0)
                       or mes.get("mean_week_minutes", 0))
    week_minutes_cap = max(round(base_minutes * RAMP_CAP), 120)

    plan, quality_week, minutes_week = [], 0, 0
    today = date.today()

    first = 1 if skip_today else 0
    for offset in range(first, first + days):
        day = today + timedelta(days=offset)
        if offset > first and (offset - first) % 7 == 0:   # nova semana do plano
            quality_week, minutes_week = 0, 0

        tsb = ctl - atl
        # As bandeiras de recuperação só valem para os primeiros dois dias: a
        # partir daí é projeção, e projetar fadiga indefinidamente seria fingir
        # que se sabe como a pessoa vai dormir na quinta-feira.
        allowed = {w["id"] for w in eligible(catalogue, tsb, ctl, dsh, flagged and offset <= 1)}

        slot = SLOTS[day.weekday()]
        if slot == "quality" and quality_week >= MAX_QUALITY_PER_WEEK:
            slot = "easy"

        choice = _pick(by_id, allowed, PREFERENCES[slot])
        if choice and minutes_week + choice.get("duration_min", 0) > week_minutes_cap:
            choice = _pick(by_id, allowed, SAFE)      # travão de volume
        if not choice:
            choice = _pick(by_id, allowed, SAFE) or by_id["rest"]

        est = choice.get("load_est", 0)
        ctl = est * a_ctl + ctl * (1 - a_ctl)
        atl = est * a_atl + atl * (1 - a_atl)

        hard = est >= 85
        dsh = 0 if hard else (dsh + 1 if dsh is not None else None)
        if hard:
            quality_week += 1
        minutes_week += choice.get("duration_min", 0)

        plan.append({
            "date": day.isoformat(),
            "weekday": DIAS[day.weekday()],
            "id": choice["id"],
            "name": choice["name"],
            "duration_min": choice.get("duration_min"),
            "load_est": est,
            "tsb_after": round(ctl - atl, 1),
        })

    sessions = [d for d in plan if d["id"] != "rest"]
    return {
        "days": plan,
        "summary": {
            "sessions": len(sessions),
            "hard": len([d for d in plan if d["load_est"] >= 85]),
            "minutes": sum(d["duration_min"] or 0 for d in plan),
            "week_minutes_cap": week_minutes_cap,
            "ctl_start": load["ctl"],
            "ctl_end": round(ctl, 1),
            "tsb_end": round(ctl - atl, 1),
        },
    }
