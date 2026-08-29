#!/usr/bin/env python3
"""Traduz cada número numa leitura: bom, a vigiar, ou a corrigir.

Um relatório cheio de valores sem veredicto obriga a pessoa a saber de
periodização para o ler, e quem sabe de periodização não precisa do
relatório. Por isso cada métrica traz um estado e uma frase que diz porquê.

Os limiares são convenções de treino, não verdades: TSB pelas bandas
clássicas de Coggan, a razão aguda/crónica pela literatura de carga de treino
(a zona 0.8 a 1.3 é a habitualmente citada como sustentável), e FC de repouso,
HRV e sono pelos mesmos valores que já disparam as bandeiras de recuperação,
para que o relatório não se contradiga.

O texto sai no idioma do perfil. Os limiares não mudam com a língua.
"""

from __future__ import annotations

from language import t

ESTADOS = {
    "bom":     ("good",     "●", "state.good"),
    "atencao": ("warning",  "◐", "state.watch"),
    "cuidado": ("serious",  "◑", "state.fix"),
    "alerta":  ("critical", "▲", "state.alert"),
}


def rotulo(estado: str, idioma: str) -> str:
    return t(ESTADOS[estado][2], idioma)


def _v(key, titulo, valor, unidade, estado, leitura, gloss="",
       escala_=None, alvo="", acao=""):
    """Uma ficha de leitura.

    escala diz onde o valor cai entre o mau e o bom, para que "a corrigir" não
    seja um rótulo sem fasquia. alvo é o intervalo desejável em palavras, e
    acao o que fazer quando não está bem.
    """
    return {"key": key, "titulo": titulo, "valor": valor, "unidade": unidade,
            "estado": estado, "leitura": leitura, "gloss": gloss,
            "escala": escala_, "alvo": alvo, "acao": acao,
            "rotulo": None}


def escala(minimo: float, maximo: float, zonas: list, valor) -> dict | None:
    """Zonas contíguas e a posição do valor, ambas em percentagem da barra."""
    if valor is None or maximo <= minimo:
        return None
    largura = maximo - minimo
    saida, anterior = [], minimo
    for limite, estado in zonas:
        topo = min(float(limite), maximo)
        if topo > anterior:
            saida.append({"largura": round((topo - anterior) / largura * 100, 2),
                          "estado": estado})
            anterior = topo
    if anterior < maximo:
        saida.append({"largura": round((maximo - anterior) / largura * 100, 2),
                      "estado": zonas[-1][1]})
    pos = (min(max(float(valor), minimo), maximo) - minimo) / largura * 100
    return {"zonas": saida, "pos": round(pos, 2), "min": minimo, "max": maximo}


def tsb(value: float, ln: str) -> dict:
    if value < -25:
        e, l = "alerta", t("l.tsb.alert", ln)
    elif value < -10:
        e, l = "atencao", t("l.tsb.watch", ln)
    elif value <= 5:
        e, l = "bom", t("l.tsb.balanced", ln)
    elif value <= 25:
        e, l = "bom", t("l.tsb.fresh", ln)
    else:
        e, l = "cuidado", t("l.tsb.idle", ln)
    acao = "" if e == "bom" else t("ac.tsb.rest" if value < -10 else "ac.tsb.train", ln)
    return _v("tsb", t("m.tsb", ln), value, "", e, l, t("g.tsb", ln),
              escala(-40, 30, [(-25, "alerta"), (-10, "atencao"), (5, "bom"),
                               (25, "bom"), (30, "cuidado")], value),
              t("a.tsb", ln), acao)


def ctl(value: float, delta: float, ln: str) -> dict:
    if delta > 2:
        e, l = "bom", t("l.ctl.up", ln, delta=f"{delta:+.1f}")
    elif delta >= -1:
        e, l = "bom", t("l.ctl.flat", ln)
    elif delta >= -4:
        e, l = "atencao", t("l.ctl.down", ln, delta=f"{delta:.1f}")
    else:
        e, l = "cuidado", t("l.ctl.falling", ln, delta=f"{delta:.1f}")
    return _v("ctl", t("m.ctl", ln), value, "", e, l,
              t("g.ctl", ln, antes=round(value - delta, 1)),
              escala(-8, 8, [(-4, "cuidado"), (-1, "atencao"), (2, "bom"), (8, "bom")], delta),
              t("a.ctl", ln), "" if e == "bom" else t("ac.ctl", ln))


def rhr(now, base, ln: str) -> dict:
    if now is None or base is None:
        return _v("rhr", t("m.rhr", ln), t("g.no_data", ln), "", "bom", t("g.no_data", ln))
    d = now - base
    if d > 5:
        e, l = "alerta", t("l.rhr.high", ln, d=f"{d:+.1f}")
    elif d > 2:
        e, l = "cuidado", t("l.rhr.mid", ln, d=f"{d:+.1f}")
    elif d >= -1:
        e, l = "bom", t("l.rhr.normal", ln)
    else:
        e, l = "bom", t("l.rhr.low", ln, d=f"{d:.1f}")
    return _v("rhr", t("m.rhr", ln), now, "bpm", e, l,
              t("g.base", ln, base=base, delta=f"{d:+.1f} bpm"),
              escala(-4, 8, [(-1, "bom"), (2, "bom"), (5, "cuidado"), (8, "alerta")], d),
              t("a.rhr", ln), "" if e == "bom" else t("ac.rhr", ln))


