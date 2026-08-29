#!/usr/bin/env python3
"""Report language, taken from each person's Garmin account.

The account carries a locale. If it says Portuguese, the report comes out in
Portuguese; in any other case it comes out in English, which is what Garmin
defaults to and what serves the most people.

Language is per profile, because a household can hold accounts set
differently. COACH_LANG forces one, for testing.

English and Portuguese live here, because English is the default and
Portuguese is the language this was written in. The rest live in
translations.py as flat dictionaries of the same keys. Anything missing falls
back to English, so a half-finished translation never breaks the page.
"""

from __future__ import annotations

import os

APP = "GarmiNAS"

try:
    from translations import ALL as OTHERS
except ImportError:                  # without the file, English and Portuguese
    OTHERS: dict[str, dict[str, str]] = {}


def languages() -> list[str]:
    return ["en", "pt"] + sorted(OTHERS)


def pick(language: str | None = None) -> str:
    """Normalises the account locale to one of the languages that exist here.

    Garmin returns things like "pt", "pt-BR", "en-GB" or "zh-CN". Only the part
    before the dash matters; anything untranslated falls back to English.
    """
    asked = (language or os.environ.get("COACH_LANG") or "en").lower()
    base = asked.replace("_", "-").split("-")[0]
    return base if base in languages() else "en"


