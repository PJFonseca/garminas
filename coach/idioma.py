#!/usr/bin/env python3
"""Idioma do relatório, tirado da conta Garmin de cada pessoa.

A conta traz um locale. Se disser português, o relatório sai em português; em
qualquer outro caso sai em inglês, que é o que a Garmin usa por omissão e o
que serve a mais gente.

Cada perfil tem o seu idioma, porque numa casa pode haver contas diferentes.
COACH_LANG força um idioma, para testar.
"""

from __future__ import annotations

import os

APP = "GarmiNAS"
IDIOMAS = ("en", "pt")


def escolher(idioma: str | None = None) -> str:
    """Normaliza o locale da conta para uma das línguas que existem aqui.

    A Garmin devolve coisas como "pt", "pt-BR", "en-GB" ou "zh-CN". Interessa
    só a parte antes do traço; o que não estiver traduzido cai para inglês.
    """
    pedido = (idioma or os.environ.get("COACH_LANG") or "en").lower()
    base = pedido.replace("_", "-").split("-")[0]
    return base if base in linguas() else "en"


F = {
    # ── estados das leituras ────────────────────────────────────────────────
    "estado.bom": ("bom", "good"),
    "estado.atencao": ("a vigiar", "watch"),
    "estado.cuidado": ("a corrigir", "fix this"),
    "estado.alerta": ("alerta", "alert"),

    # ── títulos das métricas ────────────────────────────────────────────────
    "m.tsb": ("Frescura", "Freshness"),
    "m.ctl": ("Forma de fundo", "Fitness"),
    "m.rhr": ("FC de repouso", "Resting heart rate"),
    "m.hrv": ("HRV", "HRV"),
    "m.sono": ("Sono", "Sleep"),
    "m.ramp": ("Progressão", "Weekly ramp"),
    "m.dsh": ("Dias desde sessão dura", "Days since a hard session"),
    "m.vol": ("Volume 7 dias", "Volume, 7 days"),
    "m.peso": ("Peso", "Weight"),

    # ── glosas ──────────────────────────────────────────────────────────────
    "g.tsb": ("TSB, a forma menos a fadiga", "TSB, fitness minus fatigue"),
    "g.ctl": ("CTL, média da carga a 42 dias. Há quatro semanas estava em {antes}",
              "CTL, 42-day load average. Four weeks ago it was {antes}"),
    "g.base": ("média a 7 dias. Base de 28 dias: {base}. Diferença: {delta}",
               "7-day average. 28-day baseline: {base}. Difference: {delta}"),
    "g.sono": ("média das últimas 7 noites", "average of the last 7 nights"),
    "g.ramp": ("carga da última semana a dividir pela média das anteriores",
               "last week's load divided by the average of the weeks before"),
    "g.dsh": ("uma sessão dura é carga de 100 ou mais", "a hard session is load 100 or more"),
    "g.vol": ("média das semanas com treino: {media} min",
              "average of weeks with training: {media} min"),
    "g.peso": ("pesagem de {data}", "weighed on {data}"),
    "g.sem_dados": ("sem dados suficientes", "not enough data"),

    # ── leituras ────────────────────────────────────────────────────────────
    "l.tsb.alerta": ("fadiga a acumular mais depressa do que a recuperação",
                     "fatigue is building faster than you recover"),
    "l.tsb.atencao": ("cansaço normal de quem está a construir carga",
                      "the normal tiredness of building load"),
    "l.tsb.equilibrio": ("carga e recuperação em equilíbrio", "load and recovery are balanced"),
    "l.tsb.fresco": ("fresco, bom momento para uma sessão exigente",
                     "fresh, a good moment for a demanding session"),
    "l.tsb.parado": ("demasiado fresco, já se perde forma por falta de treino",
                     "too fresh, you are losing fitness for lack of training"),
    "l.ctl.sobe": ("a subir {delta} em quatro semanas, estás a ganhar base",
                   "up {delta} in four weeks, you are building a base"),
    "l.ctl.estavel": ("estável em quatro semanas, a manter a base",
                      "flat over four weeks, holding the base"),
    "l.ctl.desce": ("a descer {delta} em quatro semanas", "down {delta} in four weeks"),
    "l.ctl.cai": ("a descer {delta} em quatro semanas, a perder base aeróbia",
                  "down {delta} in four weeks, losing aerobic base"),
    "l.rhr.alto": ("{d} bpm acima da base: o corpo está a pedir descanso",
                   "{d} bpm above baseline: your body is asking for rest"),
    "l.rhr.medio": ("{d} bpm acima da base, a vigiar nos próximos dias",
                    "{d} bpm above baseline, worth watching over the next few days"),
    "l.rhr.normal": ("na base habitual", "at your usual baseline"),
    "l.rhr.baixo": ("{d} bpm abaixo da base, sinal de boa recuperação",
                    "{d} bpm below baseline, a sign of good recovery"),
    "l.hrv.alerta": ("{pct}% abaixo da base: sistema nervoso sob stress",
                     "{pct}% below baseline: your nervous system is under stress"),
    "l.hrv.baixo": ("{pct}% abaixo da base", "{pct}% below baseline"),
    "l.hrv.normal": ("na base habitual", "at your usual baseline"),
    "l.hrv.alto": ("{pct} acima da base, boa recuperação",
                   "{pct} above baseline, good recovery"),
    "l.sono.alerta": ("abaixo de 6 horas o treino deixa de render, por muito bem feito que seja",
                      "below 6 hours training stops paying off, however well you do it"),
    "l.sono.curto": ("curto. Abaixo de 6 horas o plano passa a só sugerir sessões leves",
                     "short. Below 6 hours the plan will only suggest easy sessions"),
    "l.sono.aceitavel": ("aceitável, mas há margem para melhorar",
                         "acceptable, but there is room to improve"),
    "l.sono.bom": ("suficiente para sustentar a carga", "enough to sustain the load"),
    "l.ramp.alerta": ("salto grande de mais face às semanas anteriores",
                      "far too big a jump on the weeks before"),
    "l.ramp.alto": ("acima de 1.3, o intervalo onde as lesões aparecem",
                    "above 1.3, the range where injuries show up"),
    "l.ramp.bom": ("entre 0.8 e 1.3, progressão sustentável",
                   "between 0.8 and 1.3, a sustainable ramp"),
    "l.ramp.leve": ("abaixo de 0.8: semana mais leve do que as anteriores",
                    "below 0.8: a lighter week than the ones before"),
    "l.ramp.muito_leve": ("muito abaixo das semanas anteriores, a forma vai cair",
                          "far below the previous weeks, fitness will drop"),
    "l.dsh.muito": ("há muito sem estímulo intenso; a velocidade perde-se primeiro",
                    "a long time without hard work; speed is the first thing to go"),
    "l.dsh.algum": ("já vai longe sem uma sessão exigente",
                    "it has been a while since a demanding session"),
    "l.dsh.recente": ("sessão dura muito recente, cuidado com a seguinte",
                      "a hard session very recently, take care with the next one"),
    "l.dsh.bom": ("espaçamento adequado", "well spaced"),
    "l.dsh.nenhuma": ("sem nenhuma sessão dura no histórico recente",
                      "no hard session in the recent history"),
    "l.vol.baixo": ("bem abaixo da média do mês ({media} min)",
                    "well below the month's average ({media} min)"),
    "l.vol.alto": ("bem acima da média do mês ({media} min)",
                   "well above the month's average ({media} min)"),
    "l.vol.bom": ("em linha com a média do mês ({media} min)",
                  "in line with the month's average ({media} min)"),
    "l.vol.sem_base": ("sem histórico para comparar", "no history to compare against"),
    "l.peso.velho": ("a última pesagem foi há {dias} dias, não dá para ver tendência",
                     "the last weigh-in was {dias} days ago, too old to show a trend"),
    "l.peso.poucas": ("poucas pesagens para calcular uma tendência",
                      "too few weigh-ins to work out a trend"),
    "l.peso.rapido": ("a descer {kg} kg por semana, depressa de mais",
                      "down {kg} kg a week, too fast"),
    "l.peso.certo": ("a descer {kg} kg por semana, no ritmo certo",
                     "down {kg} kg a week, at the right rate"),
    "l.peso.estavel": ("praticamente estável nas últimas semanas",
                       "essentially flat over the last few weeks"),
    "l.peso.sobe": ("a subir {kg} kg por semana", "up {kg} kg a week"),

    # ── alvos ───────────────────────────────────────────────────────────────
    "a.tsb": ("confortável entre −10 e +5. Acima de +25 já é falta de treino",
              "comfortable between −10 and +5. Above +25 is undertraining"),
    "a.ctl": ("o que interessa é a direção, a subir devagar e sem saltos",
              "direction is what matters: up slowly, without jumps"),
    "a.rhr": ("normal até 2 bpm acima da base", "normal up to 2 bpm above baseline"),
    "a.hrv": ("normal entre −5% e +5% da base", "normal between −5% and +5% of baseline"),
    "a.sono": ("7 horas ou mais sustentam a carga de treino",
               "7 hours or more sustains the training load"),
    "a.ramp": ("sustentável entre 0.8 e 1.3", "sustainable between 0.8 and 1.3"),
    "a.dsh": ("entre 2 e 14 dias mantém o estímulo sem acumular fadiga",
              "2 to 14 days keeps the stimulus without piling up fatigue"),
    "a.vol": ("entre 60% e 140% da média do mês",
              "between 60% and 140% of the month's average"),
    "a.peso": ("perder entre {min} e {max} kg por semana",
               "lose between {min} and {max} kg a week"),

    # ── ações ───────────────────────────────────────────────────────────────
    "ac.tsb.descansar": ("Precisas de dias fáceis antes da próxima sessão dura.",
                         "You need easy days before the next hard session."),
    "ac.tsb.treinar": ("Aproveita para treinar a sério.", "Use it: train properly."),
    "ac.ctl": ("Acrescenta uma sessão fácil por semana antes de acrescentar intensidade.",
               "Add one easy session a week before adding any intensity."),
    "ac.rhr": ("Trata como sinal de fadiga ou infeção: descansa e reavalia amanhã.",
               "Treat it as fatigue or illness: rest and check again tomorrow."),
    "ac.hrv": ("Dorme mais e adia a próxima sessão dura em um ou dois dias.",
               "Sleep more and push the next hard session back a day or two."),
    "ac.sono": ("Deitar meia hora mais cedo rende mais do que qualquer sessão extra.",
                "Half an hour earlier to bed pays more than any extra session."),
    "ac.ramp.subir": ("Sobe o volume devagar, cerca de 10% por semana.",
                      "Raise the volume slowly, around 10% a week."),
    "ac.ramp.segurar": ("Segura a próxima semana no mesmo volume.",
                        "Hold next week at the same volume."),
    "ac.dsh.meter": ("Mete intervalos ou um contínuo forte esta semana.",
                     "Put in intervals or a hard steady run this week."),
    "ac.dsh.esperar": ("Deixa passar mais um dia fácil.", "Give it one more easy day."),
    "ac.vol.falta": ("Falta volume face ao teu normal.", "You are short of your usual volume."),
    "ac.vol.demais": ("Semana pesada: a seguinte deve ser mais leve.",
                      "Heavy week: the next one should be lighter."),
    "ac.peso.pesar": ("Pesa-te uma vez por semana, em jejum e sempre à mesma hora.",
                      "Weigh yourself once a week, fasted, always at the same time."),
    "ac.peso.pesar_mais": ("Pesa-te uma vez por semana para o plano poder acompanhar.",
                           "Weigh in weekly so the plan can follow along."),
    "ac.peso.comer": ("Come mais nos dias de treino: a esta velocidade perde-se músculo.",
                      "Eat more on training days: at this rate you lose muscle."),
    "ac.peso.mesa": ("O plano acrescenta volume fácil; a diferença maior vem da mesa.",
                     "The plan adds easy volume; the bigger difference comes from the kitchen."),
    "ac.peso.olhar": ("Vale a pena olhar para a alimentação antes de acrescentar treino.",
                      "Worth looking at food before adding more training."),
}


