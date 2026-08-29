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

from idioma import t as _t

CTL_TC, ATL_TC = 42, 7

# Molde semanal. Segunda a descansar, qualidade a terça e quinta, força à
# sexta, longo ao sábado. É o esqueleto clássico; a elegibilidade deita-o
# abaixo quando o corpo não está para isso.
SLOTS = ["rest", "quality", "easy", "quality", "strength", "long", "easy"]

# Preferências por tipo de slot, da mais exigente para a mais branda.
PREFERENCES = {
    "rest": ["rest", "easy_walk"],
    "walk": ["easy_walk", "rest"],
    "easy": ["easy_run", "treadmill_base", "strength", "easy_walk"],
    "quality": ["tempo", "treadmill_intervals_long", "treadmill_intervals_short"],
    "strength": ["strength", "easy_walk", "rest"],
    "long": ["long_run", "easy_run", "treadmill_base"],
}
SAFE = ["rest", "easy_walk", "strength"]
SAFE_PESO = ["easy_walk", "rest", "strength"]

DIAS = {
    "pt": ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
    "fr": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
    "de": ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"],
    "it": ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"],
    "zh": ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"],
}

# O nome de cada espaço do molde semanal, por língua.
SLOT_NOME = {
    "rest": {"pt": "descanso", "en": "rest", "es": "descanso", "fr": "repos",
             "de": "Ruhe", "it": "riposo", "zh": "休息"},
    "easy": {"pt": "rodagem fácil", "en": "easy running", "es": "rodaje suave",
             "fr": "footing facile", "de": "lockerer Dauerlauf", "it": "corsa facile",
             "zh": "轻松跑"},
    "quality": {"pt": "trabalho de qualidade", "en": "quality work", "es": "trabajo de calidad",
                "fr": "travail de qualité", "de": "Qualitätsarbeit", "it": "lavoro di qualità",
                "zh": "强度训练"},
    "long": {"pt": "corrida longa", "en": "long run", "es": "tirada larga",
             "fr": "sortie longue", "de": "langer Lauf", "it": "lungo", "zh": "长距离跑"},
    "strength": {"pt": "força", "en": "strength", "es": "fuerza", "fr": "renforcement",
                 "de": "Kraft", "it": "forza", "zh": "力量"},
    "walk": {"pt": "caminhada", "en": "walking", "es": "caminata", "fr": "marche",
             "de": "Spaziergang", "it": "camminata", "zh": "步行"},
}

# Frases dos motivos, com marcadores. Ficam aqui porque só o plano as usa.
MOTIVOS = {
    "dia": {"pt": "é o dia de {slot} da semana", "en": "it is the week's {slot} day",
            "es": "es el día de {slot} de la semana", "fr": "c'est le jour de {slot} de la semaine",
            "de": "es ist der {slot}-Tag der Woche", "it": "è il giorno di {slot} della settimana",
            "zh": "这是本周的{slot}日"},
    "walk": {"pt": "caminhada em vez de descanso, para somar gasto sem cobrar recuperação",
             "en": "a walk instead of rest, to add expenditure without costing recovery",
             "es": "caminata en lugar de descanso, para sumar gasto sin cobrar recuperación",
             "fr": "une marche plutôt qu'un repos, pour dépenser sans coûter de récupération",
             "de": "ein Spaziergang statt Ruhe, um Verbrauch ohne Erholungskosten zu sammeln",
             "it": "camminata invece di riposo, per spendere senza costare recupero",
             "zh": "用步行代替休息，增加消耗又几乎不占恢复"},
    "tecto": {"pt": "a semana já leva {feitos} minutos de corrida e esta sessão passava o tecto de {tecto}, por isso hoje fica assim",
              "en": "the week already has {feitos} minutes of running and this session would pass the {tecto} ceiling, so today stays like this",
              "es": "la semana ya lleva {feitos} minutos de carrera y esta sesión pasaría el techo de {tecto}, así que hoy queda así",
              "fr": "la semaine compte déjà {feitos} minutes de course et cette séance dépasserait le plafond de {tecto}, donc ça reste ainsi",
              "de": "die Woche hat schon {feitos} Laufminuten und diese Einheit überschritte die Grenze von {tecto}, deshalb bleibt es heute dabei",
              "it": "la settimana ha già {feitos} minuti di corsa e questa seduta supererebbe il tetto di {tecto}, quindi oggi resta così",
              "zh": "本周已有 {feitos} 分钟跑量，这次会超过 {tecto} 的上限，所以今天维持这样"},
    "barreira": {"pt": "{barreira}, por isso fica esta", "en": "{barreira}, so this one it is",
                 "es": "{barreira}, así que queda esta", "fr": "{barreira}, donc ce sera celle-ci",
                 "de": "{barreira}, deshalb wird es diese", "it": "{barreira}, quindi resta questa",
                 "zh": "{barreira}，所以改成这个"},
    "elegivel": {"pt": "é o dia de {slot}, no que está elegível",
                 "en": "it is the {slot} day, within what is eligible",
                 "es": "es el día de {slot}, dentro de lo elegible",
                 "fr": "c'est le jour de {slot}, parmi ce qui est éligible",
                 "de": "es ist der {slot}-Tag, im Rahmen des Möglichen",
                 "it": "è il giorno di {slot}, tra ciò che è ammissibile",
                 "zh": "这是{slot}日，在可选范围内"},
    "nada": {"pt": "nada mais exigente está elegível com o estado de hoje",
             "en": "nothing harder is eligible given today's state",
             "es": "nada más exigente es elegible con el estado de hoy",
             "fr": "rien de plus exigeant n'est éligible vu l'état du jour",
             "de": "nichts Härteres ist bei der heutigen Verfassung möglich",
             "it": "niente di più impegnativo è ammissibile con lo stato di oggi",
             "zh": "以今天的状态，没有更高强度的可选"},
}

