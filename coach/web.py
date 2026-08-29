#!/usr/bin/env python3
"""Web interface: set up on one page, then read the reports.

Uma person abre o browser, escolhe o modelo, escreve as credenciais da Garmin
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
import profiles  # noqa: E402
from language import APP, languages, pick  # noqa: E402
from language import t as _t  # noqa: E402
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
# cada um. Dentro de cada ano faz duas passagens, uma por days_list ("Days
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
]

# Depois dos anos de data vem a descarga dos ficheiros FIT, que pode ser a
# parte mais demorada de todas. É uma segunda fase, não a continuação da
# primeira: tratá-las como uma só punha a barra nos 100% com setecentos
# ficheiros ainda por descarregar.
FICHEIROS = re.compile(r"(\d+)\s*/\s*(\d+)\s+downloaded")
COMECOU_FICHEIROS = re.compile(r"Downloading\s+FIT\s+files\s*\((\d+)", re.I)

# Quanto da barra cabe a cada fase. Os anos são o grosso do tempo; os
# ficheiros, com ligação decente, andam depressa.
PESO_ANOS = 0.85
FINISHED = re.compile(r"\[\s*100%\s*\]\s*Done")


class SyncProgress:
    """Traduz o que o upstream imprime numa percentagem que não mente."""

    def __init__(self) -> None:
        self.year, self.years = 1, 1
        self.pct = 0.0
        self.step: str | None = None
        self.fase = "anos"

    def feed(self, line: str) -> None:
        if COMECOU_FICHEIROS.search(line):
            self.fase = "ficheiros"
            self._set(PESO_ANOS, "a descarregar ficheiros de treino")
            return

        found = FICHEIROS.search(line)
        if found:
            self.fase = "ficheiros"
            a, b = int(found.group(1)), max(1, int(found.group(2)))
            self._set(PESO_ANOS + (1 - PESO_ANOS) * min(1.0, a / b),
                      f"ficheiro {a} de {b}")
            return

        if self.fase == "ficheiros":
            return                    # os contadores dos anos já não se aplicam

        found = YEAR.search(line)
        if found:
            self.year, self.years = int(found.group(1)), max(1, int(found.group(2)))
            self._set((self.year - 1) / self.years * PESO_ANOS,
                      f"ano {self.year} de {self.years}")
            return

        if FINISHED.search(line):
            self._set(PESO_ANOS, None)
            return

        for pattern, shape in INNER:
            found = pattern.search(line)
            if found:
                a, b = int(found.group(1)), max(1, int(found.group(2)))
                inner = min(1.0, a / b)
                banda = f"ano {self.year} de {self.years} · " if self.years > 1 else ""
                self._set((self.year - 1 + inner) / self.years * PESO_ANOS,
                          banda + shape.format(a=a, b=b))
                return

    def _set(self, fraction: float, step: str | None) -> None:
        self.pct = max(self.pct, min(1.0, fraction) * 100)   # nunca recua
        if step:
            self.step = step


# Nomes internos das fases e o que a person lê.
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


def request_language() -> str:
    """Antes de existir um perfil não há conta para consultar, por isso vale o
    que o browser pede. Depois de existir, manda o perfil."""
    try:
        preferida = request.accept_languages.best_match(languages())
    except RuntimeError:                      # fora de um pedido
        preferida = None
    return pick(preferida)


def unlocked() -> set:
    return set(session.get("profiles", []))


def can_view(p: dict) -> bool:
    """Sem password_field, qualquer person da casa vê. Com password_field, só quem a souber."""
    return not p["has_password"] or p["slug"] in unlocked()


def password_hash(password_field: str) -> str:
    return hashlib.sha256(("garmin-nas:" + password_field).encode()).hexdigest()


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
    return bool(profiles.listing())


def run_streaming(cmd: list[str], env: dict, mfa_ok: bool = False,
                  track: bool = False) -> bool:
    """Corre um comando ligado a um pseudo-terminal.

    O pty é indispensável: o upstream pede o código de dois passos com input(),
    e sem terminal esse pedido nunca aparece, o processo ficaria bloqueado
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


def save_credentials(folder: Path, email: str, password: str) -> None:
    """Mesmo formato e permissões que o upstream usa no seu próprio prompt.

    Sem este ficheiro a sincronização diária das 05:30 ficaria à espera que
    alguém escrevesse a palavra-passe num terminal que ninguém está a ver.
    """
    env = folder / ".env"
    env.write_text(f"GARMIN_EMAIL={email}\nGARMIN_PASSWORD={password}\n")
    env.chmod(0o600)