# Each entry is (Portuguese, English). Both are written out because these two
# are the languages the code itself falls back on.
F = {
    # ── estados das leituras ────────────────────────────────────────────────
    "state.good": ("bom", "good"),
    "state.watch": ("a vigiar", "watch"),
    "state.fix": ("a corrigir", "fix this"),
    "state.alert": ("alerta", "alert"),

    # ── títulos das métricas ────────────────────────────────────────────────
    "m.tsb": ("Frescura", "Freshness"),
    "m.ctl": ("Forma de fundo", "Fitness"),
    "m.rhr": ("FC de repouso", "Resting heart rate"),
    "m.hrv": ("HRV", "HRV"),
    "m.sleep": ("Sono", "Sleep"),
    "m.ramp": ("Progressão", "Weekly ramp"),
    "m.dsh": ("Dias desde sessão dura", "Days since a hard session"),
    "m.vol": ("Volume 7 dias", "Volume, 7 days"),
    "m.weight": ("Peso", "Weight"),

    # ── glosas ──────────────────────────────────────────────────────────────
    "g.tsb": ("TSB, a forma menos a fadiga", "TSB, fitness minus fatigue"),
    "g.ctl": ("CTL, média da carga a 42 dias. Há quatro semanas estava em {antes}",
              "CTL, 42-day load average. Four weeks ago it was {antes}"),
    "g.base": ("média a 7 dias. Base de 28 dias: {base}. Diferença: {delta}",
               "7-day average. 28-day baseline: {base}. Difference: {delta}"),
    "g.sleep": ("média das últimas 7 noites", "average of the last 7 nights"),
    "g.ramp": ("carga da última semana a dividir pela média das anteriores",
               "last week's load divided by the average of the weeks before"),
    "g.dsh": ("uma sessão dura é carga de 100 ou mais", "a hard session is load 100 or more"),
    "g.vol": ("média das semanas com treino: {media} min",
              "average of weeks with training: {media} min"),
    "g.weight": ("pesagem de {data}", "weighed on {data}"),
    "g.no_data": ("sem dados suficientes", "not enough data"),

    # ── leituras ────────────────────────────────────────────────────────────
    "l.tsb.alert": ("fadiga a acumular mais depressa do que a recuperação",
                     "fatigue is building faster than you recover"),
    "l.tsb.watch": ("cansaço normal de quem está a construir carga",
                      "the normal tiredness of building load"),
    "l.tsb.balanced": ("carga e recuperação em equilíbrio", "load and recovery are balanced"),
    "l.tsb.fresh": ("fresco, bom momento para uma sessão exigente",
                     "fresh, a good moment for a demanding session"),
    "l.tsb.idle": ("demasiado fresco, já se perde forma por falta de treino",
                     "too fresh, you are losing fitness for lack of training"),
    "l.ctl.up": ("a subir {delta} em quatro semanas, estás a ganhar base",
                   "up {delta} in four weeks, you are building a base"),
    "l.ctl.flat": ("estável em quatro semanas, a manter a base",
                      "flat over four weeks, holding the base"),
    "l.ctl.down": ("a descer {delta} em quatro semanas", "down {delta} in four weeks"),
    "l.ctl.falling": ("a descer {delta} em quatro semanas, a perder base aeróbia",
                  "down {delta} in four weeks, losing aerobic base"),
    "l.rhr.high": ("{d} bpm acima da base: o corpo está a pedir descanso",
                   "{d} bpm above baseline: your body is asking for rest"),
    "l.rhr.mid": ("{d} bpm acima da base, a vigiar nos próximos dias",
                    "{d} bpm above baseline, worth watching over the next few days"),
    "l.rhr.normal": ("na base habitual", "at your usual baseline"),
    "l.rhr.low": ("{d} bpm abaixo da base, sinal de boa recuperação",
                    "{d} bpm below baseline, a sign of good recovery"),
    "l.hrv.alert": ("{pct}% abaixo da base: sistema nervoso sob stress",
                     "{pct}% below baseline: your nervous system is under stress"),
    "l.hrv.low": ("{pct}% abaixo da base", "{pct}% below baseline"),
    "l.hrv.normal": ("na base habitual", "at your usual baseline"),
    "l.hrv.high": ("{pct} acima da base, boa recuperação",
                   "{pct} above baseline, good recovery"),
    "l.sleep.alert": ("abaixo de 6 horas o treino deixa de render, por muito bem feito que seja",
                      "below 6 hours training stops paying off, however well you do it"),
    "l.sleep.short": ("curto. Abaixo de 6 horas o plano passa a só sugerir sessões leves",
                     "short. Below 6 hours the plan will only suggest easy sessions"),
    "l.sleep.ok": ("aceitável, mas há margem para melhorar",
                         "acceptable, but there is room to improve"),
    "l.sleep.good": ("suficiente para sustentar a carga", "enough to sustain the load"),
    "l.ramp.alert": ("salto grande de mais face às semanas anteriores",
                      "far too big a jump on the weeks before"),
    "l.ramp.high": ("acima de 1.3, o intervalo onde as lesões aparecem",
                    "above 1.3, the range where injuries show up"),
    "l.ramp.good": ("entre 0.8 e 1.3, progressão sustentável",
                   "between 0.8 and 1.3, a sustainable ramp"),
    "l.ramp.light": ("abaixo de 0.8: semana mais leve do que as anteriores",
                    "below 0.8: a lighter week than the ones before"),
    "l.ramp.very_light": ("muito abaixo das semanas anteriores, a forma vai cair",
                          "far below the previous weeks, fitness will drop"),
    "l.dsh.long": ("há muito sem estímulo intenso; a velocidade perde-se primeiro",
                    "a long time without hard work; speed is the first thing to go"),
    "l.dsh.some": ("já vai longe sem uma sessão exigente",
                    "it has been a while since a demanding session"),
    "l.dsh.recent": ("sessão dura muito recente, cuidado com a seguinte",
                      "a hard session very recently, take care with the next one"),
    "l.dsh.good": ("espaçamento adequado", "well spaced"),
    "l.dsh.none": ("sem nenhuma sessão dura no histórico recente",
                      "no hard session in the recent history"),
    "l.vol.low": ("bem abaixo da média do mês ({media} min)",
                    "well below the month's average ({media} min)"),
    "l.vol.high": ("bem acima da média do mês ({media} min)",
                   "well above the month's average ({media} min)"),
    "l.vol.good": ("em linha com a média do mês ({media} min)",
                  "in line with the month's average ({media} min)"),
    "l.vol.no_base": ("sem histórico para comparar", "no history to compare against"),
    "l.weight.stale": ("a última pesagem foi há {dias} dias, não dá para ver tendência",
                     "the last weigh-in was {dias} days ago, too old to show a trend"),
    "l.weight.few": ("poucas pesagens para calcular uma tendência",
                      "too few weigh-ins to work out a trend"),
    "l.weight.fast": ("a descer {kg} kg por semana, depressa de mais",
                      "down {kg} kg a week, too fast"),
    "l.weight.right": ("a descer {kg} kg por semana, no ritmo certo",
                     "down {kg} kg a week, at the right rate"),
    "l.weight.flat": ("praticamente estável nas últimas semanas",
                       "essentially flat over the last few weeks"),
    "l.weight.up": ("a subir {kg} kg por semana", "up {kg} kg a week"),

    # ── alvos ───────────────────────────────────────────────────────────────
    "a.tsb": ("confortável entre −10 e +5. Acima de +25 já é falta de treino",
              "comfortable between −10 and +5. Above +25 is undertraining"),
    "a.ctl": ("o que interessa é a direção, a subir devagar e sem saltos",
              "direction is what matters: up slowly, without jumps"),
    "a.rhr": ("normal até 2 bpm acima da base", "normal up to 2 bpm above baseline"),
    "a.hrv": ("normal entre −5% e +5% da base", "normal between −5% and +5% of baseline"),
    "a.sleep": ("7 horas ou mais sustentam a carga de treino",
               "7 hours or more sustains the training load"),
    "a.ramp": ("sustentável entre 0.8 e 1.3", "sustainable between 0.8 and 1.3"),
    "a.dsh": ("entre 2 e 14 dias mantém o estímulo sem acumular fadiga",
              "2 to 14 days keeps the stimulus without piling up fatigue"),
    "a.vol": ("entre 60% e 140% da média do mês",
              "between 60% and 140% of the month's average"),
    "a.weight": ("perder entre {min} e {max} kg por semana",
               "lose between {min} and {max} kg a week"),

    # ── ações ───────────────────────────────────────────────────────────────
    "ac.tsb.rest": ("Precisas de dias fáceis antes da próxima sessão dura.",
                         "You need easy days before the next hard session."),
    "ac.tsb.train": ("Aproveita para treinar a sério.", "Use it: train properly."),
    "ac.ctl": ("Acrescenta uma sessão fácil por semana antes de acrescentar intensidade.",
               "Add one easy session a week before adding any intensity."),
    "ac.rhr": ("Trata como sinal de fadiga ou infeção: descansa e reavalia amanhã.",
               "Treat it as fatigue or illness: rest and check again tomorrow."),
    "ac.hrv": ("Dorme mais e adia a próxima sessão dura em um ou dois dias.",
               "Sleep more and push the next hard session back a day or two."),
    "ac.sleep": ("Deitar meia hora mais cedo rende mais do que qualquer sessão extra.",
                "Half an hour earlier to bed pays more than any extra session."),
    "ac.ramp.raise": ("Sobe o volume devagar, cerca de 10% por semana.",
                      "Raise the volume slowly, around 10% a week."),
    "ac.ramp.hold": ("Segura a próxima semana no mesmo volume.",
                        "Hold next week at the same volume."),
    "ac.dsh.add": ("Mete intervalos ou um contínuo forte esta semana.",
                     "Put in intervals or a hard steady run this week."),
    "ac.dsh.wait": ("Deixa passar mais um dia fácil.", "Give it one more easy day."),
    "ac.vol.short": ("Falta volume face ao teu normal.", "You are short of your usual volume."),
    "ac.vol.heavy": ("Semana pesada: a seguinte deve ser mais leve.",
                      "Heavy week: the next one should be lighter."),
    "ac.weight.weigh": ("Pesa-te uma vez por semana, em jejum e sempre à mesma hora.",
                      "Weigh yourself once a week, fasted, always at the same time."),
    "ac.weight.weigh_weekly": ("Pesa-te uma vez por semana para o plano poder acompanhar.",
                           "Weigh in weekly so the plan can follow along."),
    "ac.weight.eat": ("Come mais nos dias de treino: a esta velocidade perde-se músculo.",
                      "Eat more on training days: at this rate you lose muscle."),
    "ac.weight.kitchen": ("O plano acrescenta volume fácil; a diferença maior vem da mesa.",
                     "The plan adds easy volume; the bigger difference comes from the kitchen."),
    "ac.weight.food": ("Vale a pena olhar para a alimentação antes de acrescentar treino.",
                      "Worth looking at food before adding more training."),
}


