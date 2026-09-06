#!/usr/bin/env python3
"""Desenha o relatório a partir dos dados, não do markdown.

O markdown continua a ser a versão canónica. Aqui interessa outra coisa: que
uma pessoa abra a página de manhã e perceba o essencial em três segundos:
como está, o que faz hoje, e se alguma coisa merece atenção.

Cores tiradas da paleta validada da orientação de visualização: azul para
magnitude, e os quatro estados reservados para o que é estado. Nenhuma cor
carrega significado sozinha; há sempre rótulo ao lado.
"""

from __future__ import annotations

import re
from html import escape

from assess import ESTADOS, desporto
from language import APP
from language import t as _t
from figures import CSS as FIG_CSS, exercicios, linha_tempo

CSS = """
.viz { --s1:#2a78d6; --seq-leve:#9ec5f4; --seq-med:#3987e5; --seq-duro:#1c5cab;
       --good:#0ca30c; --warn:#fab219; --serious:#ec835a; --critical:#d03b3b; }
@media (prefers-color-scheme: dark) {
  .viz { --s1:#3987e5; --seq-leve:#1c5cab; --seq-med:#3987e5; --seq-duro:#86b6ef; }
}

.hero { display:flex; flex-wrap:wrap; align-items:baseline; gap:.6rem; margin:.2rem 0 1.6rem; }
.hero h1 { margin:0; }
.hero .date { color:var(--dim); font-variant-numeric:tabular-nums; }

.today { border:1px solid var(--line); border-left:3px solid var(--s1); border-radius:8px;
  padding:.85rem 1rem; margin:0 0 1rem; background:color-mix(in srgb, var(--s1) 5%, transparent); }

/* O que fazer a seguir, em destaque. É a pergunta com que se abre a página. */
.seguir { border:1px solid var(--s1); border-radius:12px; padding:1.15rem 1.3rem 1.3rem;
  margin:0 0 2rem; background:color-mix(in srgb, var(--s1) 6%, transparent); }
.seguir .quando { font-size:.78rem; text-transform:uppercase; letter-spacing:.06em; color:var(--dim); }
.seguir h2 { margin:.2rem 0 .1rem; padding:0; border:0; font-size:1.45rem; }
.seguir .dur { font-size:.95rem; color:var(--dim); }
.seguir .como { margin:.7rem 0 0; font-size:1rem; max-width:74ch; }
.seguir .ritmo { margin:.6rem 0 0; padding:.6rem .8rem; border-radius:8px; max-width:68ch;
  background:color-mix(in srgb, var(--s1) 12%, transparent); font-size:1rem; font-weight:600; }
.seguir .porque { margin:.55rem 0 0; font-size:.87rem; color:var(--dim); max-width:68ch; }
.day .ritmo { font-size:.8rem; margin-top:.35rem; font-weight:600; }

.day .desc { font-size:.76rem; color:var(--dim); margin-top:.3rem; line-height:1.4; }
.today b { font-size:1.05rem; }

/* Como correu a sessão que acabou de ser feita. O cartão existe porque a
   pergunta "foi bom ou mau?" merece resposta antes do plano de amanhã. */
.correu { border:1px solid var(--line); border-radius:12px; padding:1rem 1.15rem;
  margin:0 0 1.5rem; background:color-mix(in srgb, var(--fg) 3%, transparent); }
.correu .rotulo { display:flex; align-items:center; gap:.45rem; font-size:.8rem;
  text-transform:uppercase; letter-spacing:.06em; color:var(--dim); margin-bottom:.5rem; }
.correu .rotulo b { color:var(--s1); font-size:.95rem; }
.correu p { margin:0; font-size:1.05rem; line-height:1.55; max-width:74ch; }
.correu .factos { margin-top:.6rem; font-size:.85rem; color:var(--dim); }

/* Parciais e zonas. O comprimento das barras diz o que os números sozinhos
   demoram a dizer: onde acelerou, onde caiu, onde passou o tempo todo. */
.detalhe { margin-top:1.1rem; display:grid; gap:1.1rem;
  grid-template-columns:repeat(auto-fit,minmax(19rem,1fr)); }
.detalhe h4 { margin:0 0 .5rem; font-size:.78rem; text-transform:uppercase;
  letter-spacing:.06em; color:var(--dim); font-weight:600; }
.sp { display:grid; grid-template-columns:1.4rem 1fr auto; align-items:center;
  gap:.5rem; padding:.16rem 0; font-size:.83rem; }
.sp .n { color:var(--dim); font-variant-numeric:tabular-nums; text-align:right; }
.sp .barra { height:.75rem; border-radius:3px; background:var(--s1); min-width:2px; }
.sp .v { font-variant-numeric:tabular-nums; white-space:nowrap; }
.sp .v small { color:var(--dim); margin-left:.4rem; }
.zonas { display:flex; height:1.5rem; border-radius:6px; overflow:hidden; }
.zonas i { display:block; }
.zonas .z1 { background:#cde2fb } .zonas .z2 { background:#9ec5f4 }
.zonas .z3 { background:#5598e7 } .zonas .z4 { background:#2a78d6 }
.zonas .z5 { background:#184f95 }
@media (prefers-color-scheme: dark) {
  .zonas .z1 { background:#184f95 } .zonas .z2 { background:#256abf }
  .zonas .z3 { background:#3987e5 } .zonas .z4 { background:#6da7ec }
  .zonas .z5 { background:#b7d3f6 }
}
.zleg { display:flex; flex-wrap:wrap; gap:.7rem; margin-top:.45rem; font-size:.78rem;
  color:var(--dim); font-variant-numeric:tabular-nums; }
.zleg b { color:var(--fg); font-weight:600; }
.today .muted { color:var(--dim); }

.tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(21rem,1fr)); gap:.8rem; margin:.75rem 0 2rem; }
.tile { border:1px solid var(--line); border-radius:10px; padding:1rem 1.15rem 1.15rem; }
.tile .head { display:flex; align-items:baseline; justify-content:space-between; gap:.6rem;
  margin-bottom:.35rem; }

/* As que estão bem não precisam de ocupar o mesmo espaço das que não estão. */
.calmas { display:grid; grid-template-columns:repeat(auto-fit,minmax(24rem,1fr)); gap:.15rem 1.5rem;
  margin:.5rem 0 2rem; }
.linha { display:grid; grid-template-columns:11rem auto 1fr; align-items:center; gap:.8rem;
  padding:.5rem .2rem; border-bottom:1px solid var(--line); }
.linha .nome { font-size:.85rem; color:var(--dim); }
.linha .val { font-size:1.05rem; font-weight:650; font-variant-numeric:tabular-nums; white-space:nowrap; }
.linha .val .u { font-size:.8rem; font-weight:400; color:var(--dim); }
.linha .diz { font-size:.85rem; color:var(--dim); }
.linha .mini { grid-column:1 / -1; margin:.15rem 0 0; }
.mini .track { height:.3rem; }
.mini .marker { top:-.12rem; height:.55rem; }
h2 .conta { font-size:.8rem; font-weight:400; color:var(--dim); margin-left:.5rem; }
.tile .k { font-size:.72rem; text-transform:uppercase; letter-spacing:.06em; color:var(--dim); }
.tile .v { font-size:1.6rem; font-weight:650; line-height:1.25; font-variant-numeric:tabular-nums; }
.tile .g { font-size:.82rem; color:var(--dim); }
.tile .v .u { font-size:.9rem; font-weight:400; color:var(--dim); }

.badge { display:inline-flex; align-items:center; gap:.35rem; font-size:.78rem; font-weight:600;
  padding:.1rem .45rem; border-radius:99px; border:1px solid currentColor; }
.b-good{color:var(--good)} .b-warn{color:var(--warn)} .b-serious{color:var(--serious)} .b-crit{color:var(--critical)}

.callout { border:1px solid var(--serious); border-left-width:3px; border-radius:8px;
  padding:.8rem 1rem; margin:1rem 0 1.5rem; }
.callout h3 { margin:0 0 .4rem; font-size:.95rem; color:var(--serious); }
.callout ul { margin:.2rem 0 0; padding-left:1.1rem; }

.chart { display:flex; align-items:flex-end; gap:.5rem; height:9rem; margin:1rem 0 .3rem; }
.col { flex:1; display:flex; flex-direction:column; justify-content:flex-end; align-items:center;
  gap:.3rem; height:100%; position:relative; }
.col .n { font-size:.8rem; font-variant-numeric:tabular-nums; color:var(--dim); }
.col .bar { width:100%; background:var(--s1); border-radius:4px 4px 0 0; min-height:2px; }
.col .zero { width:100%; height:2px; background:var(--line); border-radius:2px; }
.axis { display:flex; gap:.5rem; border-top:1px solid var(--line); padding-top:.35rem; }
.axis span { flex:1; text-align:center; font-size:.75rem; color:var(--dim); font-variant-numeric:tabular-nums; }
.plot { position:relative; }
.media { position:absolute; left:0; right:0; border-top:1px dashed var(--dim); opacity:.55; }
.media span { position:absolute; right:0; top:-1.15rem; font-size:.7rem; color:var(--dim);
  background:var(--bg); padding:0 .25rem; }
.tip { position:absolute; bottom:100%; left:50%; transform:translate(-50%,-.4rem); white-space:nowrap;
  background:var(--fg); color:var(--bg); font-size:.75rem; padding:.25rem .5rem; border-radius:5px;
  opacity:0; pointer-events:none; transition:opacity .12s; z-index:2; }
.col:hover .tip, .day:hover .tip { opacity:1; }

.plan { display:grid; grid-template-columns:repeat(auto-fill,minmax(15rem,1fr)); gap:.6rem; margin:1rem 0 .5rem; }
.day { position:relative; border:1px solid var(--line); border-left:3px solid var(--line); border-radius:8px;
  padding:.55rem .7rem; }
.day.leve  { border-left-color:var(--seq-leve); }
.day.med   { border-left-color:var(--seq-med); }
.day.duro  { border-left-color:var(--seq-duro); }
.day.hoje  { outline:2px solid var(--s1); outline-offset:1px; }
.day .d { font-size:.72rem; color:var(--dim); text-transform:uppercase; letter-spacing:.04em; }
.day .s { font-size:.88rem; font-weight:600; line-height:1.3; margin:.1rem 0; }
.day .m { font-size:.78rem; color:var(--dim); font-variant-numeric:tabular-nums; }
.day.rest .s { font-weight:500; color:var(--dim); }

/* Painéis. O texto corrido nunca alarga: acima de ~70 caracteres por linha
   o olho perde a linha seguinte, e a página larga só piorava a leitura. */
.painéis { display:grid; grid-template-columns:1fr; gap:1.75rem; align-items:start; }
@media (min-width:64rem) { .painéis { grid-template-columns:1fr 1fr; gap:2.25rem; } }
.painel > h2:first-child, .painel > h3:first-child { margin-top:0; }
/* Dentro da grelha quem trata do espaço é o gap, não a margem do cartão. */
.painel > .correu, .painel > .seguir { margin-bottom:0; }
/* Medida de leitura. Acima de uns 75 caracteres por linha o olho perde a
   linha seguinte ao voltar à esquerda. Abaixo de 60 parte de mais. O rodapé e
   as legendas são texto pequeno e aguentam mais. */
.prose, .callout, .resumo p { max-width:74ch; }
/* A secção livre ocupa a linha toda e não tem nada ao lado, por isso a 74ch
   sobrava meio ecrã num monitor largo. 96 é mais do que a medida ideal, e é
   uma troca consciente: linha mais difícil de seguir, espaço aproveitado. */
.prose.larga { max-width:96ch; }
.legend { max-width:96ch; }
.prose p, .correu p, .seguir .como { text-wrap:pretty; }
.prose { border-left:3px solid var(--line); padding:.1rem 0 .1rem 1rem; margin:.75rem 0 1.5rem; }
.prose p { margin:.4rem 0; }
.prose ol, .prose ul { margin:.4rem 0; padding-left:1.2rem; }
.prose li { margin:.25rem 0; text-wrap:pretty; }
.legend { font-size:.8rem; color:var(--dim); margin:.2rem 0 1.5rem; }
.num { font-variant-numeric:tabular-nums; text-align:right; }

.tile { position:relative; }
.tile.e-good     { border-left:3px solid var(--good); }
.tile.e-warning  { border-left:3px solid var(--warn); }
.tile.e-serious  { border-left:3px solid var(--serious); }
.tile.e-critical { border-left:3px solid var(--critical); }
.tile .r { font-size:.86rem; margin-top:.5rem; }
.tile .acao { font-size:.86rem; margin-top:.3rem; }
.tile .acao::before { content:"→ "; color:var(--dim); }

.meter { margin:.7rem 0 .1rem; }
.track { position:relative; display:flex; height:.45rem; border-radius:99px; overflow:hidden; }
.track i { display:block; height:100%; }
.z-good{background:color-mix(in srgb,var(--good) 45%,transparent)}
.z-warning{background:color-mix(in srgb,var(--warn) 45%,transparent)}
.z-serious{background:color-mix(in srgb,var(--serious) 45%,transparent)}
.z-critical{background:color-mix(in srgb,var(--critical) 45%,transparent)}
.marker { position:absolute; top:-.2rem; width:3px; height:.85rem; border-radius:2px;
  background:var(--fg); box-shadow:0 0 0 2px var(--bg); transform:translateX(-1.5px); }
/* O alvo tem linha própria: espremido entre o mínimo e o máximo, partia em
   duas e sobrepunha-se aos números das pontas. */
.scale { display:flex; justify-content:space-between; font-size:.72rem;
  color:var(--dim); margin-top:.28rem; font-variant-numeric:tabular-nums; }
.alvo { font-size:.78rem; color:var(--dim); margin-top:.15rem; }
.alvo::before { content:"normal: "; opacity:.75; }
.tile .r .dot { font-weight:700; }
.e-good .dot{color:var(--good)} .e-warning .dot{color:var(--warn)}
.e-serious .dot{color:var(--serious)} .e-critical .dot{color:var(--critical)}
.key { display:flex; flex-wrap:wrap; gap:.9rem; font-size:.78rem; color:var(--dim); margin:.1rem 0 .9rem; }
.key b { font-weight:600; }
.resumo { border:1px solid var(--line); border-radius:10px; padding:.85rem 1rem; margin:0 0 1.5rem; }
.resumo h3 { margin:0 0 .45rem; font-size:.9rem; }
.resumo li { margin:.15rem 0; font-size:.9rem; }
.resumo ul { margin:0; padding-left:1.1rem; }

.day { cursor:pointer; }
.day:hover, .day:focus-visible { border-color:var(--s1); }
.day .ver { font-size:.74rem; color:var(--s1); margin-top:.45rem; }
dialog { border:1px solid var(--line); border-radius:14px; background:var(--bg); color:var(--fg);
  padding:0; max-width:min(46rem, 92vw); width:100%; }
dialog::backdrop { background:rgba(0,0,0,.55); }
.modal { padding:1.5rem 1.6rem 1.7rem; position:relative; }
.modal .quando { font-size:.78rem; text-transform:uppercase; letter-spacing:.06em; color:var(--dim); }
.modal h3 { margin:.25rem 0 .5rem; font-size:1.5rem; }
.modal .ritmo { padding:.6rem .8rem; border-radius:8px; font-weight:600;
  background:color-mix(in srgb, var(--s1) 12%, transparent); }
.modal .como { color:var(--dim); }
.modal .porque { font-size:.87rem; color:var(--dim); margin:1rem 0 0; }
.modal .fechar { position:absolute; top:.6rem; right:.9rem; border:0; background:none;
  color:var(--dim); font-size:1.6rem; cursor:pointer; line-height:1; }
""" + FIG_CSS

