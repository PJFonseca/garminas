#!/usr/bin/env python3
"""Traduz cada número numa leitura: bom, a vigiar, ou a corrigir.

Um relatório cheio de valores sem veredicto obriga a pessoa a saber de
periodização para o ler — e quem sabe de periodização não precisa do
relatório. Por isso cada métrica traz um estado e uma frase que diz porquê.

Os limiares são convenções de treino, não verdades: TSB pelas bandas
clássicas de Coggan, a razão aguda/crónica pela literatura de carga de treino
(a zona 0.8–1.3 é a habitualmente citada como sustentável), e FC de repouso,
HRV e sono pelos mesmos valores que já disparam as bandeiras de recuperação,
para que o relatório não se contradiga.

Estados, por ordem de gravidade: bom, atencao, cuidado, alerta.
"""

from __future__ import annotations

ESTADOS = {
    "bom":     ("good",     "●", "bom"),
    "atencao": ("warning",  "◐", "a vigiar"),
    "cuidado": ("serious",  "◑", "a corrigir"),
    "alerta":  ("critical", "▲", "alerta"),
}


def _v(key, titulo, valor, unidade, estado, leitura, gloss=""):
    return {"key": key, "titulo": titulo, "valor": valor, "unidade": unidade,
            "estado": estado, "leitura": leitura, "gloss": gloss}


def tsb(value: float) -> dict:
    if value < -25:
        e, l = "alerta", "fadiga a acumular mais depressa do que a recuperação"
    elif value < -10:
        e, l = "atencao", "cansaço normal de quem está a construir carga"
    elif value <= 5:
        e, l = "bom", "carga e recuperação em equilíbrio"
    elif value <= 25:
        e, l = "bom", "fresco, bom momento para uma sessão exigente"
    else:
        e, l = "cuidado", "demasiado fresco: já se perde forma por falta de treino"
    return _v("tsb", "Frescura", value, "", e, l, "TSB — forma menos fadiga")


def ctl(value: float, delta: float) -> dict:
    if delta > 2:
        e, l = "bom", f"a subir {delta:+.1f} em quatro semanas, estás a ganhar base"
    elif delta >= -1:
        e, l = "bom", "estável em quatro semanas, a manter a base"
    elif delta >= -4:
        e, l = "atencao", f"a descer {delta:.1f} em quatro semanas"
    else:
        e, l = "cuidado", f"a descer {delta:.1f} em quatro semanas, a perder base aeróbia"
    return _v("ctl", "Forma de fundo", value, "", e, l, "CTL — média de carga a 42 dias")


def rhr(now, base) -> dict:
    if now is None or base is None:
        return _v("rhr", "FC de repouso", "—", "bpm", "bom", "sem dados suficientes")
    d = now - base
    if d > 5:
        e, l = "alerta", f"{d:+.1f} bpm acima da base: o corpo está a pedir descanso"
    elif d > 2:
        e, l = "cuidado", f"{d:+.1f} bpm acima da base, a vigiar nos próximos dias"
    elif d >= -1:
        e, l = "bom", "na base habitual"
    else:
        e, l = "bom", f"{d:.1f} bpm abaixo da base, sinal de boa recuperação"
    return _v("rhr", "FC de repouso", now, "bpm", e, l, f"7 dias · base 28 dias {base}")


def hrv(now, base) -> dict:
    if now is None or base is None:
        return _v("hrv", "HRV", "—", "", "bom", "sem dados suficientes")
    pct = (now - base) / base * 100 if base else 0
    if pct < -12:
        e, l = "alerta", f"{pct:.0f}% abaixo da base: sistema nervoso sob stress"
    elif pct < -5:
        e, l = "cuidado", f"{pct:.0f}% abaixo da base"
    elif pct <= 5:
        e, l = "bom", "na base habitual"
    else:
        e, l = "bom", f"{pct:+.0f}% acima da base, boa recuperação"
    return _v("hrv", "HRV", now, "", e, l, f"7 dias · base 28 dias {base}")