# ── veredictos e frases longas do relatório ─────────────────────────────────
F.update({
    "v.ramp.none": ("sem semanas anteriores suficientes para comparar",
                   "not enough previous weeks to compare against"),
    "v.ramp.alert": ("{r}, acima de 1.3: subida rápida de mais, território de lesão",
                      "{r}, above 1.3: rising too fast, injury territory"),
    "v.ramp.light": ("{r}, abaixo de 0.8: a semana passada ficou aquém, está a perder forma",
                    "{r}, below 0.8: last week fell short, you are losing fitness"),
    "v.ramp.good": ("{r}, entre 0.8 e 1.3: progressão saudável",
                   "{r}, between 0.8 and 1.3: a healthy ramp"),
    "v.ease_off": ("Abranda o plano se acontecer alguma destas coisas: a FC de repouso a 7 dias "
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
    "md.status": ("Estado", "Status"),
    "md.next_up": ("A seguir: {quando}, {data}", "Next up: {quando}, {data}"),
    "md.why": ("Porquê esta: {motivo}.", "Why this one: {motivo}."),
    "md.atl": ("ATL (fadiga recente) {atl}, {n} sessões nos últimos 7 dias.",
               "ATL (recent fatigue) {atl}, {n} sessions in the last 7 days."),
    "md.already_trained": ("Já treinaste: **{desporto}**, {min} min{km}, carga {carga}. "
                        "O plano abaixo começa amanhã.",
                        "You already trained: **{desporto}**, {min} min{km}, load {carga}. "
                        "The plan below starts tomorrow."),
    "md.reading": ("Leitura", "Reading"), "md.why_col": ("Porquê", "Why"),
    "md.metric": ("Métrica", "Metric"), "md.value": ("Valor", "Value"),
    "md.day": ("Dia", "Day"), "md.session": ("Sessão", "Session"),
    "md.tsb_projected": ("TSB projetado", "Projected TSB"),
})

# ── interface do relatório ──────────────────────────────────────────────────
F.update({
    "ui.training": ("Treino", "Training"),
    "ui.today": ("Hoje", "Today"),
    "ui.tomorrow": ("Amanhã", "Tomorrow"),
    "ui.already_trained": ("Já treinaste hoje:", "You already trained today:"),
    "ui.plan_tomorrow": ("O plano começa amanhã.", "The plan starts tomorrow."),
    "ui.load": ("carga", "load"),
    "ui.why_this": ("Porquê esta", "Why this one"),
    "ui.see_session": ("ver a sessão", "see the session"),
    "ui.no_training": ("sem treino", "no training"),
    "ui.needs_attention": ("A corrigir", "Needs attention"),
    "ui.of": ("{n} de {total}", "{n} of {total}"),
    "ui.within_normal": ("Dentro do normal", "Within normal"),
    "ui.all_good": ("Está tudo dentro do esperado", "Everything is where it should be"),
    "ui.all_good_sub": ("Nenhuma métrica fora dos limites. Segue o plano.",
                        "No metric out of range. Follow the plan."),
    "ui.sorted_by": ("ordenado do mais urgente para o mais tranquilo",
                    "sorted from most urgent to least"),
    "ui.analysis": ("Análise", "Analysis"),
    "ui.weekly_load": ("Carga por semana", "Weekly load"),
    "ui.average": ("média {n}", "average {n}"),
    "ui.plan": ("Plano para os próximos {n} dias", "Plan for the next {n} days"),
    "ui.recommendation": ("Recomendação", "Recommendation"),
    "ui.when_to_ease": ("Quando abrandar", "When to ease off"),
    "ui.recent": ("Treinos recentes", "Recent sessions"),
    "ui.flags": ("Bandeiras de recuperação", "Recovery flags"),
    "ui.flags_sub": ("Enquanto durarem, o plano só sugere sessões leves.",
                         "While they last, the plan will only suggest easy sessions."),
    "ui.ramp": ("Progressão", "Ramp"),
    "ui.summary_28d": ("{duras} em 28 dias, {descanso} dias sem treino. Sessão mais longa {longa} min.",
                      "{duras} in 28 days, {descanso} days without training. Longest session {longa} min."),
    "ui.one_hard": ("1 sessão dura", "1 hard session"),
    "ui.n_hard": ("{n} sessões duras", "{n} hard sessions"),
    "ui.plan_summary": ("{s} sessões, {h} duras, {min} minutos. CTL projetado de {a} para {b}, "
                        "TSB no fim {tsb}. Calculado a partir das regras, não escrito pelo modelo.",
                        "{s} sessions, {h} hard, {min} minutes. Projected CTL from {a} to {b}, "
                        "final TSB {tsb}. Worked out from the rules, not written by the model."),
    "ui.weight_goal": ("Com o objetivo de perder peso, os dias de descanso a mais passam a "
                         "caminhada: gasta energia e quase não cobra recuperação. A intensidade "
                         "fica na mesma, porque é essa que magoa. O treino ajuda, mas a diferença "
                         "maior vem da alimentação, que este relatório não vê. E se aparecerem "
                         "sinais de fadiga, eles mandam primeiro.",
                         "With weight loss as the goal, spare rest days become walks: they spend "
                         "energy and ask almost nothing back. Intensity is unchanged, because "
                         "intensity is what injures. Training helps, but the bigger difference "
                         "comes from food, which this report cannot see. And if fatigue signals "
                         "appear, they take precedence."),
    "ui.no_text": ("Sem texto redigido: ou o modelo não respondeu, ou o que escreveu continha "
                     "números fora dos dados e foi rejeitado. Os números e o plano mantêm-se "
                     "válidos.",
                     "No written text: either the model did not answer, or what it wrote contained "
                     "numbers absent from the data and was rejected. The figures and the plan "
                     "still stand."),
    "ui.disclaimer": ("Orientação genérica gerada a partir dos teus próprios dados. Não substitui "
                 "acompanhamento clínico ou de um treinador, sobretudo se houver dor, tonturas "
                 "ou sintomas persistentes.",
                 "General guidance generated from your own data. It does not replace medical or "
                 "coaching supervision, especially if there is pain, dizziness or persistent "
                 "symptoms."),
    # tabela
    "th.date": ("Data", "Date"), "th.sport": ("Desporto", "Sport"),
    "th.min": ("Min", "Min"), "th.km": ("km", "km"),
    "th.hr": ("FC média", "Avg HR"), "th.load": ("Carga", "Load"),
    "th.week": ("Semana de", "Week of"), "th.sessions": ("Sessões", "Sessions"),
    "th.minutes": ("Minutos", "Minutes"),
    # linha de tempo e figuras
    "tl.easy": ("fácil", "easy"), "tl.hard": ("forte", "hard"), "tl.walking": ("a andar", "walking"),
    "tl.total": ("{n} min ao todo", "{n} min in total"),
    # intensidades do plano
    "int.hard": ("dura", "hard"), "int.moderate": ("moderada", "moderate"),
    "int.easy": ("leve", "easy"), "int.rest": ("descanso", "rest"),
    # landing e configuração
    # Notas sobre a sessão que acabou de ser feita. Os números vão sempre em
    # algarismos: escrever "oito semanas" por extenso fazia o modelo responder
    # "8 weeks", e a guarda rejeitava um número que nunca lhe tinha sido dado.
    "s.fastest": ("foi a tua sessão mais rápida das últimas 8 semanas",
                  "your fastest session in the last 8 weeks"),
    "s.one_faster": ("só 1 sessão em 8 semanas foi mais rápida",
                     "only 1 session in 8 weeks was faster"),
    "s.few_faster": ("só {n} sessões em 8 semanas foram mais rápidas",
                     "only {n} sessions in 8 weeks were faster"),
    "s.above_avg": ("correste a {kmh} km/h, acima da tua média recente de {media}",
                    "you ran at {kmh} km/h, above your recent average of {media}"),
    "s.below_avg": ("correste a {kmh} km/h, abaixo da tua média recente de {media}",
                    "you ran at {kmh} km/h, below your recent average of {media}"),
    "s.longer": ("durou {min} minutos, bem mais do que os {media} habituais",
                 "it lasted {min} minutes, well over your usual {media}"),
    "s.shorter": ("foi curta, {min} minutos contra os {media} habituais",
                  "it was short, {min} minutes against your usual {media}"),
    "s.hard_ground": ("a {kmh} km/h estiveste no teu terreno forte",
                      "at {kmh} km/h you were on hard ground"),
    "s.easy_ground": ("a {kmh} km/h ficaste em ritmo fácil, que é onde se constrói a base",
                      "at {kmh} km/h you stayed easy, which is where the base is built"),
    "s.hr_high": ("a FC média foi {hr}, acima das {media} habituais",
                  "average heart rate was {hr}, above your usual {media}"),
    "s.hr_low": ("a FC média foi {hr}, abaixo das {media} habituais",
                 "average heart rate was {hr}, below your usual {media}"),
    "v.session.strong_long": ("Sessão forte: mais rápida e mais longa do que o teu costume.",
                              "Strong session: faster and longer than your usual."),
    "v.session.strong": ("Bom estímulo: correste acima do teu ritmo habitual.",
                         "Good stimulus: you ran above your usual pace."),
    "v.session.volume": ("Boa sessão de volume: mais longa do que o teu costume.",
                         "Good volume session: longer than your usual."),
    "v.session.base": ("Sessão de base, ao ritmo certo para construir aeróbio.",
                       "Base session, at the right pace to build aerobic fitness."),
    "v.session.normal": ("Sessão dentro do teu normal.", "A session within your normal."),
    "m.eff": ("Progresso", "Progress"),
    "g.eff": ("ritmo à mesma frequência cardíaca, {n} sessões recentes contra as {m} anteriores",
              "pace at the same heart rate, {n} recent sessions against the {m} before"),
    "l.eff.much_better": ("{pct}% mais eficiente: mais velocidade com o mesmo esforço",
                          "{pct}% more efficient: more speed for the same effort"),
    "l.eff.better": ("{pct}% mais eficiente do que nas sessões anteriores",
                     "{pct}% more efficient than in the sessions before"),
    "l.eff.flat": ("igual às sessões anteriores, sem ganho nem perda",
                   "level with the sessions before, no gain and no loss"),
    "l.eff.worse": ("{pct}% menos eficiente do que nas sessões anteriores",
                    "{pct}% less efficient than in the sessions before"),
    "l.eff.much_worse": ("{pct}% menos eficiente: o mesmo esforço rende menos",
                         "{pct}% less efficient: the same effort buys less"),
    "a.eff": ("subir é melhorar, mas calor e passadeira mexem no valor",
              "up is better, though heat and treadmill move the number"),
    "ac.eff.keep": ("Está a resultar. Não mudes nada.", "It is working. Change nothing."),
    "ac.eff.check": ("Vê o sono e o calor antes de mudar o treino.",
                     "Look at sleep and heat before changing the training."),
    "s.eff": ("estás {pct}% mais eficiente do que nas sessões anteriores, mais velocidade com o mesmo coração",
              "you are {pct}% more efficient than in the sessions before, more speed for the same heart rate"),
    "s.eff_down": ("estás {pct}% menos eficiente do que nas sessões anteriores",
                   "you are {pct}% less efficient than in the sessions before"),
    "s.faded": ("abrandaste no fim: o último quilómetro foi {last}, contra {best} no mais rápido",
                "you faded at the end: the last kilometre was {last}, against {best} at your fastest"),
    "s.built": ("foste a acelerar: o último quilómetro foi o mais rápido",
                "you built through it: the last kilometre was the fastest"),
    "s.z5": ("passaste {min} minutos em zona 5, {pct}% da sessão",
             "you spent {min} minutes in zone 5, {pct}% of the session"),
    "s.z12": ("ficaste quase toda a sessão em zona 1 e 2, {pct}% do tempo",
              "you stayed in zones 1 and 2 for most of it, {pct}% of the time"),
    "ui.settings": ("Preferências", "Preferences"),
    "ui.your_prompt": ("As tuas instruções ao treinador", "Your instructions to the coach"),
    "ui.prompt_help": ("Escreve aqui o que quiseres que o treinador tenha em conta: objetivos, "
                       "lesões, o que gostas e o que detestas, o tom que preferes. Vai junto a "
                       "cada relatório. O que não muda: os números e o plano continuam calculados, "
                       "e nenhuma instrução faz o treinador inventar dados.",
                       "Write whatever you want the coach to take into account: goals, injuries, "
                       "what you enjoy and what you hate, the tone you prefer. It goes with every "
                       "report. What does not change: the figures and the plan stay calculated, "
                       "and no instruction will make the coach invent data."),
    "ui.prompt_example": ("Por exemplo: treino para uma meia maratona em março, tenho o joelho "
                          "direito sensível, prefiro correr de manhã, fala-me sem rodeios.",
                          "For example: I am training for a half marathon in March, my right knee "
                          "is sensitive, I prefer to run in the morning, be blunt with me."),
    "ui.language_choice": ("Idioma do relatório", "Report language"),
    "ui.language_auto": ("Como está na conta Garmin ({lang})", "As set in the Garmin account ({lang})"),
    "ui.save": ("Guardar", "Save"),
    "ui.saved": ("Guardado.", "Saved."),
    "d.splits": ("Parciais por quilómetro", "Splits per kilometre"),
    "d.zones": ("Tempo em cada zona cardíaca", "Time in each heart rate zone"),
    "d.zone_from": ("a partir de {bpm} bpm", "from {bpm} bpm"),
    "d.max_hr": ("FC máxima {hr}", "max HR {hr}"),
    "d.cadence": ("{n} passos/min", "{n} steps/min"),
    "d.no_splits": ("Sem parciais para esta sessão.", "No splits for this session."),
    "ui.como_correu": ("Como correu", "How it went"),
    "tsb.fadiga": ("fadiga acumulada", "fatigue piling up"),
    "tsb.cansado": ("cansado", "tired"),
    "tsb.fresco": ("muito fresco", "very fresh"),
    "tsb.equilibrio": ("equilibrado", "balanced"),
    "ui.today_short": ("hoje", "today"),
    "ui.update_now": ("Atualizar agora", "Update now"),
    "ui.fetching": ("A ir buscar os treinos novos", "Fetching new sessions"),
    "ui.no_new_data": ("Sem dados novos desde a última vez.", "No new data since last time."),
    "ui.setting_up": ("A configurar", "Setting up"),
    "ui.starting": ("A começar", "Starting"),
    "ui.log": ("Registo", "Log"),
    "ui.code": ("Código de verificação", "Verification code"),
    "ui.code_sub": ("A Garmin pediu o código de dois passos. Escreve-o aqui.",
                      "Garmin asked for the two-factor code. Type it here."),
    "ui.send_code": ("Enviar código", "Send code"),
    "ui.see_report": ("Ver o relatório", "See the report"),
    "ui.waiting": ("a aguardar", "waiting"),
    "ui.failed": ("Falhou", "Failed"),
    "ui.who": ("Quem vai treinar?", "Who is training?"),
    "ui.who_sub": ("Cada pessoa tem a sua conta Garmin e o seu relatório.",
                    "Each person has their own Garmin account and their own report."),
    "ui.add": ("Adicionar", "Add"),
    "ui.switch": ("Trocar de perfil", "Switch profile"),
    "ui.logout": ("Sair", "Sign out"),
    "ui.previous": ("Relatórios anteriores", "Previous reports"),
    "ui.none": ("nenhum", "none"),
    "ui.back": ("Voltar", "Back"),
    "ui.no_reports": ("Ainda não há relatórios", "No reports yet"),
    "ui.no_reports_sub": ("A primeira sincronização de {nome} ainda não correu.",
                              "The first sync for {nome} has not run yet."),
})


# Outras línguas entram aqui, como dicionários planos das mesmas chaves. O que
# faltar cai para inglês, por isso uma tradução incompleta nunca parte a
# página: mostra parte em inglês e o resto na língua da pessoa.
def t(key: str, language: str = "en", **kw) -> str:
    """One phrase, in the given language, with English as the fallback."""
    language = (language or "en").lower()
    text = None
    if language in OTHERS:
        text = OTHERS[language].get(key)
    if text is None:
        pair = F.get(key)
        if not pair:
            return key
        text = pair[0] if language == "pt" else pair[1]
    return text.format(**kw) if kw else text