INTENSITY = [(85, "duro", "int.hard"), (50, "med", "int.moderate"),
             (1, "leve", "int.easy"), (0, "rest", "int.rest")]


def _intensity(load: float, ln: str) -> tuple[str, str]:
    for limit, css, chave in INTENSITY:
        if load >= limit:
            return css, _t(chave, ln)
    return "rest", _t("int.rest", ln)


def _mmss(segundos: int) -> str:
    return f"{segundos // 60}:{segundos % 60:02d}"


def _splits(parciais: list[dict], ln: str) -> str:
    """Um traço por quilómetro, com o comprimento a valer a velocidade."""
    if not parciais:
        return ""
    topo = max((p["kmh"] or 0) for p in parciais) or 1
    linhas = []
    for p in parciais:
        largura = round((p["kmh"] or 0) / topo * 100)
        extra = []
        if p.get("hr"):
            extra.append(f'{p["hr"]} bpm')
        if p.get("cadence"):
            extra.append(f'{p["cadence"]} spm')
        linhas.append(
            f'<div class=sp><span class=n>{p["n"]}</span>'
            f'<span class=barra style="width:{largura}%"></span>'
            f'<span class=v>{p["pace"]} /km'
            f'{f"<small>{escape(chr(183).join(extra))}</small>" if extra else ""}</span></div>')
    return (f'<div><h4>{_t("d.splits", ln)}</h4>{"".join(linhas)}</div>')