def hrv(now, base, ln: str) -> dict:
    if now is None or base is None:
        return _v("hrv", t("m.hrv", ln), t("g.no_data", ln), "", "bom", t("g.no_data", ln))
    pct = (now - base) / base * 100 if base else 0
    if pct < -12:
        e, l = "alerta", t("l.hrv.alert", ln, pct=f"{pct:.0f}")
    elif pct < -5:
        e, l = "cuidado", t("l.hrv.low", ln, pct=f"{pct:.0f}")
    elif pct <= 5:
        e, l = "bom", t("l.hrv.normal", ln)
    else:
        e, l = "bom", t("l.hrv.high", ln, pct=f"{pct:+.0f}%")
    return _v("hrv", t("m.hrv", ln), now, "", e, l,
              t("g.base", ln, base=base, delta=f"{pct:+.0f}%"),
              escala(-25, 15, [(-12, "alerta"), (-5, "cuidado"), (5, "bom"), (15, "bom")], pct),
              t("a.hrv", ln), "" if e == "bom" else t("ac.hrv", ln))


def sleep(hours, ln: str) -> dict:
    if hours is None:
        return _v("sono", t("m.sleep", ln), t("g.no_data", ln), "", "bom", t("g.no_data", ln))
    if hours < 6:
        e, l = "alerta", t("l.sleep.alert", ln)
    elif hours < 6.5:
        e, l = "cuidado", t("l.sleep.short", ln)
    elif hours < 7:
        e, l = "atencao", t("l.sleep.ok", ln)
    else:
        e, l = "bom", t("l.sleep.good", ln)
    return _v("sono", t("m.sleep", ln), hours, "h", e, l, t("g.sleep", ln),
              escala(4, 9, [(6, "alerta"), (6.5, "cuidado"), (7, "atencao"), (9, "bom")], hours),
              t("a.sleep", ln), "" if e == "bom" else t("ac.sleep", ln))


def ramp(value, ln: str) -> dict:
    if value is None:
        return _v("ramp", t("m.ramp", ln), t("g.no_data", ln), "", "bom", t("g.no_data", ln))
    if value > 1.5:
        e, l = "alerta", t("l.ramp.alert", ln)
    elif value > 1.3:
        e, l = "cuidado", t("l.ramp.high", ln)
    elif value >= 0.8:
        e, l = "bom", t("l.ramp.good", ln)
    elif value >= 0.5:
        e, l = "atencao", t("l.ramp.light", ln)
    else:
        e, l = "cuidado", t("l.ramp.very_light", ln)
    acao = "" if e == "bom" else t("ac.ramp.raise" if value < 0.8 else "ac.ramp.hold", ln)
    return _v("ramp", t("m.ramp", ln), value, "", e, l, t("g.ramp", ln),
              escala(0, 2, [(0.5, "cuidado"), (0.8, "atencao"), (1.3, "bom"),
                            (1.5, "cuidado"), (2, "alerta")], value),
              t("a.ramp", ln), acao)


def days_since_hard(days, ln: str) -> dict:
    if days is None:
        return _v("dsh", t("m.dsh", ln), t("g.no_data", ln), "", "atencao", t("l.dsh.none", ln))
    if days > 21:
        e, l = "cuidado", t("l.dsh.long", ln)
    elif days > 14:
        e, l = "atencao", t("l.dsh.some", ln)
    elif days < 2:
        e, l = "atencao", t("l.dsh.recent", ln)
    else:
        e, l = "bom", t("l.dsh.good", ln)
    acao = "" if e == "bom" else t("ac.dsh.add" if days > 14 else "ac.dsh.wait", ln)
    return _v("dsh", t("m.dsh", ln), days, "d", e, l, t("g.dsh", ln),
              escala(0, 25, [(2, "atencao"), (14, "bom"), (21, "atencao"), (25, "cuidado")], days),
              t("a.dsh", ln), acao)


def volume(minutes_7d, mean_week_minutes, ln: str) -> dict:
    if not mean_week_minutes:
        return _v("vol", t("m.vol", ln), minutes_7d, "min", "bom", t("l.vol.no_base", ln))
    razao = minutes_7d / mean_week_minutes
    if razao < 0.6:
        e, l = "atencao", t("l.vol.low", ln, media=mean_week_minutes)
    elif razao > 1.4:
        e, l = "cuidado", t("l.vol.high", ln, media=mean_week_minutes)
    else:
        e, l = "bom", t("l.vol.good", ln, media=mean_week_minutes)
    acao = "" if e == "bom" else t("ac.vol.short" if razao < 1 else "ac.vol.heavy", ln)
    return _v("vol", t("m.vol", ln), minutes_7d, "min", e, l,
              t("g.vol", ln, media=mean_week_minutes),
              escala(0, 2, [(0.6, "atencao"), (1.4, "bom"), (2, "cuidado")], razao),
              t("a.vol", ln), acao)