def work(folder: Path, model_id: str, email: str, password: str, password_field: str = "") -> None:
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
        save_credentials(folder, email, password)
        job.say(f"Credenciais guardadas em {folder}/.env, legíveis só pelo dono.")
        job.say("A abrir o Chrome e a passar a proteção da Cloudflare. "
                "A primeira sincronização puxa o histórico todo e demora.")

        lockfile = folder / ".sync.lock"
        if lockfile.exists():
            raise RuntimeError("já há uma sincronização a decorrer para este perfil")
        lockfile.touch()
        try:
            ok = run_streaming(["xvfb-run", "-a", "garmin-givemydata", "--full"],
                               {"GARMIN_EMAIL": email, "GARMIN_PASSWORD": password,
                                "GARMIN_DATA_DIR": str(folder)},
                               mfa_ok=True, track=True)
        finally:
            lockfile.unlink(missing_ok=True)
        if not ok:
            raise RuntimeError("a sincronização com a Garmin falhou; vê o registo acima")

        with job.lock:
            job.phase = "relatório"
        job.say("A gerar o primeiro relatório.")
        if not run_streaming([sys.executable, "/opt/coach/coach.py"],
                             {"GARMIN_DATA_DIR": str(folder)}):
            raise RuntimeError("o relatório falhou")

        # Só agora se sabe o nome verdadeiro: vem da Garmin, não de quem
        # escreveu o email. A folder provisória passa a ter o nome proper.
        data = profiles.register(folder)
        if password_field:
            data["password_field"] = password_hash(password_field)
            profiles.write(folder, data)
        proper = profiles.slug(data.get("first") or folder.name)
        if proper != folder.name and not (profiles.PROFILES / proper).exists():
            folder.rename(profiles.PROFILES / proper)
            folder = profiles.PROFILES / proper

        with job.lock:
            job.phase, job.done, job.slug = "pronto", True, folder.name
        job.say(f"Feito. Perfil de {data.get('nome') or folder.name} pronto.")
    except Exception as exc:                       # noqa: BLE001, vai para o ecrã
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

.previous { display:flex; flex-wrap:wrap; gap:.4rem; margin:.6rem 0 0; }
.previous a { display:inline-block; padding:.3rem .7rem; border:1px solid var(--line);
  border-radius:99px; font-size:.85rem; text-decoration:none; font-variant-numeric:tabular-nums; }
.previous a:hover { border-color:var(--accent); }
.previous .today_str { border-color:var(--accent); font-weight:600; }

.people { display:flex; flex-wrap:wrap; gap:1rem; margin:1.5rem 0; }
.person { display:flex; flex-direction:column; align-items:center; gap:.6rem; width:8.5rem;
  padding:1.1rem .6rem; border:1px solid var(--line); border-radius:14px; text-decoration:none;
  color:var(--fg); }
.person:hover { border-color:var(--accent); }
.person img, .person .iniciais { width:5rem; height:5rem; border-radius:50%; object-fit:cover;
  display:grid; place-items:center; background:color-mix(in srgb, var(--accent) 12%, transparent);
  font-size:2rem; font-weight:600; color:var(--accent); }
.person .nome { font-weight:600; font-size:.95rem; text-align:center; }
.person.nova .iniciais { background:none; border:1px dashed var(--line); }
.lock { color:var(--dim); }
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
        return redirect("/progress")
    people = profiles.listing()
    if not people:
        return redirect("/new")

    cards = []
    for person in people:
        portrait = (f'<img src="/photo/{person["slug"]}" alt="">' if person["photo"]
                   else f'<span class=iniciais>{escape(person["first"][:1].upper())}</span>')
        lock = ' <span class=lock title="protegido por password_field">•</span>' if person["has_password"] else ""
        cards.append(
            f'<a class=person href="/p/{person["slug"]}">{portrait}'
            f'<span class=nome>{escape(person["first"])}{lock}</span></a>')

    ln = request_language()
    cards.append(f'<a class="person nova" href="/new">'
                   f'<span class=iniciais>+</span>'
                   f'<span class=nome>{_t("ui.adicionar", ln)}</span></a>')
    return page(APP, f"""
<h1>{_t("ui.quem", ln)}</h1>
<p class=sub>{_t("ui.quem_sub", ln)}</p>
<div class=people>{"".join(cards)}</div>""")


