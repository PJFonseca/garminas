#!/usr/bin/env python3
"""Interface web: configurar numa página, depois ler os relatórios.

Uma pessoa abre o browser, escolhe o modelo, escreve as credenciais da Garmin
e carrega em começar. A partir daí a aplicação trata de tudo: descarrega o
modelo, guarda as credenciais como o upstream as guardaria, sincroniza o
histórico, pede o código de dois passos se for preciso, e escreve o primeiro
relatório. Nunca é preciso um terminal.

Depois de configurado, a mesma página passa a mostrar o relatório do dia.
"""

from __future__ import annotations

import json
import os
import pty
import re
import select
import subprocess
import sys
import hashlib
import threading
import time
from datetime import date
from html import escape
from pathlib import Path

import markdown
from flask import Flask, jsonify, redirect, request, send_file, session

sys.path.insert(0, str(Path(__file__).parent))
from setup import CATALOGUE, META, TARGET, human  # noqa: E402
from setup import download as download_model  # noqa: E402
import perfis  # noqa: E402
from report_html import CSS as VIZ_CSS, report_html  # noqa: E402

DATA = Path(os.environ.get("GARMIN_DATA_DIR_ROOT", "/data"))

HOST = os.environ.get("WEB_HOST", "0.0.0.0")
PORT = int(os.environ.get("WEB_PORT", "8090"))

MFA_PROMPT = re.compile(r"MFA code", re.I)

# O pseudo-terminal convence os programas de que falam com um terminal a
# cores, e eles passam a intercalar sequências de escape. No browser isso
# aparece como lixo do género "[0m" no meio das frases.
ANSI = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07]*\x07|[@-Z\\-_])")

# Como o upstream reporta o avanço, lido do seu código: parte o histórico em
# anos, do mais recente para trás, e anuncia "[ 50%] Year 3/6" ao entrar em
# cada um. Dentro de cada ano faz duas passagens, uma por dias ("Days
# 232-238/366") e outra por blocos mensais ("Chunk 5/13"), e ambas recomeçam
# do zero. Seguir só uma delas dá uma barra que salta para trás; seguir só os
# anos dá uma barra que fica parada durante minutos.
#
# Portanto: o ano define a banda, a passagem em curso enche-a, e o resultado
# nunca recua.
YEAR = re.compile(r"Year\s+(\d+)\s*/\s*(\d+)")
INNER = [
    (re.compile(r"Days\s+\d+\s*-\s*(\d+)\s*/\s*(\d+)"), "dia {a} de {b}"),
    (re.compile(r"Chunk\s+(\d+)\s*/\s*(\d+)"), "bloco {a} de {b}"),
    (re.compile(r"(\d+)\s*/\s*(\d+)\s+downloaded"), "ficheiro {a} de {b}"),
]
FINISHED = re.compile(r"\[\s*100%\s*\]\s*Done")


class SyncProgress:
    """Traduz o que o upstream imprime numa percentagem que não mente."""

    def __init__(self) -> None:
        self.year, self.years = 1, 1
        self.pct = 0.0
        self.step: str | None = None

    def feed(self, line: str) -> None:
        found = YEAR.search(line)
        if found:
            self.year, self.years = int(found.group(1)), max(1, int(found.group(2)))
            self._set((self.year - 1) / self.years, f"ano {self.year} de {self.years}")
            return

        if FINISHED.search(line):
            self._set(1.0, None)
            return

        for pattern, shape in INNER:
            found = pattern.search(line)
            if found:
                a, b = int(found.group(1)), max(1, int(found.group(2)))
                inner = min(1.0, a / b)
                banda = f"ano {self.year} de {self.years} · " if self.years > 1 else ""
                self._set((self.year - 1 + inner) / self.years,
                          banda + shape.format(a=a, b=b))
                return

    def _set(self, fraction: float, step: str | None) -> None:
        self.pct = max(self.pct, min(1.0, fraction) * 100)   # nunca recua
        if step:
            self.step = step


# Nomes internos das fases e o que a pessoa lê.
PHASES = {
    "parado": "A começar",
    "modelo": "A descarregar o modelo de linguagem",
    "garmin": "A ligar à Garmin e a puxar o histórico",
    "relatório": "A escrever o primeiro relatório",
    "pronto": "Pronto",
    "erro": "Falhou",
}