BARREIRAS = {
    "flag": {"pt": "há sinais de fadiga por resolver, por isso só entram sessões leves",
             "en": "there are unresolved fatigue signals, so only easy sessions qualify",
             "es": "hay señales de fatiga sin resolver, así que solo entran sesiones suaves",
             "fr": "des signaux de fatigue persistent, donc seules les séances faciles passent",
             "de": "es gibt ungelöste Ermüdungssignale, daher kommen nur lockere Einheiten infrage",
             "it": "ci sono segnali di fatica irrisolti, quindi passano solo sedute leggere",
             "zh": "疲劳信号尚未消除，只安排轻松训练"},
    "dsh": {"pt": "a última sessão dura foi há {dsh} dias e esta pede {pede}",
            "en": "the last hard session was {dsh} days ago and this one needs {pede}",
            "es": "la última sesión dura fue hace {dsh} días y esta pide {pede}",
            "fr": "la dernière séance dure remonte à {dsh} jours et celle-ci en demande {pede}",
            "de": "die letzte harte Einheit war vor {dsh} Tagen, diese verlangt {pede}",
            "it": "l'ultima seduta dura è di {dsh} giorni fa e questa ne chiede {pede}",
            "zh": "上次高强度训练是 {dsh} 天前，这次需要 {pede} 天"},
    "tsb": {"pt": "a frescura está em {tsb} e esta sessão pede pelo menos {pede}",
            "en": "freshness is at {tsb} and this session needs at least {pede}",
            "es": "la frescura está en {tsb} y esta sesión pide al menos {pede}",
            "fr": "la fraîcheur est à {tsb} et cette séance en demande au moins {pede}",
            "de": "die Frische liegt bei {tsb}, diese Einheit verlangt mindestens {pede}",
            "it": "la freschezza è a {tsb} e questa seduta chiede almeno {pede}",
            "zh": "状态储备为 {tsb}，这次至少需要 {pede}"},
    "ctl": {"pt": "a base aeróbia ainda está em {ctl} e esta sessão pede {pede}",
            "en": "the aerobic base is still at {ctl} and this session needs {pede}",
            "es": "la base aeróbica está en {ctl} y esta sesión pide {pede}",
            "fr": "la base aérobie est à {ctl} et cette séance en demande {pede}",
            "de": "die aerobe Grundlage liegt bei {ctl}, diese Einheit verlangt {pede}",
            "it": "la base aerobica è a {ctl} e questa seduta chiede {pede}",
            "zh": "有氧基础为 {ctl}，这次需要 {pede}"},
}


def _f(tabela: dict, chave: str, ln: str, **kw) -> str:
    d = tabela[chave]
    return (d.get(ln) or d["en"]).format(**kw)

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


def porque_nao(w: dict, tsb: float, ctl: float, dsh: int | None, flagged: bool,
               ln: str = "en") -> str:
    """A regra que impediu uma sessão. Serve para explicar a escolha do dia.

    Sem isto o plano diz o que fazer mas nunca porquê, e uma sugestão sem
    razão é indistinguível de um palpite.
    """
    if flagged and not w.get("recovery_safe"):
        return _f(BARREIRAS, "flag", ln)
    if "days_since_hard_min" in w and dsh is not None and dsh < w["days_since_hard_min"]:
        return _f(BARREIRAS, "dsh", ln, dsh=dsh, pede=w["days_since_hard_min"])
    if "tsb_min" in w and tsb < w["tsb_min"]:
        return _f(BARREIRAS, "tsb", ln, tsb=round(tsb, 1), pede=w["tsb_min"])
    if "ctl_min" in w and ctl < w["ctl_min"]:
        return _f(BARREIRAS, "ctl", ln, ctl=round(ctl, 1), pede=w["ctl_min"])
    return ""