def _zonas(zonas: list[dict], ln: str) -> str:
    total = sum(z["seconds"] for z in zonas) or 1
    barras = "".join(
        f'<i class=z{z["n"]} style="width:{z["seconds"] / total * 100:.1f}%" '
        f'title="Z{z["n"]}, {_mmss(z["seconds"])}"></i>'
        for z in zonas if z["seconds"])
    legenda = " ".join(
        f'<span><b>Z{z["n"]}</b> {_mmss(z["seconds"])}'
        + (f' <span title="{_t("d.zone_from", ln, bpm=z["low"])}">{z["low"]}+</span>'
           if z.get("low") else "") + '</span>'
        for z in zonas if z["seconds"])
    return (f'<div><h4>{_t("d.zones", ln)}</h4><div class=zonas>{barras}</div>'
            f'<div class=zleg>{legenda}</div></div>')


def _tsb_state(tsb: float, ln: str) -> tuple[str, str, str]:
    """Class, label and icon. Colour never travels alone."""
    if tsb < -25:
        return "b-crit", _t("tsb.fadiga", ln), "▼"
    if tsb < -10:
        return "b-serious", _t("tsb.cansado", ln), "▽"
    if tsb > 10:
        return "b-good", _t("tsb.fresco", ln), "△"
    return "b-good", _t("tsb.equilibrio", ln), "●"