app = Flask(__name__)

# Chave de sessão gerada uma vez e guardada, para que reiniciar o container
# não deite fora quem já entrou.
_chave = DATA / ".sessao.key"
if not _chave.exists():
    DATA.mkdir(parents=True, exist_ok=True)
    _chave.write_bytes(os.urandom(32))
    _chave.chmod(0o600)
app.secret_key = _chave.read_bytes()


def desbloqueados() -> set:
    return set(session.get("perfis", []))


def pode_ver(p: dict) -> bool:
    """Sem senha, qualquer pessoa da casa vê. Com senha, só quem a souber."""
    return not p["tem_senha"] or p["slug"] in desbloqueados()


def cifra(senha: str) -> str:
    return hashlib.sha256(("garmin-nas:" + senha).encode()).hexdigest()


class Job:
    """O trabalho de configuração a decorrer. Só um de cada vez."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.phase = "parado"
        self.log: list[str] = []
        self.progress: int | None = None
        self.needs_mfa = False
        self.mfa_code: str | None = None
        self.error: str | None = None
        self.step: str | None = None
        self.sync = SyncProgress()
        self.started: float | None = None
        self.slug: str | None = None
        self.done = False
        self.running = False

    def say(self, line: str) -> None:
        line = ANSI.sub("", line).rstrip()
        if not line:
            return
        with self.lock:
            if self.log and self.log[-1] == line:
                return                   # o upstream repete-se muito
            self.log.append(line)
            del self.log[:-400]          # o histórico completo não interessa

    def _eta(self) -> str | None:
        """Estimativa a partir do ritmo observado, não de um palpite fixo.

        Só aparece depois de 5% para não anunciar duas horas por causa dos
        primeiros segundos, que são sempre os mais lentos.
        """
        if not self.started or not self.progress or self.progress < 5 or self.done:
            return None
        decorrido = time.time() - self.started
        restante = decorrido * (100 - self.progress) / self.progress
        if restante < 90:
            return "falta menos de um minuto"
        if restante < 5400:
            return f"faltam cerca de {round(restante / 60)} min"
        return f"faltam cerca de {restante / 3600:.1f} h"

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "phase": PHASES.get(self.phase, self.phase),
                "needs_mfa": self.needs_mfa, "error": self.error,
                "done": self.done, "running": self.running,
                "progress": self.progress, "step": self.step,
                "eta": self._eta(), "slug": self.slug,
                "log": self.log[-40:],
            }


job = Job()


def configured() -> bool:
    return bool(perfis.listar())


def run_streaming(cmd: list[str], env: dict, mfa_ok: bool = False,
                  track: bool = False) -> bool:
    """Corre um comando ligado a um pseudo-terminal.

    O pty é indispensável: o upstream pede o código de dois passos com input(),
    e sem terminal esse pedido nunca aparece — o processo ficaria bloqueado
    para sempre sem dizer porquê.
    """
    master, slave = pty.openpty()
    proc = subprocess.Popen(cmd, stdin=slave, stdout=slave, stderr=slave,
                            env={**os.environ, **env}, close_fds=True)
    os.close(slave)

    buffer = ""
    try:
        while proc.poll() is None:
            if select.select([master], [], [], 0.5)[0]:
                try:
                    chunk = os.read(master, 4096).decode("utf-8", "replace")
                except OSError:
                    break
                if not chunk:
                    break
                buffer += chunk.replace("\r\n", "\n").replace("\r", "\n")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if not line.strip():
                        continue
                    job.say(line)
                    if track:
                        job.sync.feed(ANSI.sub("", line))
                        with job.lock:
                            job.progress = round(job.sync.pct)
                            job.step = job.sync.step

                if mfa_ok and MFA_PROMPT.search(buffer):
                    job.say(buffer.strip())
                    buffer = ""
                    with job.lock:
                        job.needs_mfa = True
                    while True:
                        with job.lock:
                            code = job.mfa_code
                            if code:
                                job.mfa_code, job.needs_mfa = None, False
                        if code:
                            os.write(master, (code + "\n").encode())
                            job.say("  (código enviado)")
                            break
                        if proc.poll() is not None:
                            break
                        time.sleep(0.5)
    finally:
        os.close(master)
    return proc.wait() == 0


def save_credentials(pasta: Path, email: str, password: str) -> None:
    """Mesmo formato e permissões que o upstream usa no seu próprio prompt.

    Sem este ficheiro a sincronização diária das 05:30 ficaria à espera que
    alguém escrevesse a palavra-passe num terminal que ninguém está a ver.
    """
    env = pasta / ".env"
    env.write_text(f"GARMIN_EMAIL={email}\nGARMIN_PASSWORD={password}\n")
    env.chmod(0o600)


def work(pasta: Path, model_id: str, email: str, password: str, senha: str = "") -> None:
    try:
        with job.lock:
            job.running, job.phase = True, "modelo"

        chosen = next((m for m in CATALOGUE if m["id"] == model_id), None)
        if chosen and not TARGET.exists():
            job.say(f"A descarregar {chosen['name']} ({human(chosen['mib'])}).")

            def progress(done_bytes: int, total: int) -> None:
                with job.lock:
                    job.progress = int(done_bytes * 100 / total) if total else None

            if not download_model(chosen, on_progress=progress):
                raise RuntimeError("o download do modelo falhou")
            META.write_text(f'{{"id": "{chosen["id"]}", "name": "{chosen["name"]}", '
                            f'"url": "{chosen["url"]}", "installed": "{date.today()}"}}')
            job.say("Modelo instalado.")
        elif TARGET.exists():
            job.say("Modelo já instalado, a passar à frente.")
        else:
            job.say("Sem modelo: o relatório sai com números e plano, sem texto.")

        with job.lock:
            job.phase, job.progress, job.step = "garmin", None, None
            job.sync, job.started = SyncProgress(), time.time()
        save_credentials(pasta, email, password)
        job.say(f"Credenciais guardadas em {pasta}/.env, legíveis só pelo dono.")
        job.say("A abrir o Chrome e a passar a proteção da Cloudflare. "
                "A primeira sincronização puxa o histórico todo e demora.")

        trinco = pasta / ".sync.lock"
        if trinco.exists():
            raise RuntimeError("já há uma sincronização a decorrer para este perfil")
        trinco.touch()
        try:
            ok = run_streaming(["xvfb-run", "-a", "garmin-givemydata", "--full"],
                               {"GARMIN_EMAIL": email, "GARMIN_PASSWORD": password,
                                "GARMIN_DATA_DIR": str(pasta)},
                               mfa_ok=True, track=True)
        finally:
            trinco.unlink(missing_ok=True)
        if not ok:
            raise RuntimeError("a sincronização com a Garmin falhou; vê o registo acima")

        with job.lock:
            job.phase = "relatório"
        job.say("A gerar o primeiro relatório.")
        if not run_streaming([sys.executable, "/opt/coach/coach.py"],
                             {"GARMIN_DATA_DIR": str(pasta)}):
            raise RuntimeError("o relatório falhou")

        # Só agora se sabe o nome verdadeiro: vem da Garmin, não de quem
        # escreveu o email. A pasta provisória passa a ter o nome certo.
        dados = perfis.registar(pasta)
        if senha:
            dados["senha"] = cifra(senha)
            perfis.escrever(pasta, dados)
        certo = perfis.slug(dados.get("primeiro") or pasta.name)
        if certo != pasta.name and not (perfis.PERFIS / certo).exists():
            pasta.rename(perfis.PERFIS / certo)
            pasta = perfis.PERFIS / certo

        with job.lock:
            job.phase, job.done, job.slug = "pronto", True, pasta.name
        job.say(f"Feito. Perfil de {dados.get('nome') or pasta.name} pronto.")
    except Exception as exc:                       # noqa: BLE001 — vai para o ecrã
        with job.lock:
            job.error, job.phase = str(exc), "erro"
        job.say(f"ERRO: {exc}")
    finally:
        with job.lock:
            job.running = False


# ── páginas ──────────────────────────────────────────────────────────────────

CSS = """
:root { --bg:#fbfaf8; --fg:#1a1a1a; --dim:#6b6b6b; --line:#e2ddd6; --accent:#0f6b4f; --warn:#8a4b00; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#16181a; --fg:#e8e6e3; --dim:#9a9a9a; --line:#2c2f33; --accent:#4fbf95; --warn:#d69a4a; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 46rem; margin: 0 auto; padding: 2rem 1.25rem 5rem; }
main.wide { max-width: 88rem; padding-inline: clamp(1.25rem, 3vw, 3rem); }
h1 { font-size:1.5rem; letter-spacing:-.02em; margin:0 0 .25rem; }
h2 { font-size:1.15rem; margin:2.25rem 0 .5rem; padding-bottom:.3rem; border-bottom:1px solid var(--line); }
h3 { font-size:1rem; margin:1.5rem 0 .4rem; }
.sub { color:var(--dim); margin:0 0 2rem; }
table { border-collapse:collapse; width:100%; margin:.75rem 0; font-size:.93rem; }
th,td { text-align:left; padding:.4rem .6rem; border-bottom:1px solid var(--line); }
th { font-weight:600; color:var(--dim); font-size:.82rem; text-transform:uppercase; letter-spacing:.04em; }
.wrap { overflow-x:auto; }
label { display:block; margin:.9rem 0 .25rem; font-weight:600; font-size:.92rem; }
input[type=text],input[type=email],input[type=password] { width:100%; padding:.55rem .7rem; font:inherit;
  border:1px solid var(--line); border-radius:6px; background:var(--bg); color:var(--fg); }
button { margin-top:1.5rem; padding:.6rem 1.4rem; font:inherit; font-weight:600; cursor:pointer;
  background:var(--accent); color:#fff; border:0; border-radius:6px; }
button:disabled { opacity:.5; cursor:default; }
.model { display:flex; gap:.7rem; align-items:flex-start; padding:.7rem; border:1px solid var(--line);
  border-radius:8px; margin-bottom:.5rem; cursor:pointer; }
.model:has(input:checked) { border-color:var(--accent); background:color-mix(in srgb, var(--accent) 7%, transparent); }
.model .size { color:var(--dim); font-size:.85rem; }
.model .note { color:var(--dim); font-size:.87rem; display:block; margin-top:.15rem; }
pre#log { background:color-mix(in srgb, var(--fg) 5%, transparent); border:1px solid var(--line); border-radius:8px;
  padding:.8rem; font-size:.82rem; line-height:1.45; max-height:22rem; overflow:auto; white-space:pre-wrap; }
.bar { height:.5rem; background:var(--line); border-radius:99px; overflow:hidden; margin:.6rem 0; }
.bar > i { display:block; height:100%; background:var(--accent); width:0; transition:width .3s; }
.bar.wait { background:linear-gradient(90deg, var(--line) 0 40%, var(--accent) 50%, var(--line) 60% 100%);
  background-size:250% 100%; animation:slide 1.6s linear infinite; }
@keyframes slide { from { background-position:100% 0 } to { background-position:-150% 0 } }
.err { color:var(--warn); font-weight:600; }
.note-box { border-left:3px solid var(--line); padding:.3rem 0 .3rem .9rem; color:var(--dim); font-size:.9rem; }
nav { display:flex; gap:1rem; font-size:.9rem; margin-bottom:1.5rem; }

/* Sem isto os links herdam o roxo de "visitado" do browser, que sobre fundo
   escuro quase não se vê. */
a, a:visited { color:var(--accent); text-decoration-color:color-mix(in srgb, var(--accent) 45%, transparent); }
a:hover { text-decoration-thickness:2px; }
nav a { text-decoration:none; }

.anteriores { display:flex; flex-wrap:wrap; gap:.4rem; margin:.6rem 0 0; }
.anteriores a { display:inline-block; padding:.3rem .7rem; border:1px solid var(--line);
  border-radius:99px; font-size:.85rem; text-decoration:none; font-variant-numeric:tabular-nums; }
.anteriores a:hover { border-color:var(--accent); }
.anteriores .hoje { border-color:var(--accent); font-weight:600; }

.gente { display:flex; flex-wrap:wrap; gap:1rem; margin:1.5rem 0; }
.pessoa { display:flex; flex-direction:column; align-items:center; gap:.6rem; width:8.5rem;
  padding:1.1rem .6rem; border:1px solid var(--line); border-radius:14px; text-decoration:none;
  color:var(--fg); }
.pessoa:hover { border-color:var(--accent); }
.pessoa img, .pessoa .iniciais { width:5rem; height:5rem; border-radius:50%; object-fit:cover;
  display:grid; place-items:center; background:color-mix(in srgb, var(--accent) 12%, transparent);
  font-size:2rem; font-weight:600; color:var(--accent); }
.pessoa .nome { font-weight:600; font-size:.95rem; text-align:center; }
.pessoa.nova .iniciais { background:none; border:1px dashed var(--line); }
.cadeado { color:var(--dim); }
nav .avatar { width:1.6rem; height:1.6rem; border-radius:50%; object-fit:cover; }
nav { align-items:center; }
nav b { margin-right:auto; }
hr { border:0; border-top:1px solid var(--line); margin:2rem 0; }
""" + VIZ_CSS

SHELL = """<!doctype html><html lang=pt><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>%(title)s</title><style>%(css)s</style><main class="%(cls)s">%(body)s</main>%(script)s"""


def page(title: str, body: str, script: str = "", wide: bool = False) -> str:
    """wide serve o relatório, que tem painéis; o formulário fica estreito,
    porque um campo de texto com 80 caracteres de largura não se lê melhor."""
    return SHELL % {"title": title, "css": CSS, "body": body,
                    "script": script, "cls": "wide" if wide else ""}


MODAL_JS = """<script>
document.querySelectorAll('.day[data-dia]').forEach(c => {
  const abrir = () => document.getElementById('dia-' + c.dataset.dia)?.showModal();
  c.addEventListener('click', abrir);
  c.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); abrir(); }
  });
});
document.querySelectorAll('dialog').forEach(d => {
  d.querySelector('.fechar')?.addEventListener('click', () => d.close());
  d.addEventListener('click', e => { if (e.target === d) d.close(); });
});
</script>"""


@app.get("/")
def home():
    """A porta de entrada: quem és tu, ou cria um perfil novo."""
    if job.snapshot()["running"]:
        return redirect("/progresso")
    gente = perfis.listar()
    if not gente:
        return redirect("/novo")

    cartoes = []
    for pessoa in gente:
        retrato = (f'<img src="/foto/{pessoa["slug"]}" alt="">' if pessoa["foto"]
                   else f'<span class=iniciais>{escape(pessoa["primeiro"][:1].upper())}</span>')
        cadeado = ' <span class=cadeado title="protegido por senha">•</span>' if pessoa["tem_senha"] else ""
        cartoes.append(
            f'<a class=pessoa href="/p/{pessoa["slug"]}">{retrato}'
            f'<span class=nome>{escape(pessoa["primeiro"])}{cadeado}</span></a>')

    cartoes.append('<a class="pessoa nova" href="/novo">'
                   '<span class=iniciais>+</span><span class=nome>Adicionar</span></a>')
    return page("garmin-nas", f"""