def sleep(hours) -> dict:
    if hours is None:
        return _v("sono", "Sono", "—", "h", "bom", "sem dados suficientes")
    if hours < 6:
        e, l = "alerta", "abaixo de 6 h: é aqui que o treino deixa de render"
    elif hours < 6.5:
        e, l = "cuidado", "curto; abaixo de 6 h corta o catálogo a recuperação"
    elif hours < 7:
        e, l = "atencao", "aceitável, mas há margem para melhorar"
    else:
        e, l = "bom", "suficiente para sustentar a carga"
    return _v("sono", "Sono", hours, "h", e, l, "média das últimas 7 noites")


def ramp(value) -> dict:
    if value is None:
        return _v("ramp", "Progressão", "—", "", "bom", "sem semanas anteriores para comparar")
    if value > 1.5:
        e, l = "alerta", "salto grande de mais face às semanas anteriores"
    elif value > 1.3:
        e, l = "cuidado", "acima de 1.3, o intervalo onde as lesões aparecem"
    elif value >= 0.8:
        e, l = "bom", "entre 0.8 e 1.3, progressão sustentável"
    elif value >= 0.5:
        e, l = "atencao", "abaixo de 0.8: semana mais leve do que as anteriores"
    else:
        e, l = "cuidado", "muito abaixo das semanas anteriores, a forma vai cair"
    return _v("ramp", "Progressão", value, "", e, l, "última semana face à média das anteriores")


def days_since_hard(days) -> dict:
    if days is None:
        return _v("dsh", "Sessão dura há", "—", "", "atencao",
                  "sem nenhuma sessão dura no histórico recente")
    if days > 21:
        e, l = "cuidado", "há muito sem estímulo intenso; a velocidade perde-se primeiro"
    elif days > 14:
        e, l = "atencao", "já vai longe sem uma sessão exigente"
    elif days < 2:
        e, l = "atencao", "sessão dura muito recente, cuidado com a seguinte"
    else:
        e, l = "bom", "espaçamento adequado"
    return _v("dsh", "Sessão dura há", days, "dias", e, l, "")


def volume(minutes_7d, mean_week_minutes) -> dict:
    if not mean_week_minutes:
        return _v("vol", "Volume 7 dias", minutes_7d, "min", "bom", "sem histórico para comparar")
    razao = minutes_7d / mean_week_minutes
    if razao < 0.6:
        e, l = "atencao", f"bem abaixo da média do mês ({mean_week_minutes} min)"
    elif razao > 1.4:
        e, l = "cuidado", f"bem acima da média do mês ({mean_week_minutes} min)"
    else:
        e, l = "bom", f"em linha com a média do mês ({mean_week_minutes} min)"
    return _v("vol", "Volume 7 dias", minutes_7d, "min", e, l, "")


ORDEM = {"alerta": 0, "cuidado": 1, "atencao": 2, "bom": 3}


def assess(m: dict) -> list[dict]:
    """Todas as leituras, das mais graves para as mais tranquilas."""
    load, rec, month = m["load"], m["recovery"], m["month"]
    fichas = [
        tsb(load["tsb"]),
        ctl(load["ctl"], load.get("ctl_delta", 0.0)),
        volume(load["minutes_7d"], month.get("mean_week_minutes", 0)),
        ramp(month["ramp"]),
        rhr(rec["rhr_7d"], rec["rhr_28d"]),
        hrv(rec["hrv_7d"], rec["hrv_28d"]),
        sleep(rec["sleep_h_7d"]),
        days_since_hard(load["days_since_hard"]),
    ]
    return sorted(fichas, key=lambda f: ORDEM[f["estado"]])


# Os nomes que a Garmin usa internamente não são para ler.
DESPORTOS = {
    "running": "Corrida", "treadmill_running": "Passadeira",
    "trail_running": "Trail", "indoor_running": "Corrida interior",
    "walking": "Caminhada", "hiking": "Caminhada na natureza",
    "cycling": "Ciclismo", "indoor_cycling": "Bicicleta interior",
    "mountain_biking": "BTT", "road_biking": "Estrada",
    "swimming": "Natação", "lap_swimming": "Natação em piscina",
    "open_water_swimming": "Águas abertas",
    "strength_training": "Força", "indoor_cardio": "Cardio interior",
    "elliptical": "Elíptica", "rowing": "Remo", "yoga": "Ioga",
    "unknown": "Sem categoria",
}


def desporto(chave: str) -> str:
    return DESPORTOS.get(chave, chave.replace("_", " ").capitalize())
