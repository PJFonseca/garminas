#!/usr/bin/env python3
"""Gera o relatório diário de treino.

Divisão de responsabilidades:
  metrics.py    calcula os números
  plan.py       constrói o plano por simulação
  workouts.yaml define o catálogo e as regras
  este ficheiro monta o relatório e pede ao modelo que o comente

O relatório tem quatro partes: o que foi feito, a leitura do que foi feito, o
retrato dos últimos 30 dias, e o plano para os próximos dias.

O modelo nunca calcula, nunca inventa sessões, e nunca decide sozinho ignorar
uma bandeira de recuperação. Se o modelo estiver em baixo, o relatório sai na
mesma — só que sem as partes redigidas.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from metrics import build, connect  # noqa: E402
from plan import build_plan, eligible  # noqa: E402

CATALOGUE = Path(__file__).with_name("workouts.yaml")
OUT_DIR = Path(os.environ.get("COACH_OUT", "/data/reports"))
LLM_URL = os.environ.get("LLM_URL", "http://llm:8080/v1/chat/completions")
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "600"))
PLAN_DAYS = int(os.environ.get("COACH_PLAN_DAYS", "14"))


def check_flags(m: dict, rules: dict) -> list[str]:
    """Bandeiras de recuperação. Determinístico de propósito."""
    r, load, flags = m["recovery"], m["load"], []

    if r["rhr_delta"] is not None and r["rhr_delta"] > rules["rhr_delta_above"]:
        flags.append(f"FC de repouso {r['rhr_delta']:+.1f} bpm acima da base de 28 dias")
    if r["hrv_delta_pct"] is not None and r["hrv_delta_pct"] < rules["hrv_drop_pct_below"]:
        flags.append(f"HRV {r['hrv_delta_pct']:.1f}% abaixo da base")
    if r["sleep_h_7d"] is not None and r["sleep_h_7d"] < rules["sleep_h_below"]:
        flags.append(f"média de sono de {r['sleep_h_7d']} h nos últimos 7 dias")
    if load["tsb"] < rules["tsb_below"]:
        flags.append(f"TSB em {load['tsb']}, fadiga acumulada elevada")
    return flags


def ask_llm(system: str, prompt: str, max_tokens: int = 400) -> str | None:
    body = json.dumps({
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.4,
        "max_tokens": max_tokens,
    }).encode()

    req = urllib.request.Request(LLM_URL, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
            return json.load(resp)["choices"][0]["message"]["content"].strip()
    except (urllib.error.URLError, KeyError, TimeoutError, OSError) as exc:
        print(f"modelo indisponível ({exc}); secção sai sem comentário", file=sys.stderr)
        return None


SYSTEM = "És um treinador conciso e honesto. Escreves em português europeu, sem entusiasmo artificial."


def analyse_training(m: dict, flags: list[str]) -> str | None:
    """Primeira chamada: leitura do que foi efetivamente treinado."""
    sessions = "\n".join(
        f"- {s['date']} {s['sport']}, {s['minutes']} min"
        + (f", {s['km']} km" if s["km"] else "")
        + (f", FC média {s['avg_hr']}" if s["avg_hr"] else "")
        + f", carga {s['load']}"
        for s in m["recent"][:10]
    ) or "- nenhuma sessão registada"

    return ask_llm(SYSTEM, f"""Sessões mais recentes:
{sessions}

Carga: CTL {m['load']['ctl']}, ATL {m['load']['atl']}, TSB {m['load']['tsb']}
Últimos 7 dias: {m['load']['sessions_7d']} sessões, {m['load']['minutes_7d']} minutos
Dias desde a última sessão dura: {m['load']['days_since_hard']}
Recuperação: FC repouso 7d {m['recovery']['rhr_7d']} contra 28d {m['recovery']['rhr_28d']}, \
HRV 7d {m['recovery']['hrv_7d']} contra 28d {m['recovery']['hrv_28d']}, \
sono 7d {m['recovery']['sleep_h_7d']} h
Bandeiras ativas: {'; '.join(flags) if flags else 'nenhuma'}

Escreve uma leitura do treino feito nos últimos dias, em português europeu:
1. O que a distribuição das sessões revela, citando números concretos acima.
2. Se o equilíbrio entre carga e recuperação está a resultar ou não.

Máximo 120 palavras. Não inventes números.""")


def review_and_recommend(m: dict, plan: dict, flags: list[str]) -> str | None:
    """Segunda chamada: 30 dias e justificação do plano já calculado."""
    month = m["month"]
    weeks = "\n".join(
        f"- semana de {w['start']}: {w['sessions']} sessões, {w['minutes']} min, carga {w['load']}"
        for w in reversed(month["weeks"])
    )
    days = "\n".join(
        f"- {d['date']} ({d['weekday']}): {d['name']}"
        + (f", {d['duration_min']} min" if d["duration_min"] else "")
        for d in plan["days"]
    )
    s = plan["summary"]

    return ask_llm(SYSTEM, f"""Últimas quatro semanas:
{weeks}

Taxa de progressão da última semana face às anteriores: {month['ramp']}
Sessões duras em 28 dias: {month['hard_sessions']}. Dias sem treino: {month['rest_days']}.
Sessão mais longa: {month['longest_min']} min, {month['longest_km']} km.
Bandeiras ativas hoje: {'; '.join(flags) if flags else 'nenhuma'}