<h1>Quem vai treinar?</h1>
<p class=sub>Cada pessoa tem a sua conta Garmin e o seu relatório.</p>
<div class=gente>{"".join(cartoes)}</div>""")


@app.get("/foto/<slug>")
def foto(slug: str):
    pasta = perfis.pasta_de(slug)
    dados = perfis.ler(pasta) if pasta else {}
    if pasta and dados.get("foto") and (pasta / dados["foto"]).exists():
        return send_file(pasta / dados["foto"])
    return ("", 404)


@app.get("/p/<slug>")
@app.get("/p/<slug>/<day>")
def perfil(slug: str, day: str | None = None):
    pessoa = next((p for p in perfis.listar() if p["slug"] == slug), None)
    if not pessoa:
        return redirect("/")
    if not pode_ver(pessoa):
        return page(f'{pessoa["primeiro"]} — garmin-nas', f"""
<nav><a href="/">Voltar</a></nav>
<h1>{escape(pessoa["primeiro"])}</h1>
<p class=sub>Este perfil está protegido.</p>
<form method=post action="/entrar/{slug}">
  <label for=senha>Senha</label>
  <input type=password id=senha name=senha autofocus autocomplete=current-password>
  <button type=submit>Entrar</button>
</form>""")
    return relatorio_de(pessoa, day)


@app.post("/entrar/<slug>")
def entrar(slug: str):
    pasta = perfis.pasta_de(slug)
    dados = perfis.ler(pasta) if pasta else {}
    if dados.get("senha") and cifra(request.form.get("senha", "")) == dados["senha"]:
        session["perfis"] = sorted(desbloqueados() | {slug})
        session.permanent = True
    return redirect(f"/p/{slug}")


@app.get("/sair")
def sair():
    session.clear()
    return redirect("/")


def relatorio_de(pessoa: dict, day: str | None):
    pasta = Path(pessoa["dir"])
    reports = pasta / "reports"
    if not reports.exists():
        return page("garmin-nas", f'<nav><a href="/">Voltar</a></nav>'
                    f'<h1>Ainda não há relatórios</h1>'
                    f'<p class=sub>A primeira sincronização de {escape(pessoa["primeiro"])} '
                    f'ainda não correu.</p>')

    dias = sorted((f.stem for f in reports.glob("*.md") if f.stem != "latest"), reverse=True)
    stem = day or "latest"
    estruturado = reports / f"{stem}.json"
    if estruturado.exists():
        corpo = report_html(json.loads(estruturado.read_text()))
    else:
        alternativa = reports / f"{stem}.md"
        if not alternativa.exists():
            return page("garmin-nas", "<h1>Relatório não encontrado</h1>"), 404
        corpo = markdown.markdown(alternativa.read_text(), extensions=["tables"])
        corpo = corpo.replace("<table>", "<div class=wrap><table>").replace("</table>", "</table></div>")

    hoje = date.today().isoformat()
    anteriores = "".join(
        f'<a class="{"hoje" if d == hoje else ""}" href="/p/{pessoa["slug"]}/{d}">'
        f'{d}{" (hoje)" if d == hoje else ""}</a>' for d in dias[:14])
    retrato = (f'<img class=avatar src="/foto/{pessoa["slug"]}" alt="">' if pessoa["foto"] else "")
    return page(f'{pessoa["primeiro"]} — garmin-nas',
                f'<nav>{retrato}<b>{escape(pessoa["nome"])}</b>'
                f'<a href="/">Trocar de perfil</a><a href="/novo">Adicionar perfil</a>'
                f'{"<a href=/sair>Sair</a>" if pessoa["tem_senha"] else ""}</nav>{corpo}'
                f'<hr><h3>Relatórios anteriores</h3>'
                f'<div class=anteriores>{anteriores or "<span class=legend>nenhum</span>"}</div>',
                MODAL_JS, wide=True)


@app.get("/novo")
def novo():
    return setup_form()


def setup_form() -> str:
    options = "".join(
        f'''<label class=model><input type=radio name=model value="{m['id']}"
              {'checked' if i == 0 else ''}>
            <span><b>{m['name']}</b> <span class=size>{human(m['mib'])}</span>
            <span class=note>{m['note']}</span></span></label>'''
        for i, m in enumerate(CATALOGUE))

    ja_ha = bool(perfis.listar())
    modelo_ja = TARGET.exists()
    bloco_modelo = "" if modelo_ja else f"""
  <h2>Modelo de linguagem</h2>
  <p class=note-box>Corre no teu computador, não na nuvem. Escreve os comentários
  do relatório, e é partilhado por todos os perfis. Os números e o plano são
  calculados e não dependem dele.</p>
  {options}
  <label class=model><input type=radio name=model value=""><span><b>Nenhum</b>
    <span class=note>Relatório só com números, tabelas e plano.</span></span></label>"""

    return page("Novo perfil — garmin-nas", f"""
{'<nav><a href="/">Voltar</a></nav>' if ja_ha else ''}
<h1>{'Adicionar perfil' if ja_ha else 'garmin-nas'}</h1>
<p class=sub>{'Cada pessoa entra com a sua própria conta Garmin.'
              if ja_ha else 'Dá os acessos da Garmin e arranca.'}</p>