# ── veredictos e frases longas do relatório ─────────────────────────────────
F.update({
    "v.ramp.sem": ("sem semanas anteriores suficientes para comparar",
                   "not enough previous weeks to compare against"),
    "v.ramp.alerta": ("{r}, acima de 1.3: subida rápida de mais, território de lesão",
                      "{r}, above 1.3: rising too fast, injury territory"),
    "v.ramp.leve": ("{r}, abaixo de 0.8: a semana passada ficou aquém, está a perder forma",
                    "{r}, below 0.8: last week fell short, you are losing fitness"),
    "v.ramp.bom": ("{r}, entre 0.8 e 1.3: progressão saudável",
                   "{r}, between 0.8 and 1.3: a healthy ramp"),
    "v.abrandar": ("Abranda o plano se acontecer alguma destas coisas: a FC de repouso a 7 dias "
                   "subir mais de {rhr} bpm acima da base de 28 dias, o HRV cair mais de {hrv}% "
                   "abaixo da base, o sono a 7 dias descer abaixo de {sono} h, ou o TSB passar "
                   "abaixo de {tsb}. Se alguma acontecer, o relatório do dia seguinte passa a "
                   "sugerir apenas sessões leves. Dor, tonturas ou sono partido valem por si, "
                   "sem esperar por números.",
                   "Ease off the plan if any of these happens: your 7-day resting heart rate "
                   "rises more than {rhr} bpm above the 28-day baseline, HRV drops more than "
                   "{hrv}% below baseline, 7-day sleep falls below {sono} h, or TSB goes below "
                   "{tsb}. If one of them does, the next day's report will suggest easy sessions "
                   "only. Pain, dizziness or broken sleep count on their own, without waiting "
                   "for numbers."),
    "md.estado": ("Estado", "Status"),
    "md.a_seguir": ("A seguir: {quando}, {data}", "Next up: {quando}, {data}"),
    "md.porque": ("Porquê esta: {motivo}.", "Why this one: {motivo}."),
    "md.atl": ("ATL (fadiga recente) {atl}, {n} sessões nos últimos 7 dias.",
               "ATL (recent fatigue) {atl}, {n} sessions in the last 7 days."),
    "md.ja_treinaste": ("Já treinaste: **{desporto}**, {min} min{km}, carga {carga}. "
                        "O plano abaixo começa amanhã.",
                        "You already trained: **{desporto}**, {min} min{km}, load {carga}. "
                        "The plan below starts tomorrow."),
    "md.leitura": ("Leitura", "Reading"), "md.porque_col": ("Porquê", "Why"),
    "md.metrica": ("Métrica", "Metric"), "md.valor": ("Valor", "Value"),
    "md.dia": ("Dia", "Day"), "md.sessao": ("Sessão", "Session"),
    "md.tsb_proj": ("TSB projetado", "Projected TSB"),
})