Plano já calculado para os próximos {len(plan['days'])} dias, que deves explicar
e não alterar:
{days}

O plano dá {s['sessions']} sessões, {s['hard']} delas duras, {s['minutes']} minutos
no total, e leva o CTL de {s['ctl_start']} para {s['ctl_end']}.

Escreve, em português europeu:
1. O que os últimos 30 dias mostram como tendência, com um número concreto.
2. Porque é que o plano acima faz sentido face a essa tendência, em duas ou três frases.
3. Um sinal concreto que obrigue a abrandar o plano.

Máximo 160 palavras. Não inventes sessões que não estejam na lista.""", max_tokens=520)


def table(header: list[str], rows: list[list]) -> list[str]:
    return ["| " + " | ".join(header) + " |",
            "|" + "|".join("---" for _ in header) + "|"] + \
           ["| " + " | ".join("—" if c is None else str(c) for c in r) + " |" for r in rows]


def render(m: dict, flags: list[str], plan: dict, analysis: str | None,
           review: str | None) -> str:
    load, rec, month = m["load"], m["recovery"], m["month"]
    today = plan["days"][0]

    lines = [f"# Treino — {m['generated']}", ""]

    lines += ["## Estado", ""]
    lines += table(["Métrica", "Valor"], [
        ["CTL (forma de fundo)", load["ctl"]],
        ["ATL (fadiga recente)", load["atl"]],
        ["TSB (frescura)", load["tsb"]],
        ["Sessões / minutos, 7 dias", f"{load['sessions_7d']} / {load['minutes_7d']}"],
        ["Dias desde sessão dura", load["days_since_hard"]],
        ["FC repouso 7d vs 28d", f"{rec['rhr_7d']} vs {rec['rhr_28d']}"],
        ["HRV 7d vs 28d", f"{rec['hrv_7d']} vs {rec['hrv_28d']}"],
        ["Sono médio 7d", f"{rec['sleep_h_7d']} h"],
    ])
    lines += [""]

    if flags:
        lines += ["## Bandeiras de recuperação", ""]
        lines += [f"- {f}" for f in flags]
        lines += ["", "Enquanto durarem, só ficam elegíveis sessões de recuperação.", ""]

    lines += ["## Treinos recentes", ""]
    if m["recent"]:
        lines += table(["Data", "Desporto", "Min", "km", "FC média", "Carga"],
                       [[s["date"], s["sport"], s["minutes"], s["km"] or None,
                         s["avg_hr"], s["load"]] for s in m["recent"]])
    else:
        lines += ["Sem sessões registadas."]
    lines += [""]

    lines += ["## Análise", ""]
    lines += [analysis or "_Modelo indisponível: esta secção precisa dele. Os números acima estão completos._"]
    lines += [""]

    lines += ["## Últimos 30 dias", ""]
    lines += table(["Semana de", "Sessões", "Minutos", "km", "Carga"],
                   [[w["start"], w["sessions"], w["minutes"], w["km"], w["load"]]
                    for w in reversed(month["weeks"])])
    lines += ["", f"Progressão da última semana face às anteriores: **{month['ramp']}** "
                  f"(acima de 1.3 é território de lesão, abaixo de 0.8 é perda de forma). "
                  f"{month['hard_sessions']} sessões duras, {month['rest_days']} dias sem treino, "
                  f"sessão mais longa {month['longest_min']} min.", ""]

    lines += ["## Hoje", "",
              f"**{today['name']}**"
              + (f" — {today['duration_min']} min" if today["duration_min"] else "") + ".", ""]

    s = plan["summary"]
    lines += [f"## Plano — próximos {len(plan['days'])} dias", ""]
    lines += table(["Data", "Dia", "Sessão", "Min", "TSB projetado"],
                   [[d["date"], d["weekday"], d["name"], d["duration_min"], d["tsb_after"]]
                    for d in plan["days"]])
    lines += ["", f"{s['sessions']} sessões, {s['hard']} duras, {s['minutes']} minutos. "
                  f"CTL projetado de {s['ctl_start']} para {s['ctl_end']}, "
                  f"TSB no fim {s['tsb_end']}.", ""]

    lines += ["## Recomendação", ""]
    lines += [review or "_Modelo indisponível: o plano acima foi calculado à mesma e é válido._"]

    lines += ["", "---", "",
              "Orientação genérica gerada a partir dos teus próprios dados. "
              "Não substitui acompanhamento clínico ou de um treinador, "
              "sobretudo se houver dor, tonturas ou sintomas persistentes."]
    return "\n".join(lines)


def main() -> None:
    cfg = yaml.safe_load(CATALOGUE.read_text())
    m = build(connect())

    if m["coverage"]["activities"] == 0:
        sys.exit("Sem atividades na base de dados. Correr a sincronização primeiro.")

    flags = check_flags(m, cfg["recovery_flags"])
    plan = build_plan(m, cfg["workouts"], bool(flags), PLAN_DAYS)

    analysis = analyse_training(m, flags)
    review = review_and_recommend(m, plan, flags)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = render(m, flags, plan, analysis, review)
    (OUT_DIR / f"{date.today().isoformat()}.md").write_text(report)
    (OUT_DIR / "latest.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