<form method=post action=/comecar>
  {bloco_modelo}
  {'<p class=note-box>O modelo já está instalado e serve todos os perfis.</p>' if modelo_ja else ''}

  <h2>Garmin Connect</h2>
  <p class=note-box>Ficam guardadas no disco desta máquina, legíveis só pelo dono,
  e são precisas outra vez a cada sincronização diária. Esta página não usa HTTPS,
  por isso escreve-as numa rede em que confies.</p>
  <label for=email>Email</label>
  <input type=email id=email name=email required autocomplete=username>
  <label for=password>Palavra-passe</label>
  <input type=password id=password name=password required autocomplete=current-password>
  <p class=note-box>Se tiveres verificação em dois passos, o código é pedido
  aqui mesmo, a meio do processo.</p>

  <h2>Senha deste perfil</h2>
  <p class=note-box>Opcional, e serve só para os relatórios não ficarem à vista
  de toda a casa. Não é segurança a sério: a página anda em HTTP simples na
  rede local.</p>
  <label for=senha>Senha, ou deixa em branco</label>
  <input type=password id=senha name=senha autocomplete=new-password>

  <button type=submit>Começar</button>
</form>""")


@app.post("/comecar")
def start():
    if job.snapshot()["running"]:
        return redirect("/progresso")
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    if not email or not password:
        return redirect("/novo")

    # Nome provisório, tirado do email. O verdadeiro só se sabe depois da
    # primeira sincronização, porque é a Garmin que o tem.
    base = perfis.slug(email.split("@")[0]) or "perfil"
    nome = base
    n = 2
    while (perfis.PERFIS / nome).exists():
        nome, n = f"{base}-{n}", n + 1
    pasta = perfis.criar(nome)

    job.reset()
    threading.Thread(target=work,
                     args=(pasta, request.form.get("model", ""), email, password,
                           request.form.get("senha", "").strip()),
                     daemon=True).start()
    return redirect("/progresso")


@app.get("/progresso")
def progress_page():
    return page("A configurar — garmin-nas", """
