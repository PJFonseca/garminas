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
mesma, só que sem as partes redigidas.
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
from assess import ESTADOS, assess, desporto  # noqa: E402
from language import APP, pick  # noqa: E402
from language import t as _t  # noqa: E402
from plan import build_plan, eligible  # noqa: E402

CATALOGUE = Path(__file__).with_name("workouts.yaml")
DATA_DIR = Path(os.environ.get("GARMIN_DATA_DIR", "/data"))
OUT_DIR = Path(os.environ.get("COACH_OUT") or DATA_DIR / "reports")
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


def ask_llm(system: str, prompt: str, max_tokens: int = 400,
            temperature: float = 0.2) -> str | None:
    body = json.dumps({
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
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

LINGUAS_NOME = {
    "en": "English", "pt": "European Portuguese (Portugal, not Brazil)",
    "es": "Spanish", "fr": "French", "de": "German", "it": "Italian",
    "zh": "Simplified Chinese",
}

SYSTEM_EN = """You are a concise, honest coach. You write in {lingua}, without
manufactured enthusiasm.

Register:
- You speak to the person, not about them. Second person.
- Short sentences, twenty words at most.
- Say what to do. Never "you might consider" or "it would be advisable".
- No filler: "it is essential", "it is fundamental", "requires attention", "in
  order to". Cut it and get to the point.
- Never use em dashes. Use a comma, a colon or parentheses instead.
- One number is enough to carry a sentence. Do not introduce it with "as
  demonstrated by the value of".
- You never do arithmetic: you quote only the numbers you are given, exactly as
  they appear."""

SYSTEM = """És um treinador conciso e honesto. Escreves em português europeu de
Portugal, sem entusiasmo artificial.

Regras de língua, obrigatórias:
- Nunca uses gerúndio para ação em curso. Escreve "está a subir", nunca "está
  subindo"; "a manter a base", nunca "mantendo a base".
- Não encadeies gerúndios do género "indicando", "permitindo", "evitando",
  "preservando". Usa orações com "que", "para" ou "porque".
- Vocabulário: treino e não treinamento, desporto e não esporte, planear e não
  planejar, registo e não registro, ecrã e não tela, equipa e não time.
- Não uses travessões. Onde te apetecer um, escolhe vírgula, dois pontos ou
  parênteses.
- Nunca fazes contas: citas apenas números que te são dados, tal como aparecem.

Registo:
- Falas com a pessoa, por tu. Não escreves um relatório sobre ela.
- Frases curtas, no máximo vinte palavras cada.
- Dizes o que fazer. Nunca "podes considerar", "seria aconselhável" nem
  "é recomendável".
- Nada de encher: "é fundamental", "é essencial", "requer atenção", "de forma
  a", "no sentido de", "com o objetivo de". Corta e vai direto.
- Um número chega para sustentar uma frase. Não precisas de o apresentar com
  "como demonstra o valor de"."""


def sistema(ln: str) -> str:
    """As regras de estilo.

    As de português são as únicas escritas na própria língua, porque tratam de
    coisas que só existem em português: o gerúndio contínuo e a colocação do
    pronome. Para as outras línguas as regras vão em inglês, que é o que os
    modelos seguem melhor, com a língua de resposta indicada.
    """
    if ln == "pt":
        return SYSTEM
    return SYSTEM_EN.format(lingua=LINGUAS_NOME.get(ln, "English"))

# Fórmulas de relatório. Todas têm uma versão direta, e um treinador usa a
# direta: "dorme mais" em vez de "é fundamental melhorar a higiene do sono".
CLICHES = [
    "é fundamental", "é essencial", "é importante referir", "é de salientar",
    "requer atenção", "merece atenção especial", "podes considerar",
    "seria aconselhável", "é recomendável", "de forma a", "no sentido de",
    "com o objetivo de", "de modo a", "por conseguinte", "vale a pena referir",
    "como demonstra o valor", "no que diz respeito", "importa referir",
    "de salientar que", "em suma", "por outro lado, é",
    "é crucial", "são cruciais", "é vital", "desempenha um papel",
]

# Palavras que denunciam português do Brasil ou tradução do inglês. A troca é
# segura porque nenhuma delas tem outro sentido em português europeu.
BRASILEIRISMOS = {
    "treinamento": "treino", "treinamentos": "treinos",
    "esporte": "desporto", "esportes": "desportos", "esportiva": "desportiva",
    "planejar": "planear", "planejamento": "planeamento",
    "registro": "registo", "registros": "registos",
    "monitoramento": "monitorização", "usuário": "utilizador",
    "tela": "ecrã", "time": "equipa", "aeróbico": "aeróbio",
    "condicionamento": "condição física", "academia": "ginásio",
    "alongamento": "alongamentos", "performance": "desempenho",
    "estresse": "stress", "alternancia": "alterna", "ginástica": "ginástica",
    "atividades": "atividades", "café": "café",
}

# Em português europeu o pronome vem depois do verbo: "pode adaptar-se", não
# "pode se adaptar". É a marca mais audível do português do Brasil, e nenhuma
# lista de palavras a apanha.
CLITICO_BRASILEIRO = re.compile(
    r"\b(pode|podem|vai|vão|deve|devem|come(?:ça|çam)|costuma|costumam|"
    r"quer|querem|tende|tendem|passa|passam)\s+(se|me|te|nos)\s+\w+", re.I)

# "permitem ao corpo se recuperar": o pronome antes do infinitivo. Em
# português europeu seria "recuperar-se". A lista é curta de propósito, para
# não apanhar o "se" condicional de "se recuperar bem, treina".
REFLEXO_BRASILEIRO = re.compile(
    r"\bse\s+(recuperar|adaptar|sentir|preparar|habituar|ajustar|fortalecer|"
    r"desenvolver|manter|cansar)\b(?!\s*,)", re.I)

# "está subindo" em vez de "está a subir": a construção mais óbvia do
# português do Brasil, e a que um modelo treinado nele produz primeiro.
GERUNDIO_CONTINUO = re.compile(
    r"\b(est(?:á|ão|ava|avam|ou)|vem|vêm|continua|continuam|anda|andam)\s+\w+ndo\b", re.I)
# Nem tudo o que acaba em -ndo é gerúndio: "quando", "fundo" e "segundo" são
# palavras correntes, e "forma de fundo" está no próprio relatório.
NAO_GERUNDIO = {"quando", "fundo", "mundo", "segundo", "profundo", "comando",
                "bando", "brando", "redondo", "tremendo", "estupendo"}
GERUNDIO = re.compile(r"\b\w{3,}(?:ando|endo|indo)\b", re.I)

AVISO_LINGUA = ("\n\nA tua resposta anterior não serve: tinha gerúndios, construções "
                "do português do Brasil, ou fórmulas de relatório. Reescreve sem "
                "nenhum gerúndio, com \"a\" mais infinitivo, e fala diretamente com a "
                "pessoa em frases curtas. Diz o que fazer, sem rodeios.")

STRICTER = ("\n\nA tua resposta anterior continha números que não constam dos dados "
            "acima. Reescreve usando exclusivamente os números listados, tal como "
            "aparecem. Não calcules médias, somas, contagens nem diferenças.")


def aportuguesar(texto: str) -> str:
    """Troca palavras inequivocamente brasileiras pelas europeias."""
    def troca(m):
        palavra = m.group(0)
        nova = BRASILEIRISMOS[palavra.lower()]
        return nova.capitalize() if palavra[0].isupper() else nova

    padrao = re.compile(r"\b(" + "|".join(BRASILEIRISMOS) + r")\b", re.I)
    return padrao.sub(troca, texto)


def portugues_europeu(texto: str, ln: str = "pt") -> tuple[bool, str]:
    """Rejeita o que soa a tradução. Devolve o motivo, para o registo.

    Travessões e fórmulas de relatório valem para qualquer língua. Os gerúndios
    e o pronome antes do verbo são defeitos do português, e correr essas
    verificações sobre italiano ou espanhol daria falsos positivos a torto e a
    direito.
    """
    if "-" in texto or "-" in texto:
        return False, "travessão"
    if ln != "pt":
        return True, ""
    if GERUNDIO_CONTINUO.search(texto):
        return False, "construção 'estar + gerúndio'"
    for padrao in (CLITICO_BRASILEIRO, REFLEXO_BRASILEIRO):
        achado = padrao.search(texto)
        if achado:
            return False, f"pronome antes do verbo: '{achado.group(0)}'"
    gerundios = [g for g in GERUNDIO.findall(texto) if g.lower() not in NAO_GERUNDIO]
    if gerundios:
        return False, "gerúndio: " + ", ".join(sorted(set(gerundios)))
    achados = [c for c in CLICHES if c in texto.lower()]
    if achados:
        return False, "fórmula de relatório: " + ", ".join(achados)
    restos = [p for p in BRASILEIRISMOS if re.search(rf"\b{p}\b", texto, re.I)]
    if restos:
        return False, "vocabulário: " + ", ".join(restos)
    return True, ""


def _numbers(text: str) -> set[str]:
    out = set()
    for raw in NUMBER.findall(text):
        v = raw.replace(",", ".")
        if "." in v:
            v = v.rstrip("0").rstrip(".")
        out.add(v or "0")
    return out


def write(prompt: str, max_tokens: int = 400, ln: str = "en") -> str | None:
    """Gera, verifica os números, e insiste uma vez.

    Um 4B conta mal: ao ver dez sessões pede-se-lhe uma leitura e ele responde
    que houve seis de 75 minutos quando houve três. Por isso tudo o que é
    contagem vai já calculado no prompt, e o que sair com números que lá não
    estavam é rejeitado. Num relatório de saúde, texto errado com ar de certeza
    é pior do que secção nenhuma.
    """
    allowed = _numbers(prompt)
    reforco = ""
    melhor = None
    for attempt in (1, 2, 3):
        text = ask_llm(sistema(ln), prompt + reforco, max_tokens,
                       temperature=0.2 + 0.2 * (attempt - 1))
        if text is None:
            return None

        invented = _numbers(LIST_MARKER.sub("", text)) - allowed
        if invented:
            print(f"tentativa {attempt}: números fora dos dados {sorted(invented)}",
                  file=sys.stderr)
            reforco = STRICTER
            continue

        if ln == "pt":
            text = aportuguesar(text)
        ok, motivo = portugues_europeu(text, ln)
        if ok:
            return text
        print(f"tentativa {attempt}: não é português europeu ({motivo})", file=sys.stderr)
        melhor = melhor or text        # guardar o primeiro sem números inventados
        reforco = AVISO_LINGUA

    # Os números estão certos e a língua não está perfeita: vale mais o texto
    # aportuguesado do que secção nenhuma. O contrário, números errados, é
    # que não se aceita.
    return melhor


def ramp_verdict(ramp, ln: str = "en") -> str:
    """Diz o que a progressão significa, em vez de deixar o modelo comparar.

    Entregue apenas o número e a regra, o modelo escreveu que 0.65 estava
    'dentro do intervalo seguro (acima de 0.8 é perda de forma)', a
    conclusão oposta ao que os seus próprios dados diziam.
    """
    if ramp is None:
        return _t("v.ramp.sem", ln)
    if ramp > 1.3:
        return _t("v.ramp.alerta", ln, r=ramp)
    if ramp < 0.8:
        return _t("v.ramp.leve", ln, r=ramp)
    return _t("v.ramp.bom", ln, r=ramp)


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
    return f"{label} {now}{unit}, base de 28 dias {base}{unit}, {word}"


def analyse_training(m: dict, flags: list[str], ln: str = "en") -> str | None:
    """Primeira chamada: pôr por palavras as leituras já calculadas.

    O modelo não interpreta nada. Deu-se-lhe uma vez os números crus e ele
    concluiu que HRV acima da base mais FC de repouso abaixo da base era
    "desequilíbrio entre esforço e recuperação", dois sinais bons lidos como
    mau. Agora recebe o veredicto de cada métrica, feito em assess.py, e o
    seu trabalho é só escrevê-lo de forma corrida.
    """
    w14 = m["windows"]["14d"]
    def uma(f: dict) -> str:
        linha = (f"- {f['titulo']}: {f['valor']}"
                 f"{' ' + f['unidade'] if f['unidade'] else ''}, "
                 f"{f.get('rotulo') or ''}, {f['leitura']}")
        if f.get("alvo"):
            linha += f". Onde devia estar: {f['alvo']}"
        if f.get("acao"):
            linha += f". O que fazer: {f['acao']}"
        return linha

    leituras = "\n".join(uma(f) for f in assess(m, ln))

    return write(f"""Leituras já feitas, com o veredicto de cada uma. Não as
reinterpretes nem tires conclusões novas: o teu trabalho é escrevê-las de forma
corrida.

{leituras}

Contexto: nos últimos 14 dias foram {w14['sessions']} sessões, {w14['minutes']} minutos
ao todo e {w14['rest_days']} dias sem treino.
Bandeiras de recuperação ativas: {'; '.join(flags) if flags else 'nenhuma'}.

Write two sentences. No numbering, no list.

Do not walk through the metrics one by one: they are already on the same page,
and repeating them adds nothing. Say what the set of them means: the single
thing most limiting this training right now, and what changes if it is dealt
with.

At most 60 words. Use at most two numbers, copied from the list. Careful: a
metric's current value is not its target. If you tell someone how much to
sleep, use the number under "where it should be", never what they sleep now.

Write your answer in {LINGUAS_NOME.get(ln, "English")}.""", ln=ln)


def comentar_sessao(m: dict, ln: str = "en") -> str | None:
    """Duas frases sobre o treino que acabou de ser feito.

    As comparações vêm feitas do metrics.py. Ao modelo cabe juntá-las numa
    coisa que se leia, não descobri-las.
    """
    s = m.get("sessao") or {}
    if not s.get("has_data") or not s.get("notas"):
        return None

    factos = "\n".join(f"- {n}" for n in s["notas"])
    return write(f"""Acabaste de registar esta sessão:
{desporto(s['sport'], ln)}, {s['minutes']} minutos, {s['km']} km\
{f", {s['kmh']} km/h" if s.get('kmh') else ''}\
{f", FC média {s['avg_hr']}" if s.get('avg_hr') else ''}, carga {s['load']}.

Comparações já feitas, que não deves refazer:
{factos}

Veredicto já decidido: {s['veredicto']}

Write two sentences, speaking to the person. The first says how it went, with
one concrete comparison from the list. The second says what that means for the
next few days.

At most 45 words. Do not invent numbers or comparisons outside the list.

Write your answer in {LINGUAS_NOME.get(ln, "English")}.""",
                 max_tokens=220, ln=ln)


def review_and_recommend(m: dict, plan: dict, flags: list[str], ln: str = "en") -> str | None:
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

    return write(f"""Nas últimas quatro semanas treinaste, por semana e em média, \
{month['mean_week_minutes']} minutos.
Bandeiras de recuperação ativas hoje: {'; '.join(flags) if flags else 'nenhuma'}.

Plano já calculado para os próximos {len(plan['days'])} dias, que deves explicar e
não alterar:
{days}

Dias do plano com sessão dura: {', '.join(hard_days) if hard_days else 'nenhum'}.
Dias do plano sem treino: {', '.join(rest_days) if rest_days else 'nenhum'}.
No total: {s['sessions']} sessões, {s['hard']} duras, {s['minutes']} minutos.

Write, without numbering:
One paragraph explaining the logic of this plan: why the hard sessions sit
where they sit, and what the days without training are for.
Then one sentence on what to watch during the sessions.

At most 90 words. Do not judge fitness or progression: that is said elsewhere
in the report. Do not mention days or sessions outside the lists.

Write your answer in {LINGUAS_NOME.get(ln, "English")}.""",
                 max_tokens=420, ln=ln)


def table(header: list[str], rows: list[list]) -> list[str]:
    return ["| " + " | ".join(header) + " |",
            "|" + "|".join("---" for _ in header) + "|"] + \
           ["| " + " | ".join("" if c is None else str(c) for c in r) + " |" for r in rows]


def slow_down_rule(rules: dict, ln: str = "en") -> str:
    """A regra de travagem sai dos limiares, não do modelo.

    Pedida ao modelo, a resposta saía circular, numa execução, 'o sinal para
    abrandar é a ausência de bandeiras de recuperação'. Os números estão no
    workouts.yaml e não têm de ser adivinhados.
    """
    return _t("v.abrandar", ln, rhr=rules["rhr_delta_above"],
              hrv=abs(rules["hrv_drop_pct_below"]), sono=rules["sleep_h_below"],
              tsb=rules["tsb_below"])


def render(m: dict, flags: list[str], plan: dict, analysis: str | None,
           review: str | None, rules: dict, objetivo: dict | None = None,
           ln: str = "en") -> str:
    load, rec, month = m["load"], m["recovery"], m["month"]
    today = plan["days"][0]

    lines = [f"# {_t('ui.treino', ln)}, {m['generated']}", ""]

    lines += [f"## {_t('md.estado', ln)}", ""]
    lines += table([_t("md.metrica", ln), _t("md.valor", ln),
                    _t("md.leitura", ln), _t("md.porque_col", ln)],
                   [[f["titulo"], f"{f['valor']} {f['unidade']}".strip(),
                     f.get("rotulo") or "", f["leitura"]]
                    for f in assess(m, ln)])
    lines += ["", _t("md.atl", ln, atl=load["atl"], n=load["sessions_7d"]), ""]

    if flags:
        lines += ["## Bandeiras de recuperação", ""]
        lines += [f"- {f}" for f in flags]
        lines += ["", "Enquanto durarem, só ficam elegíveis sessões de recuperação.", ""]

    lines += [f"## {_t('ui.recentes', ln)}", ""]
    if m["recent"]:
        lines += table([_t("th.data", ln), _t("th.desporto", ln), _t("th.min", ln),
                        _t("th.km", ln), _t("th.fc", ln), _t("th.carga", ln)],
                       [[s["date"], desporto(s["sport"], ln), s["minutes"], s["km"] or None,
                         s["avg_hr"], s["load"]] for s in m["recent"]])
    else:
        lines += ["Sem sessões registadas."]
    lines += [""]

    lines += [f"## {_t('ui.analise', ln)}", ""]
    lines += [analysis or "_Sem texto redigido: ou o modelo não respondeu, ou o que escreveu "
              "continha números que não estão nos dados e foi rejeitado. "
              "Os números e o plano acima são calculados e mantêm-se válidos._"]
    lines += [""]

    lines += [f"## {_t('ui.carga_semana', ln)}", ""]
    lines += table([_t("th.semana", ln), _t("th.sessoes", ln), _t("th.minutos", ln),
                    _t("th.km", ln), _t("th.carga", ln)],
                   [[w["start"], w["sessions"], w["minutes"], w["km"], w["load"]]
                    for w in reversed(month["weeks"])])
    duras = month["hard_sessions"]
    lines += ["", f"Progressão: **{ramp_verdict(month['ramp'])}**. "
                  f"{duras} {'sessão dura' if duras == 1 else 'sessões duras'}, "
                  f"{month['rest_days']} dias sem treino, "
                  f"sessão mais longa {month['longest_min']} min.", ""]

    feito_hoje = next((s for s in m["recent"] if s["date"] == m["generated"]), None)
    seguinte = plan["days"][0]
    quando = (_t("ui.hoje", ln) if seguinte["date"] == m["generated"]
              else f"{_t('ui.amanha', ln)}, {seguinte['weekday']}")
    lines += [f"## {_t('md.a_seguir', ln, quando=quando, data=seguinte['date'])}", "",
              f"**{seguinte['name']}**"
              + (f", {seguinte['duration_min']} min" if seguinte["duration_min"] else "") + "", ""]
    if seguinte.get("ritmo"):
        lines += [f"**{seguinte['ritmo']}**", ""]
    if seguinte.get("description"):
        lines += [seguinte["description"], ""]
    if seguinte.get("motivo"):
        lines += [_t("md.porque", ln, motivo=seguinte["motivo"]), ""]

    lines += [f"## {_t('ui.hoje', ln)}", ""]
    if feito_hoje:
        lines += [_t("md.ja_treinaste", ln, desporto=desporto(feito_hoje["sport"], ln),
                     min=feito_hoje["minutes"],
                     km=f", {feito_hoje['km']} km" if feito_hoje["km"] else "",
                     carga=feito_hoje["load"]), ""]
    else:
        lines += [f"**{today['name']}**"
                  + (f", {today['duration_min']} min" if today["duration_min"] else "") + ".", ""]

    s = plan["summary"]
    lines += [f"## {_t('ui.plano', ln, n=len(plan['days']))}", ""]
    lines += table([_t("th.data", ln), _t("md.dia", ln), _t("md.sessao", ln),
                    _t("th.min", ln), _t("md.tsb_proj", ln)],
                   [[d["date"], d["weekday"], d["name"], d["duration_min"], d["tsb_after"]]
                    for d in plan["days"]])
    lines += ["", f"{s['sessions']} sessões, {s['hard']} duras, {s['minutes']} minutos. "
                  f"CTL projetado de {s['ctl_start']} para {s['ctl_end']}, "
                  f"TSB no fim {s['tsb_end']}.", ""]
    if (objetivo or {}).get("perder_peso"):
        lines += ["Com o objetivo de perder peso, os dias de descanso a mais passam a caminhada: "
                  "gasta energia e quase não cobra recuperação. A intensidade fica na mesma. "
                  "O treino ajuda, mas a diferença maior vem da alimentação, que este relatório "
                  "não vê.", ""]

    lines += [f"## {_t('ui.recomendacao', ln)}", ""]
    lines += [review or "_Sem texto redigido: ou o modelo não respondeu, ou o que escreveu "
              "continha números que não estão nos dados e foi rejeitado. "
              "Os números e o plano acima são calculados e mantêm-se válidos._"]

    lines += ["", f"### {_t('ui.quando_abrandar', ln)}", "", slow_down_rule(rules, ln), ""]
    lines += ["", "---", "",
              "Orientação genérica gerada a partir dos teus próprios dados. "
              "Não substitui acompanhamento clínico ou de um treinador, "
              "sobretudo se houver dor, tonturas ou sintomas persistentes."]
    return "\n".join(lines)


def idioma_do_perfil() -> str:
    """A língua sai do perfil; COACH_LANG serve para testar."""
    if os.environ.get("COACH_LANG"):
        return pick(os.environ["COACH_LANG"])
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import profiles
        return pick((profiles.read(DATA_DIR) or {}).get("language"))
    except Exception:                            # noqa: BLE001
        return "en"


def main() -> None:
    cfg = yaml.safe_load(CATALOGUE.read_text())
    ln = idioma_do_perfil()
    m = build(connect())

    if m["coverage"]["activities"] == 0:
        sys.exit("Sem atividades na base de dados. Correr a sincronização primeiro.")

    flags = check_flags(m, cfg["recovery_flags"])
    ja_treinou_hoje = any(s["date"] == m["generated"] for s in m["recent"])
    plan = build_plan(m, cfg["workouts"], bool(flags), PLAN_DAYS,
                      skip_today=ja_treinou_hoje, objetivo=cfg.get("objetivo"),
                      extras=cfg, ln=ln)

    sessao = comentar_sessao(m, ln)
    analysis = analyse_training(m, flags, ln)
    review = review_and_recommend(m, plan, flags, ln)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = render(m, flags, plan, analysis, review, cfg["recovery_flags"],
                    cfg.get("objetivo"), ln)
    stamp = date.today().isoformat()
    (OUT_DIR / f"{stamp}.md").write_text(report)
    (OUT_DIR / "latest.md").write_text(report)

    # O mesmo relatório em dados, para a página web o desenhar como quiser.
    # O markdown continua a ser a versão canónica, legível no terminal e por
    # um assistente; o JSON evita que a web tenha de o voltar a interpretar.
    payload = {
        "generated": m["generated"],
        "metrics": m,
        "plan": plan,
        "flags": flags,
        "analysis": analysis,
        "review": review,
        "ramp_verdict": ramp_verdict(m["month"]["ramp"], ln),
        "slow_down": slow_down_rule(cfg["recovery_flags"], ln),
        "idioma": ln,
        "today_done": next((s for s in m["recent"] if s["date"] == m["generated"]), None),
        "assessment": assess(m, ln),
        "sessao_comentario": sessao,
        "objetivo": cfg.get("objetivo") or {},
    }
    for name in (f"{stamp}.json", "latest.json"):
        (OUT_DIR / name).write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    print(report)


if __name__ == "__main__":
    main()
