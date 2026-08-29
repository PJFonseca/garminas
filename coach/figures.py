#!/usr/bin/env python3
"""Desenhos das sessões, em SVG escrito à mão.

"Afundos" e "elevação de gémeos" são nomes que só ajudam quem já os conhece.
Um boneco de traços resolve isso melhor do que um parágrafo.

Tudo é SVG inline com currentColor, por três razões: funciona sem ligação à
internet, o que interessa numa NAS; não depende de imagens de terceiros nem
das suas licenças; e acompanha o tema claro ou escuro sem uma segunda versão.
"""

from __future__ import annotations

from html import escape

from language import t as _t

# Cada figura desenha duas posições, a de partida e a de chegada, porque um
# exercício é um movimento e uma pose só conta metade.
FIGURAS: dict[str, str] = {
    "agachamento": '''
      <g><circle cx="22" cy="14" r="6"/><path d="M22 20v20M22 40l-6 18M22 40l6 18M14 26h16"/></g>
      <g><circle cx="70" cy="22" r="6"/><path d="M70 28v14M70 42l-10 8 2 10M70 42l8 8-1 10M62 32h16"/></g>
      <path class="seta" d="M44 36h12m0 0l-4-4m4 4l-4 4"/>''',
    "afundo": '''
      <g><circle cx="22" cy="14" r="6"/><path d="M22 20v20M22 40l-5 18M22 40l5 18M14 26h16"/></g>
      <g><circle cx="66" cy="16" r="6"/><path d="M66 22v20M66 42l14 6v10M66 42l-10 10v6M58 28h16"/></g>
      <path class="seta" d="M44 36h12m0 0l-4-4m4 4l-4 4"/>''',
    "gemeos": '''
      <g><circle cx="22" cy="14" r="6"/><path d="M22 20v22M22 42v16M14 58h16"/></g>
      <g><circle cx="70" cy="8" r="6"/><path d="M70 14v22M70 36v16M64 52l6 4 6-4"/></g>
      <path class="seta" d="M44 32h12m0 0l-4-4m4 4l-4 4"/>
      <path class="chao" d="M6 60h32M56 58h32"/>''',
    "prancha": '''
      <g><circle cx="18" cy="26" r="6"/><path d="M24 30h44M24 30l-4 12h8M68 30l6 14"/></g>
      <path class="chao" d="M8 46h76"/>''',
    "corrida": '''
      <g><circle cx="34" cy="12" r="6"/><path d="M34 18v18M34 36l-10 16M34 36l12 12 -2 10M34 24l-12 6M34 24l14 4"/></g>
      <path class="chao" d="M8 58h76"/>''',
    "caminhada": '''
      <g><circle cx="40" cy="12" r="6"/><path d="M40 18v20M40 38l-7 20M40 38l7 20M40 24l-8 12M40 24l9 10"/></g>
      <path class="chao" d="M8 58h76"/>''',
}

CSS = """
.fig { width:100%; max-width:11rem; height:auto; color:var(--fg); }
.fig g { fill:none; stroke:currentColor; stroke-width:2.5; stroke-linecap:round; stroke-linejoin:round; }
.fig circle { fill:none; }
.fig .seta { stroke:var(--s1); stroke-width:2; fill:none; stroke-linecap:round; }
.fig .chao { stroke:var(--line); stroke-width:2; }

.exs { display:grid; grid-template-columns:repeat(auto-fit,minmax(13rem,1fr)); gap:1rem; margin:1rem 0 0; }
.ex { border:1px solid var(--line); border-radius:10px; padding:.9rem; text-align:center; }
.ex .nome { font-weight:650; margin-top:.4rem; }
.ex .series { font-size:.85rem; color:var(--dim); }
.ex .dica { font-size:.82rem; color:var(--dim); margin-top:.35rem; text-align:left; }

.tl { display:flex; height:2.2rem; border-radius:8px; overflow:hidden; margin:.9rem 0 .35rem; }
.tl i { display:block; position:relative; }
.tl .t-facil { background:color-mix(in srgb, var(--s1) 35%, transparent); }
.tl .t-forte { background:var(--s1); }
.tl .t-andar { background:color-mix(in srgb, var(--s1) 14%, transparent); }
.tl-leg { display:flex; gap:1rem; font-size:.78rem; color:var(--dim); flex-wrap:wrap; }
.tl-leg span::before { content:""; display:inline-block; width:.7rem; height:.7rem; border-radius:3px;
  margin-right:.35rem; vertical-align:-1px; }
.tl-leg .l-facil::before { background:color-mix(in srgb, var(--s1) 35%, transparent); }
.tl-leg .l-forte::before { background:var(--s1); }
.tl-leg .l-andar::before { background:color-mix(in srgb, var(--s1) 14%, transparent); }
"""


def _texto(item: dict, campo: str, ln: str) -> str:
    """Aceita texto simples ou um dicionário por língua, com recurso a inglês."""
    valor = item.get(campo, "")
    if isinstance(valor, dict):
        return valor.get(ln) or valor.get("en") or next(iter(valor.values()), "")
    return valor


def figura(nome: str) -> str:
    corpo = FIGURAS.get(nome)
    if not corpo:
        return ""
    return f'<svg class=fig viewBox="0 0 92 66" role=img aria-label="{escape(nome)}">{corpo}</svg>'


def exercicios(lista: list[dict], ln: str = "en") -> str:
    if not lista:
        return ""
    cartoes = "".join(
        f'<div class=ex>{figura(e.get("figura", ""))}'
        f'<div class=nome>{escape(_texto(e, "nome", ln))}</div>'
        f'<div class=series>{escape(_texto(e, "series", ln))}</div>'
        f'<div class=dica>{escape(_texto(e, "dica", ln))}</div></div>'
        for e in lista)
    return f'<div class=exs>{cartoes}</div>'


def expandir(estrutura: list) -> list[dict]:
    """Desdobra os blocos repetidos: 8 x (1 min forte / 90 s a andar)."""
    saida = []
    for bloco in estrutura or []:
        if "repete" in bloco:
            for _ in range(int(bloco["repete"])):
                saida.extend(bloco["blocos"])
        else:
            saida.append(bloco)
    return saida


def linha_tempo(estrutura: list, ln: str = "en") -> str:
    """A sessão vista de lado, do aquecimento ao arrefecimento."""
    passos = expandir(estrutura)
    if not passos:
        return ""
    total = sum(float(p["min"]) for p in passos) or 1
    barras = "".join(
        f'<i class="t-{p["tipo"]}" style="width:{float(p["min"]) / total * 100:.2f}%" '
        f'title="{escape(_texto(p, "nome", ln))}, {p["min"]} min"></i>'
        for p in passos)
    usados = []
    for p in passos:
        if p["tipo"] not in usados:
            usados.append(p["tipo"])
    legenda = "".join(f'<span class=l-{u}>{_t("tl." + {"facil":"easy","forte":"hard","andar":"walking"}.get(u, u), ln)}</span>' for u in usados)
    return (f'<div class=tl>{barras}</div>'
            f'<div class=tl-leg>{legenda}<span style="margin-left:auto">'
            f'{_t("tl.total", ln, n=round(total))}</span></div>')