<h1>A configurar</h1>
<p class=sub id=phase>A começar…</p>
<div class=bar><i id=bar></i></div>
<p class=sub id=step></p>
<div id=mfa hidden>
  <h2>Código de verificação</h2>
  <p class=note-box>A Garmin pediu o código de dois passos. Escreve-o aqui.</p>
  <input type=text id=code inputmode=numeric autocomplete=one-time-code>
  <button id=sendcode type=button>Enviar código</button>
</div>
<h2>Registo</h2>
<pre id=log>a aguardar…</pre>
<p id=finished hidden><a id=verlink href=/>Ver o relatório</a></p>
""", """<script>
const $ = s => document.querySelector(s);
async function tick() {
  const s = await (await fetch('/estado')).json();
  $('#phase').textContent = s.error ? 'Falhou: ' + s.error : s.phase + '…';
  if (s.error) $('#phase').className = 'err';
  const indeterminado = s.running && s.progress === null;
  $('#bar').parentElement.classList.toggle('wait', indeterminado);
  $('#bar').style.width = indeterminado ? '0' : (s.progress ?? (s.done ? 100 : 0)) + '%';
  const partes = [];
  if (s.progress !== null && s.running) partes.push(s.progress + '%');
  if (s.step && s.running) partes.push(s.step);
  if (s.eta) partes.push(s.eta);
  $('#step').textContent = partes.join(' · ');
  $('#log').textContent = s.log.join('\\n') || 'a aguardar…';
  $('#log').scrollTop = $('#log').scrollHeight;
  $('#mfa').hidden = !s.needs_mfa;
  $('#finished').hidden = !s.done;
  if (s.slug) $('#verlink').href = '/p/' + s.slug;
  if (!s.done && !s.error) setTimeout(tick, 1500);
}
$('#sendcode').onclick = async () => {
  await fetch('/mfa', {method:'POST', headers:{'Content-Type':'application/json'},
                       body: JSON.stringify({code: $('#code').value.trim()})});
  $('#code').value = ''; $('#mfa').hidden = true;
};
tick();
</script>""")


@app.get("/estado")
def state():
    return jsonify(job.snapshot())


@app.post("/mfa")
def mfa():
    code = (request.get_json(silent=True) or {}).get("code", "").strip()
    if code:
        with job.lock:
            job.mfa_code = code
    return jsonify({"ok": bool(code)})


@app.get("/relatorio")
def relatorio_antigo():
    gente = perfis.listar()
    return redirect(f'/p/{gente[0]["slug"]}' if len(gente) == 1 else "/")



if __name__ == "__main__":
    perfis.PERFIS.mkdir(parents=True, exist_ok=True)
    movido = perfis.migrar()
    if movido:
        print(f"instalação antiga arrumada no perfil '{movido}'", flush=True)
    print(f"garmin-nas: http://{HOST}:{PORT}", flush=True)
    app.run(host=HOST, port=PORT, threaded=True)