@app.get("/photo/<slug>")
def photo(slug: str):
    folder = profiles.folder_of(slug)
    data = profiles.read(folder) if folder else {}
    if folder and data.get("photo") and (folder / data["photo"]).exists():
        return send_file(folder / data["photo"])
    return ("", 404)


@app.get("/p/<slug>")
@app.get("/p/<slug>/<day>")
def profile_page(slug: str, day: str | None = None):
    person = next((p for p in profiles.listing() if p["slug"] == slug), None)
    if not person:
        return redirect("/")
    ln = pick(person.get("language"))
    if not can_view(person):
        return page(f'{person["first"]}, {APP}', f"""
<nav><a href="/">{_t("ui.voltar", ln)}</a></nav>
<h1>{escape(person["first"])}</h1>
<p class=sub>Este perfil está protegido.</p>
<form method=post action="/login/{slug}">
  <label for=password_field>Senha</label>
  <input type=password id=password_field name=password_field autofocus autocomplete=current-password>
  <button type=submit>Entrar</button>
</form>""")
    return report_for(person, day)


@app.post("/login/<slug>")
def login(slug: str):
    folder = profiles.folder_of(slug)
    data = profiles.read(folder) if folder else {}
    if data.get("password_field") and password_hash(request.form.get("password_field", "")) == data["password_field"]:
        session["profiles"] = sorted(unlocked() | {slug})
        session.permanent = True
    return redirect(f"/p/{slug}")


@app.get("/logout")
def logout():
    session.clear()
    return redirect("/")


def report_for(person: dict, day: str | None):
    ln = pick(person.get("language"))
    folder = Path(person["dir"])
    reports = folder / "reports"
    if not reports.exists():
        return page(APP, f'<nav><a href="/">{_t("ui.voltar", ln)}</a></nav>'
                    f'<h1>{_t("ui.sem_relatorios", ln)}</h1>'
                    f'<p class=sub>{_t("ui.sem_relatorios_sub", ln, nome=escape(person["first"]))}'
                    f'</p>')

    days_list = sorted((f.stem for f in reports.glob("*.md") if f.stem != "latest"), reverse=True)
    stem = day or "latest"
    structured = reports / f"{stem}.json"
    if structured.exists():
        body = report_html(json.loads(structured.read_text()))
    else:
        fallback = reports / f"{stem}.md"
        if not fallback.exists():
            return page("garmin-nas", "<h1>Relatório não encontrado</h1>"), 404
        body = markdown.markdown(fallback.read_text(), extensions=["tables"])
        body = body.replace("<table>", "<div class=wrap><table>").replace("</table>", "</table></div>")

    today_str = date.today().isoformat()
    previous = "".join(
        f'<a class="{"today_str" if d == today_str else ""}" href="/p/{person["slug"]}/{d}">'
        f'{d}{" (today_str)" if d == today_str else ""}</a>' for d in days_list[:14])
    portrait = (f'<img class=avatar src="/photo/{person["slug"]}" alt="">' if person["photo"] else "")
    sair = f'<a href=/logout>{_t("ui.sair", ln)}</a>' if person["has_password"] else ""
    return page(f'{person["first"]}, {APP}',
                f'<nav>{portrait}<b>{escape(person["name"])}</b>'
                f'<a href="/">{_t("ui.trocar", ln)}</a>'
                f'<a href="/new">{_t("ui.adicionar", ln)}</a>{sair}</nav>{body}'
                f'<hr><h3>{_t("ui.previous", ln)}</h3>'
                f'<div class=previous>{previous or f"<span class=legend>{_t(chr(117)+chr(105)+chr(46)+chr(110)+chr(101)+chr(110)+chr(104)+chr(117)+chr(109), ln)}</span>"}</div>',
                MODAL_JS, wide=True)


@app.get("/new")
def new_profile():
    return setup_form()