def _meter(ficha: dict, compacto: bool = False, ln: str = "en") -> str:
    """Onde o valor cai entre o mau e o bom.

    Sem isto, "a corrigir" é um rótulo sem fasquia: diz que está mal, mas não
    diz quão longe do bom, nem para onde é preciso andar.
    """
    e = ficha.get("escala")
    if not e:
        return ""
    zonas = "".join(f'<i class="z-{ESTADOS[z["estado"]][0]}" style="width:{z["largura"]}%"></i>'
                    for z in e["zonas"])
    limite = lambda x: f"{x:g}"
    if compacto:
        return (f'<div class="meter mini"><div class=track>{zonas}'
                f'<b class=marker style="left:{e["pos"]}%"></b></div></div>')
    return (f'<div class=meter><div class=track>{zonas}'
            f'<b class=marker style="left:{e["pos"]}%"></b></div>'
            f'<div class=scale><span>{limite(e["min"])}</span>'
            f'<span>{limite(e["max"])}</span></div>'
            f'<div class=alvo>{escape(ficha["alvo"])}</div></div>')


def _linha(ficha: dict, ln: str) -> str:
    """Versão de uma linha, para o que está dentro do normal.

    Oito mosaicos do mesmo tamanho obrigam a ler os oito para descobrir os
    três que interessam. O que está bem confirma-se de relance; só o que está
    fora do sítio merece espaço.
    """
    css, icone, _chave = ESTADOS[ficha["estado"]]
    unidade = f' <span class=u>{escape(ficha["unidade"])}</span>' if ficha["unidade"] else ""
    return (f'<div class="linha e-{css}"><span class=nome>{escape(ficha["titulo"])}</span>'
            f'<span class=val>{ficha["valor"]}{unidade}</span>'
            f'<span class=diz><span class=dot>{icone}</span> {escape(ficha["leitura"])}</span>'
            f'{_meter(ficha, compacto=True)}</div>')