def _por_lingua(valor, ln: str):
    """Aceita texto simples ou um dicionário por língua, com recurso a inglês."""
    if isinstance(valor, dict):
        return valor.get(ln) or valor.get("en") or next(iter(valor.values()), "")
    return valor


def ritmo_de(w: dict, paces: dict, ln: str = "en") -> str:
    """Preenche a instrução de velocidade com os ritmos da pessoa."""
    modelo = _por_lingua(w.get("ritmo"), ln)
    if not modelo or not paces.get("has_data"):
        return ""
    try:
        return modelo.format(**{k: v for k, v in paces.items() if isinstance(v, (int, float))})
    except KeyError:
        return ""


def build_plan(m: dict, catalogue: list[dict], flagged: bool, days: int = 14,
               skip_today: bool = False, objetivo: dict | None = None,
               extras: dict | None = None, ln: str = "en") -> dict:
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

    # Com o objetivo de perder peso, o descanso completo passa a caminhada
    # leve, tirando um dia por semana. Caminhar gasta energia e quase não cobra
    # recuperação; a intensidade fica na mesma, porque é essa que magoa.
    objetivo, extras = objetivo or {}, extras or {}
    perder_peso = bool(objetivo.get("perder_peso")) and not flagged
    descansos_por_semana = objetivo.get("dias_descanso_por_semana", 1)

    plan, quality_week, minutes_week, descansos_week = [], 0, 0, 0
    today = date.today()

    first = 1 if skip_today else 0
    for offset in range(first, first + days):
        day = today + timedelta(days=offset)
        if offset > first and (offset - first) % 7 == 0:   # nova semana do plano
            quality_week, minutes_week, descansos_week = 0, 0, 0

        tsb = ctl - atl
        # As bandeiras de recuperação só valem para os primeiros dois dias: a
        # partir daí é projeção, e projetar fadiga indefinidamente seria fingir
        # que se sabe como a pessoa vai dormir na quinta-feira.
        allowed = {w["id"] for w in eligible(catalogue, tsb, ctl, dsh, flagged and offset <= 1)}

        slot = SLOTS[day.weekday()]
        if slot == "quality" and quality_week >= MAX_QUALITY_PER_WEEK:
            slot = "easy"

        if perder_peso and slot == "rest" and descansos_week >= descansos_por_semana:
            slot = "walk"
        preferida = by_id.get(PREFERENCES[slot][0])
        choice = _pick(by_id, allowed, PREFERENCES[slot])
        nome_slot = SLOT_NOME[slot].get(ln) or SLOT_NOME[slot]["en"]
        motivo = _f(MOTIVOS, "dia", ln, slot=nome_slot)
        if slot == "walk":
            motivo = _f(MOTIVOS, "walk", ln)

        recurso = SAFE_PESO if (perder_peso and descansos_week >= descansos_por_semana) else SAFE
        if choice and minutes_week + choice.get("duration_min", 0) > week_minutes_cap:
            choice = _pick(by_id, allowed, recurso)   # travão de volume
            motivo = _f(MOTIVOS, "tecto", ln, feitos=minutes_week, tecto=week_minutes_cap)
        elif choice and preferida and choice["id"] != preferida["id"]:
            barreira = porque_nao(preferida, tsb, ctl, dsh, flagged and offset <= 1, ln)
            motivo = (_f(MOTIVOS, "barreira", ln, barreira=barreira) if barreira
                      else _f(MOTIVOS, "elegivel", ln, slot=nome_slot))
        if not choice:
            choice = _pick(by_id, allowed, recurso) or by_id["rest"]
            motivo = _f(MOTIVOS, "nada", ln)

        est = choice.get("load_est", 0)
        ctl = est * a_ctl + ctl * (1 - a_ctl)
        atl = est * a_atl + atl * (1 - a_atl)

        if choice["id"] == "rest":
            descansos_week += 1
        hard = est >= 85
        dsh = 0 if hard else (dsh + 1 if dsh is not None else None)
        if hard:
            quality_week += 1
        # O tecto limita a subida do volume de corrida. Caminhar não é correr:
        # não carrega as pernas da mesma maneira e não pertence a essa conta.
        if choice["id"] != "easy_walk":
            minutes_week += choice.get("duration_min", 0)

        plan.append({
            "date": day.isoformat(),
            "weekday": (DIAS.get(ln) or DIAS["en"])[day.weekday()],
            "id": choice["id"],
            "name": _por_lingua(choice["name"], ln),
            "description": " ".join(_por_lingua(choice.get("description", ""), ln).split()),
            "ritmo": ritmo_de(choice, m.get("paces", {}), ln),
            "estrutura": (extras.get("estruturas") or {}).get(choice["id"], []),
            "exercicios": (extras.get("exercicios") or {}).get(choice["id"], []),
            "motivo": motivo,
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