# ── interface do relatório ──────────────────────────────────────────────────
F.update({
    "ui.treino": ("Treino", "Training"),
    "ui.hoje": ("Hoje", "Today"),
    "ui.amanha": ("Amanhã", "Tomorrow"),
    "ui.ja_treinaste": ("Já treinaste hoje:", "You already trained today:"),
    "ui.plano_amanha": ("O plano começa amanhã.", "The plan starts tomorrow."),
    "ui.carga": ("carga", "load"),
    "ui.porque_esta": ("Porquê esta", "Why this one"),
    "ui.ver_sessao": ("ver a sessão", "see the session"),
    "ui.sem_treino": ("sem treino", "no training"),
    "ui.a_corrigir": ("A corrigir", "Needs attention"),
    "ui.de": ("{n} de {total}", "{n} of {total}"),
    "ui.normal": ("Dentro do normal", "Within normal"),
    "ui.tudo_bem": ("Está tudo dentro do esperado", "Everything is where it should be"),
    "ui.tudo_bem_sub": ("Nenhuma métrica fora dos limites. Segue o plano.",
                        "No metric out of range. Follow the plan."),
    "ui.ordenado": ("ordenado do mais urgente para o mais tranquilo",
                    "sorted from most urgent to least"),
    "ui.analise": ("Análise", "Analysis"),
    "ui.carga_semana": ("Carga por semana", "Weekly load"),
    "ui.media": ("média {n}", "average {n}"),
    "ui.plano": ("Plano para os próximos {n} dias", "Plan for the next {n} days"),
    "ui.recomendacao": ("Recomendação", "Recommendation"),
    "ui.quando_abrandar": ("Quando abrandar", "When to ease off"),
    "ui.recentes": ("Treinos recentes", "Recent sessions"),
    "ui.bandeiras": ("Bandeiras de recuperação", "Recovery flags"),
    "ui.bandeiras_sub": ("Enquanto durarem, o plano só sugere sessões leves.",
                         "While they last, the plan will only suggest easy sessions."),
    "ui.progressao": ("Progressão", "Ramp"),
    "ui.resumo_28d": ("{duras} em 28 dias, {descanso} dias sem treino. Sessão mais longa {longa} min.",
                      "{duras} in 28 days, {descanso} days without training. Longest session {longa} min."),
    "ui.sessao_dura": ("1 sessão dura", "1 hard session"),
    "ui.sessoes_duras": ("{n} sessões duras", "{n} hard sessions"),
    "ui.resumo_plano": ("{s} sessões, {h} duras, {min} minutos. CTL projetado de {a} para {b}, "
                        "TSB no fim {tsb}. Calculado a partir das regras, não escrito pelo modelo.",
                        "{s} sessions, {h} hard, {min} minutes. Projected CTL from {a} to {b}, "
                        "final TSB {tsb}. Worked out from the rules, not written by the model."),
    "ui.objetivo_peso": ("Com o objetivo de perder peso, os dias de descanso a mais passam a "
                         "caminhada: gasta energia e quase não cobra recuperação. A intensidade "
                         "fica na mesma, porque é essa que magoa. O treino ajuda, mas a diferença "
                         "maior vem da alimentação, que este relatório não vê. E se aparecerem "
                         "sinais de fadiga, eles mandam primeiro.",
                         "With weight loss as the goal, spare rest days become walks: they spend "
                         "energy and ask almost nothing back. Intensity is unchanged, because "
                         "intensity is what injures. Training helps, but the bigger difference "
                         "comes from food, which this report cannot see. And if fatigue signals "
                         "appear, they take precedence."),
    "ui.sem_texto": ("Sem texto redigido: ou o modelo não respondeu, ou o que escreveu continha "
                     "números fora dos dados e foi rejeitado. Os números e o plano mantêm-se "
                     "válidos.",
                     "No written text: either the model did not answer, or what it wrote contained "
                     "numbers absent from the data and was rejected. The figures and the plan "
                     "still stand."),
    "ui.aviso": ("Orientação genérica gerada a partir dos teus próprios dados. Não substitui "
                 "acompanhamento clínico ou de um treinador, sobretudo se houver dor, tonturas "
                 "ou sintomas persistentes.",
                 "General guidance generated from your own data. It does not replace medical or "
                 "coaching supervision, especially if there is pain, dizziness or persistent "
                 "symptoms."),
    # tabela
    "th.data": ("Data", "Date"), "th.desporto": ("Desporto", "Sport"),
    "th.min": ("Min", "Min"), "th.km": ("km", "km"),
    "th.fc": ("FC média", "Avg HR"), "th.carga": ("Carga", "Load"),
    "th.semana": ("Semana de", "Week of"), "th.sessoes": ("Sessões", "Sessions"),
    "th.minutos": ("Minutos", "Minutes"),
    # linha de tempo e figuras
    "tl.facil": ("fácil", "easy"), "tl.forte": ("forte", "hard"), "tl.andar": ("a andar", "walking"),
    "tl.total": ("{n} min ao todo", "{n} min in total"),
    # intensidades do plano
    "int.dura": ("dura", "hard"), "int.moderada": ("moderada", "moderate"),
    "int.leve": ("leve", "easy"), "int.descanso": ("descanso", "rest"),
    # landing e configuração
    "ui.quem": ("Quem vai treinar?", "Who is training?"),
    "ui.quem_sub": ("Cada pessoa tem a sua conta Garmin e o seu relatório.",
                    "Each person has their own Garmin account and their own report."),
    "ui.adicionar": ("Adicionar", "Add"),
    "ui.trocar": ("Trocar de perfil", "Switch profile"),
    "ui.sair": ("Sair", "Sign out"),
    "ui.anteriores": ("Relatórios anteriores", "Previous reports"),
    "ui.nenhum": ("nenhum", "none"),
    "ui.voltar": ("Voltar", "Back"),
    "ui.sem_relatorios": ("Ainda não há relatórios", "No reports yet"),
    "ui.sem_relatorios_sub": ("A primeira sincronização de {nome} ainda não correu.",
                              "The first sync for {nome} has not run yet."),
})


# Outras línguas entram aqui, como dicionários planos das mesmas chaves. O que
# faltar cai para inglês, por isso uma tradução incompleta nunca parte a
# página: mostra parte em inglês e o resto na língua da pessoa.
try:
    from traducoes import TODAS as OUTRAS
except ImportError:                      # sem o ficheiro, ficam inglês e português
    OUTRAS: dict[str, dict[str, str]] = {}


def linguas() -> list[str]:
    return ["en", "pt"] + sorted(OUTRAS)


def t(chave: str, idioma: str = "en", **kw) -> str:
    idioma = (idioma or "en").lower()
    texto = None
    if idioma in OUTRAS:
        texto = OUTRAS[idioma].get(chave)
    if texto is None:
        par = F.get(chave)
        if not par:
            return chave
        texto = par[0] if idioma == "pt" else par[1]
    return texto.format(**kw) if kw else texto
