#!/usr/bin/env python3
"""Gera o relatório diário de treino.

Divisão de responsabilidades:
  metrics.py    calcula os números
  workouts.yaml define o catálogo e as regras
  este ficheiro filtra candidatos e pede ao modelo que escolha e redija

O modelo nunca calcula, nunca inventa sessões, e nunca decide sozinho ignorar
uma bandeira de recuperação. Se o modelo estiver em baixo, o relatório sai na
mesma — só que sem a parte redigida.
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

CATALOGUE = Path(__file__).with_name("workouts.yaml")
OUT_DIR = Path(os.environ.get("COACH_OUT", "/data/reports"))
LLM_URL = os.environ.get("LLM_URL", "http://llm:8080/v1/chat/completions")
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "600"))


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


def eligible(catalogue: list[dict], m: dict, flagged: bool) -> list[dict]:
    load = m["load"]
    dsh = load["days_since_hard"]
    out = []

    for w in catalogue:
        if flagged and not w.get("recovery_safe"):
            continue
        if w.get("requires_fresh") and flagged:
            continue
        if "tsb_min" in w and load["tsb"] < w["tsb_min"]:
            continue
        if "tsb_max" in w and load["tsb"] > w["tsb_max"]:
            continue
        if "ctl_min" in w and load["ctl"] < w["ctl_min"]:
            continue
        if "days_since_hard_min" in w and dsh is not None and dsh < w["days_since_hard_min"]:
            continue
        out.append(w)
    return out


def ask_llm(m: dict, candidates: list[dict], flags: list[str]) -> str | None:
    options = "\n".join(
        f"- {w['id']}: {w['name']} — {' '.join(w.get('description', '').split())}"
        for w in candidates
    )
    prompt = f"""Métricas de hoje (já calculadas, usa-as tal como estão):

Carga: CTL {m['load']['ctl']}, ATL {m['load']['atl']}, TSB {m['load']['tsb']}
Últimos 7 dias: {m['load']['sessions_7d']} sessões, {m['load']['minutes_7d']} minutos
Dias desde a última sessão dura: {m['load']['days_since_hard']}
Recuperação: FC repouso 7d {m['recovery']['rhr_7d']}, HRV 7d {m['recovery']['hrv_7d']}, sono 7d {m['recovery']['sleep_h_7d']} h
Bandeiras ativas: {'; '.join(flags) if flags else 'nenhuma'}

Sessões elegíveis para hoje:
{options}

Escolhe exatamente uma da lista e escreve, em português europeu:
1. Uma frase sobre o estado atual, citando um número concreto acima.
2. A sessão escolhida e porquê, em duas frases.
3. Um sinal a vigiar durante o treino.

Máximo 120 palavras. Não inventes números nem sessões fora da lista."""

    body = json.dumps({
        "messages": [
            {"role": "system", "content": "És um treinador conciso. Escreves em português europeu."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.4,
        "max_tokens": 320,
    }).encode()

    req = urllib.request.Request(LLM_URL, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
            return json.load(resp)["choices"][0]["message"]["content"].strip()
    except (urllib.error.URLError, KeyError, TimeoutError) as exc:
        print(f"modelo indisponível ({exc}); relatório sai sem comentário", file=sys.stderr)
        return None


def render(m: dict, flags: list[str], candidates: list[dict], comment: str | None) -> str:
    load, rec = m["load"], m["recovery"]
    lines = [
        f"# Treino — {m['generated']}",
        "",
        "## Estado",
        "",
        f"| Métrica | Valor |",
        f"|---|---|",
        f"| CTL (forma de fundo) | {load['ctl']} |",
        f"| ATL (fadiga recente) | {load['atl']} |",
        f"| TSB (frescura) | {load['tsb']} |",
        f"| Sessões / minutos, 7 dias | {load['sessions_7d']} / {load['minutes_7d']} |",
        f"| Dias desde sessão dura | {load['days_since_hard']} |",
        f"| FC repouso 7d vs 28d | {rec['rhr_7d']} vs {rec['rhr_28d']} |",
        f"| HRV 7d vs 28d | {rec['hrv_7d']} vs {rec['hrv_28d']} |",
        f"| Sono médio 7d | {rec['sleep_h_7d']} h |",
        "",
    ]

    if flags:
        lines += ["## Bandeiras de recuperação", ""]
        lines += [f"- {f}" for f in flags]
        lines += ["", "Só ficaram elegíveis sessões de recuperação.", ""]

    lines += ["## Sugestão", ""]
    lines += [comment if comment else
              "Modelo indisponível. Candidatos elegíveis hoje: "
              + ", ".join(w["name"] for w in candidates) + "."]
    lines += [
        "",
        "---",
        "",
        "Orientação genérica gerada a partir dos teus próprios dados. "
        "Não substitui acompanhamento clínico ou de um treinador, "
        "sobretudo se houver dor, tonturas ou sintomas persistentes.",
    ]
    return "\n".join(lines)


def main() -> None:
    cfg = yaml.safe_load(CATALOGUE.read_text())
    con = connect()
    m = build(con)

    if m["coverage"]["activities"] == 0:
        sys.exit("Sem atividades na base de dados. Correr a sincronização primeiro.")

    flags = check_flags(m, cfg["recovery_flags"])
    candidates = eligible(cfg["workouts"], m, bool(flags))
    comment = ask_llm(m, candidates, flags) if candidates else None

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = render(m, flags, candidates, comment)
    (OUT_DIR / f"{date.today().isoformat()}.md").write_text(report)
    (OUT_DIR / "latest.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
