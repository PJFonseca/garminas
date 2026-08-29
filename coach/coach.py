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
import re
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
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }).encode()

    req = urllib.request.Request(LLM_URL, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
            return json.load(resp)["choices"][0]["message"]["content"].strip()
    except (urllib.error.URLError, KeyError, TimeoutError, OSError) as exc:
        print(f"modelo indisponível ({exc}); secção sai sem comentário", file=sys.stderr)
        return None


NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
LIST_MARKER = re.compile(r"(?m)^\s*\d+[.)]\s*")

SYSTEM = ("És um treinador conciso e honesto. Escreves em português europeu, sem "
          "entusiasmo artificial. Nunca fazes contas: citas apenas números que te "
          "são dados, copiados tal como aparecem.")

STRICTER = ("\n\nA tua resposta anterior continha números que não constam dos dados "
            "acima. Reescreve usando exclusivamente os números listados, tal como "
            "aparecem. Não calcules médias, somas, contagens nem diferenças.")


def _numbers(text: str) -> set[str]:
    out = set()
    for raw in NUMBER.findall(text):
        v = raw.replace(",", ".")
        if "." in v:
            v = v.rstrip("0").rstrip(".")
        out.add(v or "0")
    return out


def write(prompt: str, max_tokens: int = 400) -> str | None:
    """Gera, verifica os números, e insiste uma vez.

    Um 4B conta mal: ao ver dez sessões pede-se-lhe uma leitura e ele responde
    que houve seis de 75 minutos quando houve três. Por isso tudo o que é
    contagem vai já calculado no prompt, e o que sair com números que lá não
    estavam é rejeitado. Num relatório de saúde, texto errado com ar de certeza
    é pior do que secção nenhuma.
    """
    allowed = _numbers(prompt)
    for attempt in (1, 2):
        text = ask_llm(SYSTEM, prompt if attempt == 1 else prompt + STRICTER, max_tokens)
        if text is None:
            return None
        invented = _numbers(LIST_MARKER.sub("", text)) - allowed
        if not invented:
            return text
        print(f"tentativa {attempt}: números fora dos dados {sorted(invented)}",
              file=sys.stderr)
    return None


def describe(label: str, now, base, unit: str = "") -> str:
    """Diz por palavras se um valor está acima, abaixo ou na base.

    O modelo não é capaz de julgar que 51.6 contra 51.4 é 'praticamente igual';
    ao ser-lhe entregue apenas os dois números, escreveu 'em declínio'.
    """
    if now is None or base is None:
        return f"{label}: sem dados"
    rel = abs(now - base) / base if base else 0
    if rel < 0.03:
        word = "praticamente igual à base"
    elif now > base:
        word = "acima da base"
    else:
        word = "abaixo da base"
    return f"{label} {now}{unit}, base de 28 dias {base}{unit} — {word}"


def analyse_training(m: dict, flags: list[str]) -> str | None:
    """Primeira chamada: leitura do que foi efetivamente treinado.

    A lista de sessões não vai no prompt de propósito. Ela está na tabela do
    relatório, para a pessoa ler; ao modelo entregam-se só os totais.
    """
    w7, w14 = m["windows"]["7d"], m["windows"]["14d"]
    rec = m["recovery"]

    return write(f"""Totais já calculados. Não contes nem calcules nada, cita-os como estão.

Últimos 7 dias: {w7['sessions']} sessões, {w7['minutes']} minutos ao todo, {w7['km']} km, média de {w7['mean_min']} minutos por sessão, {w7['hard']} sessões duras, {w7['rest_days']} dias sem treino.
Últimos 14 dias: {w14['sessions']} sessões, {w14['minutes']} minutos ao todo, {w14['km']} km, média de {w14['mean_min']} minutos por sessão, {w14['hard']} sessões duras, {w14['rest_days']} dias sem treino.
Sessão mais longa em 14 dias: {w14['longest_min']} minutos. Mais curta: {w14['shortest_min']} minutos.

Carga de treino: CTL {m['load']['ctl']}, ATL {m['load']['atl']}, TSB {m['load']['tsb']}.
Dias desde a última sessão dura: {m['load']['days_since_hard']}.

{describe('FC de repouso a 7 dias', rec['rhr_7d'], rec['rhr_28d'], ' bpm')}
{describe('HRV a 7 dias', rec['hrv_7d'], rec['hrv_28d'])}
Sono médio a 7 dias: {rec['sleep_h_7d']} horas.
Bandeiras de recuperação ativas: {'; '.join(flags) if flags else 'nenhuma'}.

Escreve duas frases curtas, em português europeu:
1. O que estes totais dizem sobre o treino das últimas duas semanas.
2. Se a carga e a recuperação estão em equilíbrio.

Máximo 100 palavras. Usa no máximo três números, todos retirados da lista acima.""")


def review_and_recommend(m: dict, plan: dict, flags: list[str]) -> str | None:
    """Segunda chamada: 30 dias e justificação do plano já calculado."""
    month = m["month"]
    weeks = "\n".join(
        f"- semana de {w['start']}: {w['sessions']} sessões, {w['minutes']} minutos, "
        f"{w['km']} km, carga {w['load']} (carga é um índice, não minutos)"
        for w in reversed(month["weeks"])
    )
    hard_days = [d["date"] for d in plan["days"] if d["load_est"] >= 85]
    rest_days = [d["date"] for d in plan["days"] if d["id"] == "rest"]
    days = "\n".join(
        f"- {d['date']} ({d['weekday']}): {d['name']}"
        + (f", {d['duration_min']} minutos" if d["duration_min"] else "")
        for d in plan["days"]
    )
    s = plan["summary"]

    return write(f"""Últimas quatro semanas, já calculadas:
{weeks}

Progressão da última semana face à média das anteriores: {month['ramp']} (acima de 1.3 é risco de lesão, abaixo de 0.8 é perda de forma).
Em 28 dias: {month['hard_sessions']} sessões duras e {month['rest_days']} dias sem treino.
Sessão mais longa do período: {month['longest_min']} minutos, {month['longest_km']} km.
Bandeiras de recuperação ativas hoje: {'; '.join(flags) if flags else 'nenhuma'}.

Plano já calculado para os próximos {len(plan['days'])} dias, que deves explicar e
não alterar:
{days}

Dias do plano com sessão dura: {', '.join(hard_days) if hard_days else 'nenhum'}.
Dias do plano sem treino: {', '.join(rest_days) if rest_days else 'nenhum'}.
No total: {s['sessions']} sessões, {s['hard']} duras, {s['minutes']} minutos, e o CTL passa de {s['ctl_start']} para {s['ctl_end']}.

Escreve, em português europeu:
1. A tendência das últimas quatro semanas. Se falares de média semanal, usa
   {month['mean_week_load']} de carga — os outros valores são semanas isoladas.
2. Porque é que o plano acima faz sentido face a essa tendência, em duas frases.

Máximo 100 palavras. Não menciones dias nem sessões que não estejam nas listas acima.""", max_tokens=520)


def table(header: list[str], rows: list[list]) -> list[str]:
    return ["| " + " | ".join(header) + " |",
            "|" + "|".join("---" for _ in header) + "|"] + \
           ["| " + " | ".join("—" if c is None else str(c) for c in r) + " |" for r in rows]


def slow_down_rule(rules: dict) -> str:
    """A regra de travagem sai dos limiares, não do modelo.

    Pedida ao modelo, a resposta saía circular — numa execução, 'o sinal para
    abrandar é a ausência de bandeiras de recuperação'. Os números estão no
    workouts.yaml e não têm de ser adivinhados.
    """
    return (f"Abranda o plano se acontecer qualquer uma destas: a FC de repouso a "
            f"7 dias subir mais de {rules['rhr_delta_above']} bpm acima da base de 28 "
            f"dias, o HRV cair mais de {abs(rules['hrv_drop_pct_below'])}% abaixo da "
            f"base, o sono a 7 dias descer abaixo de {rules['sleep_h_below']} h, ou o "
            f"TSB passar abaixo de {rules['tsb_below']}. Qualquer delas corta o "
            f"catálogo às sessões de recuperação no relatório seguinte. Dor, tonturas "
            f"ou sono partido valem por si, sem esperar por números.")


def render(m: dict, flags: list[str], plan: dict, analysis: str | None,
           review: str | None, rules: dict) -> str:
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
    lines += [analysis or "_Sem texto redigido: ou o modelo não respondeu, ou o que escreveu "
              "continha números que não estão nos dados e foi rejeitado. "
              "Os números e o plano acima são calculados e mantêm-se válidos._"]
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
    lines += [review or "_Sem texto redigido: ou o modelo não respondeu, ou o que escreveu "
              "continha números que não estão nos dados e foi rejeitado. "
              "Os números e o plano acima são calculados e mantêm-se válidos._"]

    lines += ["", "### Quando abrandar", "", slow_down_rule(rules), ""]
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
    report = render(m, flags, plan, analysis, review, cfg['recovery_flags'])
    (OUT_DIR / f"{date.today().isoformat()}.md").write_text(report)
    (OUT_DIR / "latest.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