def _tile(ficha: dict, ln: str) -> str:
    """Um número, onde ele cai, o que significa, e o que fazer."""
    css, icone, _chave = ESTADOS[ficha["estado"]]
    rotulo = ficha.get("rotulo") or _t(_chave, ln)
    unidade = f' <span class=u>{escape(ficha["unidade"])}</span>' if ficha["unidade"] else ""
    gloss = f'<div class=g>{escape(ficha["gloss"])}</div>' if ficha["gloss"] else ""
    acao = f'<div class=acao>{escape(ficha["acao"])}</div>' if ficha.get("acao") else ""
    return (f'<div class="tile e-{css}">'
            f'<div class=head><span class=k>{escape(ficha["titulo"])}</span>'
            f'<span class=r style="margin:0"><span class=dot>{icone}</span> <b>{rotulo}</b></span></div>'
            f'<div class=v>{ficha["valor"]}{unidade}</div>{gloss}'
            f'{_meter(ficha, ln=ln)}'
            f'<div class=r>{escape(ficha["leitura"])}</div>{acao}</div>')


def _legenda(ln: str) -> str:
    pares = [("good", "●", "state.good"), ("warning", "◐", "state.watch"),
             ("serious", "◑", "state.fix"), ("critical", "▲", "state.alert")]
    itens = "".join(f'<span class=e-{c}><b class=dot>{i}</b> {_t(k, ln)}</span>'
                    for c, i, k in pares)
    return f'<div class=key>{itens}<span>{_t("ui.sorted_by", ln)}</span></div>'


def _chart(weeks: list[dict], ln: str) -> str:
    """Carga por semana. Uma série, comprimento a codificar a magnitude."""
    ordered = list(reversed(weeks))
    top = max((w["load"] for w in ordered), default=0) or 1
    cols, axis = [], []
    for w in ordered:
        altura = round(w["load"] / top * 100)
        barra = (f'<div class=bar style="height:{altura}%"></div>' if w["load"]
                 else '<div class=zero></div>')
        cols.append(
            f'<div class=col><span class=tip>{w["start"]} / {w["end"]} · '
            f'{w["sessions"]}× · {w["minutes"]} min · {w["km"]} km</span>'
            f'<span class=n>{w["load"]}</span>{barra}</div>')
        axis.append(f'<span>{w["start"][5:]}</span>')
    # Linha da média: sem ela, "319" e "134" são só dois números altos.
    media = round(sum(w["load"] for w in ordered) / len(ordered)) if ordered else 0
    marca = (f'<div class=media style="bottom:{round(media / top * 100)}%">'
             f'<span>{_t("ui.average", ln, n=media)}</span></div>') if media else ""
    return (f'<div class=plot><div class=chart>{"".join(cols)}</div>{marca}</div>'
            f'<div class=axis>{"".join(axis)}</div>')