def setup_form() -> str:
    options = "".join(
        f'''<label class=model><input type=radio name=model value="{m['id']}"
              {'checked' if i == 0 else ''}>
            <span><b>{m['name']}</b> <span class=size>{human(m['mib'])}</span>
            <span class=note>{m['note']}</span></span></label>'''
        for i, m in enumerate(CATALOGUE))

    ja_ha = bool(profiles.listing())
    modelo_ja = TARGET.exists()
    bloco_modelo = "" if modelo_ja else f"""
  <h2>Modelo de linguagem</h2>
  <p class=note-box>Corre no teu computador, não na nuvem. Escreve os comentários
  do relatório, e é partilhado por todos os profiles. Os números e o plano são
  calculados e não dependem dele.</p>
  {options}
  <label class=model><input type=radio name=model value=""><span><b>Nenhum</b>
    <span class=note>Relatório só com números, tabelas e plano.</span></span></label>"""

    return page("Novo perfil, garmin-nas", f"""
{'<nav><a href="/">Voltar</a></nav>' if ja_ha else ''}
<h1>{'Adicionar perfil' if ja_ha else 'garmin-nas'}</h1>
<p class=sub>{'Cada person entra com a sua própria conta Garmin.'
              if ja_ha else 'Dá os acessos da Garmin e arranca.'}</p>

<form method=post action=/start>
  {bloco_modelo}
  {'<p class=note-box>O modelo já está instalado e serve todos os profiles.</p>' if modelo_ja else ''}

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
  <label for=password_field>Senha, ou deixa em branco</label>
  <input type=password id=password_field name=password_field autocomplete=new-password>

  <button type=submit>Começar</button>
</form>""")


@app.post("/start")
def start():
    if job.snapshot()["running"]:
        return redirect("/progress")
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    if not email or not password:
        return redirect("/new")

    # Nome provisório, tirado do email. O verdadeiro só se sabe depois da
    # primeira sincronização, porque é a Garmin que o tem.
    stem_base = profiles.slug(email.split("@")[0]) or "profile"
    name = stem_base
    n = 2
    while (profiles.PROFILES / name).exists():
        name, n = f"{stem_base}-{n}", n + 1
    folder = profiles.create(name)

    job.reset()
    threading.Thread(target=work,
                     args=(folder, request.form.get("model", ""), email, password,
                           request.form.get("password_field", "").strip()),
                     daemon=True).start()
    return redirect("/progress")


@app.get("/progress")
def progress_page():
    ln = request_language()
    return page(f'{_t("ui.a_configurar", ln)}, {APP}', f"""
<h1>{_t("ui.a_configurar", ln)}</h1>
<p class=sub id=phase>{_t("ui.comecar", ln)}…</p>
<div class=bar><i id=bar></i></div>
<p class=sub id=step></p>
<div id=mfa hidden>
  <h2>{_t("ui.codigo", ln)}</h2>
  <p class=note-box>{_t("ui.codigo_sub", ln)}</p>
  <input type=text id=code inputmode=numeric autocomplete=one-time-code>
  <button id=sendcode type=button>{_t("ui.enviar_codigo", ln)}</button>
</div>
<h2>{_t("ui.registo", ln)}</h2>
<pre id=log>{_t("ui.aguardar", ln)}…</pre>
<p id=finished hidden><a id=verlink href=/>{_t("ui.ver_relatorio", ln)}</a></p>
""", """<script>
const $ = s => document.querySelector(s);
async function tick() {
  const s = await (await fetch('/status')).json();
  $('#phase').textContent = s.error ? s.error : s.phase + '…';
  if (s.error) $('#phase').className = 'err';
  const indeterminado = s.running && s.progress === null;
  $('#bar').parentElement.classList.toggle('wait', indeterminado);
  $('#bar').style.width = indeterminado ? '0' : (s.progress ?? (s.done ? 100 : 0)) + '%';
  const partes = [];
  if (s.progress !== null && s.running) partes.push(s.progress + '%');
  if (s.step && s.running) partes.push(s.step);
  if (s.eta) partes.push(s.eta);
  $('#step').textContent = partes.join(' · ');
  $('#log').textContent = s.log.join('\\n') || '…';
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


@app.get("/status")
def state():
    return jsonify(job.snapshot())


@app.post("/mfa")
def mfa():
    code = (request.get_json(silent=True) or {}).get("code", "").strip()
    if code:
        with job.lock:
            job.mfa_code = code
    return jsonify({"ok": bool(code)})


@app.get("/report")
def legacy_report():
    people = profiles.listing()
    return redirect(f'/p/{people[0]["slug"]}' if len(people) == 1 else "/")



if __name__ == "__main__":
    # A migração primeiro: criar a pasta nova antes disso fazia a renomeação
    # da antiga deixar de acontecer, e ficavam as duas lado a lado.
    moved = profiles.migrate()
    profiles.PROFILES.mkdir(parents=True, exist_ok=True)
    if moved:
        print(f"instalação antiga arrumada no perfil '{moved}'", flush=True)
    print(f"garmin-nas: http://{HOST}:{PORT}", flush=True)
    app.run(host=HOST, port=PORT, threaded=True)