def peso(b: dict, ln: str, alvo=(-0.75, -0.25)) -> dict | None:
    """Peso e ritmo de variação, quando há pesagens que o sustentem.

    O ritmo é lido em percentagem do peso corporal por semana, não em quilos:
    meio quilo por semana é coisa diferente para quem pesa 60 ou 95.
    """
    if not b.get("has_data"):
        return None

    kg, velhos = b["kg"], b["days_old"]
    gloss = t("g.weight", ln, data=b["date"])
    if b.get("bmi"):
        gloss += f", IMC {b['bmi']}" if ln == "pt" else f", BMI {b['bmi']}"

    if velhos > 21:
        return _v("peso", t("m.weight", ln), kg, "kg", "atencao",
                  t("l.weight.stale", ln, dias=velhos), gloss, None, "",
                  t("ac.weight.weigh", ln))

    ritmo = b.get("kg_per_week")
    if ritmo is None:
        return _v("peso", t("m.weight", ln), kg, "kg", "atencao",
                  t("l.weight.few", ln), gloss, None, "", t("ac.weight.weigh_weekly", ln))

    pct = ritmo / kg * 100 if kg else 0
    baixo, alto = alvo
    if pct < baixo * 1.5:
        e, l, acao = "cuidado", t("l.weight.fast", ln, kg=f"{abs(ritmo):.2f}"), t("ac.weight.eat", ln)
    elif pct <= alto:
        e, l, acao = "bom", t("l.weight.right", ln, kg=f"{abs(ritmo):.2f}"), ""
    elif pct <= 0.1:
        e, l, acao = "atencao", t("l.weight.flat", ln), t("ac.weight.kitchen", ln)
    else:
        e, l, acao = "cuidado", t("l.weight.up", ln, kg=f"{ritmo:.2f}"), t("ac.weight.food", ln)

    return _v("peso", t("m.weight", ln), kg, "kg", e, l, gloss,
              escala(-1.2, 0.6, [(baixo * 1.5, "cuidado"), (alto, "bom"),
                                 (0.1, "atencao"), (0.6, "cuidado")], ritmo),
              t("a.weight", ln, min=f"{abs(alto) * kg / 100:.2f}", max=f"{abs(baixo) * kg / 100:.2f}"),
              acao)


ORDEM = {"alerta": 0, "cuidado": 1, "atencao": 2, "bom": 3}


def assess(m: dict, ln: str = "en") -> list[dict]:
    """Todas as leituras, das mais graves para as mais tranquilas."""
    load, rec, month = m["load"], m["recovery"], m["month"]
    fichas = [
        tsb(load["tsb"], ln),
        ctl(load["ctl"], load.get("ctl_delta", 0.0), ln),
        volume(load["minutes_7d"], month.get("mean_week_minutes", 0), ln),
        ramp(month["ramp"], ln),
        rhr(rec["rhr_7d"], rec["rhr_28d"], ln),
        hrv(rec["hrv_7d"], rec["hrv_28d"], ln),
        sleep(rec["sleep_h_7d"], ln),
        days_since_hard(load["days_since_hard"], ln),
    ]
    ficha_peso = peso(m.get("body", {}), ln)
    if ficha_peso:
        fichas.append(ficha_peso)
    for f in fichas:
        f["rotulo"] = rotulo(f["estado"], ln)
    return sorted(fichas, key=lambda f: ORDEM[f["estado"]])


# Os nomes que a Garmin usa internamente não são para ler.
DESPORTOS = {
    "running": ("Corrida", "Run"), "treadmill_running": ("Passadeira", "Treadmill"),
    "trail_running": ("Trail", "Trail run"), "indoor_running": ("Corrida interior", "Indoor run"),
    "walking": ("Caminhada", "Walk"), "hiking": ("Caminhada na natureza", "Hike"),
    "cycling": ("Ciclismo", "Cycling"), "indoor_cycling": ("Bicicleta interior", "Indoor cycling"),
    "mountain_biking": ("BTT", "Mountain biking"), "road_biking": ("Estrada", "Road cycling"),
    "swimming": ("Natação", "Swimming"), "lap_swimming": ("Natação em piscina", "Pool swim"),
    "open_water_swimming": ("Águas abertas", "Open water swim"),
    "strength_training": ("Força", "Strength"), "indoor_cardio": ("Cardio interior", "Indoor cardio"),
    "elliptical": ("Elíptica", "Elliptical"), "rowing": ("Remo", "Rowing"),
    "yoga": ("Ioga", "Yoga"), "unknown": ("Sem categoria", "Uncategorised"),
}


def desporto(chave: str, ln: str = "en") -> str:
    par = DESPORTOS.get(chave)
    if par:
        return par[1] if ln == "en" else par[0]
    return chave.replace("_", " ").capitalize()