def _plan(days: list[dict], hoje: str, ln: str) -> str:
    cards = []
    for d in days:
        css, label = _intensity(d["load_est"], ln)
        minutos = f'{d["duration_min"]} min' if d["duration_min"] else _t("ui.no_training", ln)
        cards.append(
            f'<div class="day {css}{" hoje" if d["date"] == hoje else ""}" '
            f'data-dia="{d["date"]}" role=button tabindex=0>'
            f'<span class=tip>{escape(d.get("motivo", label))}</span>'
            f'<div class=d>{d["weekday"][:3]} {d["date"][8:]}/{d["date"][5:7]}</div>'
            f'<div class=s>{escape(d["name"])}</div>'
            f'<div class=m>{minutos}</div>'
            + (f'<div class=ritmo>{escape(d["ritmo"])}</div>' if d.get("ritmo") else "")
            + f'<div class=desc>{escape(d.get("description", ""))}</div>'
            + f'<div class=ver>{_t("ui.see_session", ln)}</div></div>')
    return f'<div class=plan>{"".join(cards)}</div>{"".join(_modal(x, ln) for x in days)}'


def _modal(d: dict, ln: str) -> str:
    """A sessão inteira, ao clicar no dia.

    O cartão tem de caber numa grelha. O modal não tem essa desculpa, e é onde
    cabe a linha de tempo e o desenho de cada exercício.
    """
    dur = f' · {d["duration_min"]} min' if d["duration_min"] else ""
    partes = [f'<div class=quando>{d["weekday"]}, {d["date"]}{dur}</div>',
              f'<h3>{escape(d["name"])}</h3>']
    if d.get("ritmo"):
        partes.append(f'<p class=ritmo>{escape(d["ritmo"])}</p>')
    if d.get("description"):
        partes.append(f'<p class=como>{escape(d["description"])}</p>')
    if d.get("estrutura"):
        partes.append(linha_tempo(d["estrutura"], ln))
    if d.get("exercicios"):
        partes.append(exercicios(d["exercicios"], ln))
    if d.get("motivo"):
        partes.append(f'<p class=porque>{_t("ui.why_this", ln)}: {escape(d["motivo"])}</p>')
    return (f'<dialog id="dia-{d["date"]}"><div class=modal>'
            f'<button class=fechar aria-label=Fechar>&times;</button>'
            f'{"".join(partes)}</div></dialog>')


_FORTE = re.compile(r"\*\*(.+?)\*\*", re.S)
_ITEM = re.compile(r"^(?:[*\-\u2022]|(\d+)[.)])\s+")


def _inline(texto: str) -> str:
    """Escapa primeiro, converte depois, e por esta ordem de propósito.

    Assim o único markup que chega ao ecrã é o que aqui se reconhece. O que o
    modelo escrever com sinais de menor ou maior sai como texto, não como
    etiqueta.
    """
    return _FORTE.sub(r"<strong>\1</strong>", escape(texto.strip()))


def _prose(text: str | None, ln: str, larga: bool = False) -> str:
    """O texto do modelo, em HTML.

    As secções de forma fixa pedem duas frases e é isso que recebem. A secção
    livre não: quem a escreveu pede o que quiser, e um pedido com alíneas vem
    respondido em markdown. Escapado linha a linha, aparecia no ecrã com os
    asteriscos à mostra. Reconhece-se o pouco que o modelo usa, negrito e as
    duas espécies de lista, e o resto continua a ser parágrafo.
    """
    if not text:
        return f'<p class=legend>{_t("ui.no_text", ln)}</p>'

    cls = "prose larga" if larga else "prose"
    blocos: list[str] = []
    itens: list[str] = []
    tipo = ""
    inicio = 1

    def fechar() -> None:
        nonlocal itens, tipo
        if itens:
            # O modelo escreve listas sem indentação, por isso os pontos com
            # asterisco no meio de uma lista numerada não são uma sublista: são
            # uma interrupção. Retomar em <ol> voltava a numerar em 1, e o "4."
            # que ele escreveu aparecia como "1.". O start repõe a contagem.
            abre = f'<ol start="{inicio}">' if tipo == "ol" and inicio != 1 else f"<{tipo}>"
            blocos.append(f"{abre}{''.join(itens)}</{tipo}>")
            itens, tipo = [], ""

    for linha in text.split("\n"):
        linha = linha.strip()
        if not linha:
            continue
        marca = _ITEM.match(linha)
        if marca:
            # "3.3 km" não é uma alínea: o \s+ do padrão exige espaço a seguir
            # ao ponto, e "**Ações:**" também não, pelo mesmo motivo.
            novo = "ol" if marca.group(1) else "ul"
            if novo != tipo:
                fechar()
                tipo = novo
                inicio = int(marca.group(1)) if novo == "ol" else 1
            itens.append(f"<li>{_inline(linha[marca.end():])}</li>")
        else:
            fechar()
            blocos.append(f"<p>{_inline(linha)}</p>")
    fechar()
    return f'<div class="{cls}">{"".join(blocos)}</div>'


def _seguir(dia: dict, hoje: str, ln: str) -> str:
    """A sessão seguinte, escrita por extenso.

    O plano dizia "Corrida fácil, 35 min", que não chega para saber o que
    fazer: a que ritmo, com que intervalos, quanto tempo a aquecer. A
    descrição estava no catálogo desde o início e nunca chegava ao ecrã.
    """
    quando = (_t("ui.today", ln) if dia["date"] == hoje
              else f'{_t("ui.tomorrow", ln)}, {dia["weekday"]}')
    dur = f' <span class=dur>{dia["duration_min"]} min</span>' if dia["duration_min"] else ""
    como = f'<p class=como>{escape(dia.get("description", ""))}</p>' if dia.get("description") else ""
    ritmo = f'<p class=ritmo>{escape(dia["ritmo"])}</p>' if dia.get("ritmo") else ""
    porque = f'<p class=porque>{escape(dia["motivo"])}</p>' if dia.get("motivo") else ""
    return (f'<div class=seguir><div class=quando>{quando}, {dia["date"]}</div>'
            f'<h2>{escape(dia["name"])}{dur}</h2>{ritmo}{como}{porque}</div>')


def report_html(d: dict) -> str:
    m, plan = d["metrics"], d["plan"]
    load, rec, month = m["load"], m["recovery"], m["month"]
    hoje = d["generated"]
    ln = d.get("language") or "en"
    fichas = d.get("assessment") or []
    cls, estado, icone = _tsb_state(load["tsb"], ln)

    # Separar o que pede ação do que só precisa de confirmação. Antes, a mesma
    # informação aparecia três vezes: numa caixa de resumo, nos mosaicos, e
    # outra vez em texto na análise.
    problemas = [f for f in fichas if f["estado"] != "bom"]
    calmas = [f for f in fichas if f["estado"] == "bom"]

    if problemas:
        estado_html = (
            f'<h2>{_t("ui.needs_attention", ln)} <span class=conta>'
            f'{_t("ui.of", ln, n=len(problemas), total=len(fichas))}</span></h2>'
            f'{_legenda(ln)}<div class=tiles>{"".join(_tile(f, ln) for f in problemas)}</div>')
    else:
        estado_html = (f'<h2>{_t("ui.all_good", ln)}</h2>'
                       f'<p class=legend>{_t("ui.all_good_sub", ln)}</p>')
    if calmas:
        estado_html += (
            f'<h2>{_t("ui.within_normal", ln)} <span class=conta>{len(calmas)}</span></h2>'
            f'<div class=calmas>{"".join(_linha(f, ln) for f in calmas)}</div>')

    objetivo_html = ""
    if (d.get("objetivo") or {}).get("perder_peso"):
        objetivo_html = f'<p class=legend>{_t("ui.weight_goal", ln)}</p>'

    # O comentário à sessão que acabou de ser feita. Estava a ser gerado e
    # guardado, e nunca chegava ao ecrã.
    custom = d.get("custom_section")
    custom_html = (f'<h2>{_t("ui.section_title", ln)}</h2>{_prose(custom, ln, larga=True)}'
                   if custom else "")

    correu_html = ""
    sessao = (m.get("sessao") or {})
    comentario = d.get("sessao_comentario")
    if sessao.get("has_data") and (comentario or sessao.get("veredicto")):
        factos = []
        if sessao.get("kmh"):
            factos.append(f'{sessao["kmh"]} km/h')
        if sessao.get("avg_hr"):
            factos.append(f'{sessao["avg_hr"]} bpm')
        factos.append(f'{_t("ui.load", ln)} {sessao["load"]}')
        if sessao.get("max_hr"):
            factos.append(_t("d.max_hr", ln, hr=sessao["max_hr"]))
        if (sessao.get("weather") or {}).get("temp") is not None:
            factos.append(f'{sessao["weather"]["temp"]}°C')
        detalhe = _splits(sessao.get("splits") or [], ln) + _zonas(sessao["zones"], ln) \
            if sessao.get("zones") else _splits(sessao.get("splits") or [], ln)
        correu_html = (
            f'<div class=correu><div class=rotulo><b>{escape(APP)}</b> '
            f'{_t("ui.como_correu", ln)}</div>'
            f'<p>{escape(comentario or sessao["veredicto"])}</p>'
            f'<div class=factos>{escape(desporto(sessao["sport"], ln))}, '
            f'{sessao["minutes"]} min, {" · ".join(factos)}</div>'
            + (f'<div class=detalhe>{detalhe}</div>' if detalhe else "") + '</div>')

    if d.get("today_done"):
        s = d["today_done"]
        km = f', {s["km"]} km' if s["km"] else ""
        agora = (f'<b>{_t("ui.already_trained", ln)}</b> {escape(desporto(s["sport"], ln))}, '
                 f'{s["minutes"]} min{km}, {_t("ui.load", ln)} {s["load"]}. '
                 f'<span class=muted>{_t("ui.plan_tomorrow", ln)}</span>')
    else:
        p0 = plan["days"][0]
        dur = f', {p0["duration_min"]} min' if p0["duration_min"] else ""
        agora = f'<b>Hoje: {escape(p0["name"])}</b>{dur}'

    flags = ""
    if d["flags"]:
        itens = "".join(f"<li>{escape(f)}</li>" for f in d["flags"])
        flags = (f'<div class=callout><h3>⚠ {_t("ui.flags", ln)}</h3><ul>{itens}</ul>'
                 f'<p class=legend>{_t("ui.flags_sub", ln)}</p></div>')

    sessoes = "".join(
        f'<tr><td>{s["date"]}</td><td>{escape(desporto(s["sport"], ln))}</td>'
        f'<td class=num>{s["minutes"]}</td><td class=num>{s["km"] or ""}</td>'
        f'<td class=num>{s["avg_hr"] or ""}</td><td class=num>{s["load"]}</td></tr>'
        for s in m["recent"])

    # "Como correu" e "A seguir" respondem às duas perguntas do momento e são
    # cartões da mesma ordem de grandeza, por isso enchem bem uma linha a dois.
    # Empilhados deixavam meio ecrã em branco. Sem sessão para comentar, o que
    # vem a seguir fica com a linha inteira, que é o que faz sentido sozinho.
    seguir_html = _seguir(plan["days"][0], hoje, ln)
    topo = (f'<div class=painéis><div class=painel>{correu_html}</div>'
            f'<div class=painel>{seguir_html}</div></div>'
            if correu_html else seguir_html)

    resumo = plan["summary"]
    n_duras = month["hard_sessions"]
    duras_txt = (_t("ui.one_hard", ln) if n_duras == 1
                 else _t("ui.n_hard", ln, n=n_duras))
    return f"""<div class=viz>
<div class=hero><h1>{_t("ui.training", ln)}</h1><span class=date>{hoje}</span>
  <span class="badge {cls}">{icone} {estado}</span></div>

<div class=today>{agora}</div>
{topo}
{custom_html}
{flags}

{estado_html}

<div class=painéis>
  <div class=painel>
    <h2>{_t("ui.analysis", ln)}</h2>
    {_prose(d.get("analysis"), ln)}
  </div>
  <div class=painel>
    <h2>{_t("ui.weekly_load", ln)}</h2>
    {_chart(month["weeks"], ln)}
    <p class=legend>{_t("ui.ramp", ln)}: <b>{escape(d["ramp_verdict"])}</b>.
      {_t("ui.summary_28d", ln, duras=duras_txt, descanso=month["rest_days"],
          longa=month["longest_min"])}</p>
  </div>
</div>

<h2>{_t("ui.plan", ln, n=len(plan["days"]))}</h2>
{_plan(plan["days"], hoje, ln)}
<p class=legend>{_t("ui.plan_summary", ln, s=resumo["sessions"], h=resumo["hard"],
                    min=resumo["minutes"], a=resumo["ctl_start"], b=resumo["ctl_end"],
                    tsb=resumo["tsb_end"])}</p>
{objetivo_html}

<div class=painéis>
  <div class=painel>
    <h2>{_t("ui.recommendation", ln)}</h2>
    {_prose(d.get("review"), ln)}
    <h3>{_t("ui.when_to_ease", ln)}</h3>
    <p class=legend>{escape(d["slow_down"])}</p>
  </div>
  <div class=painel>
    <h2>{_t("ui.recent", ln)}</h2>
    <div class=wrap><table>
      <tr><th>{_t("th.date", ln)}</th><th>{_t("th.sport", ln)}</th>
          <th class=num>{_t("th.min", ln)}</th><th class=num>{_t("th.km", ln)}</th>
          <th class=num>{_t("th.hr", ln)}</th><th class=num>{_t("th.load", ln)}</th></tr>
      {sessoes}
    </table></div>
  </div>
</div>

<hr>
<p class=legend>{_t("ui.disclaimer", ln)}</p>
</div>"""
