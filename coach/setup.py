#!/usr/bin/env python3
"""Primeira configuração, do princípio ao fim.

Corre uma vez, dentro do container:

    docker compose run --rm garmin setup

Faz três coisas por esta ordem: escolhe e descarrega o modelo de linguagem,
autentica na Garmin e puxa o histórico, e gera o primeiro relatório. A pessoa
só fornece os acessos; o resto é automático.

O catálogo é deliberadamente curto. Isto corre em CPU, muitas vezes num NAS
de dois núcleos, e a diferença entre um 4B e um 8B não é qualidade a mais -
é passar de dois minutos para um quarto de hora por relatório.

O ficheiro é gravado sempre como model.gguf, para que o docker-compose.yml
funcione sem ninguém ter de editar variáveis.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

MODELS_DIR = Path(os.environ.get("MODELS_DIR", "/models"))
TARGET = MODELS_DIR / "model.gguf"
META = MODELS_DIR / "model.json"

# Todos verificados a 2026-08-29, e todos sem modo de raciocínio. Um modelo
# que "pensa" antes de responder, o Qwen3 8B, por exemplo, enche o contexto
# com o raciocínio e rebenta com "Context size has been exceeded" antes de
# escrever a resposta. Testado, não suposto.
#
# Quantização Q4_K_M: o melhor compromisso entre tamanho e qualidade em CPU.
CATALOGUE = [
    {
        "id": "gemma3-12b",
        "name": "Gemma 3 12B Instruct",
        "mib": 6962,
        "note": "O melhor texto, e o que melhor percebe o que lhe pedes. Precisa de 12 GB "
                "de memória livre: com menos, o relatório demora horas e o modelo acaba "
                "por morrer. Em 2 núcleos leva 1 a 3 horas, o que não é problema para uma "
                "coisa que corre de madrugada, uma vez por dia.",
        "url": "https://huggingface.co/unsloth/gemma-3-12b-it-GGUF/resolve/main/gemma-3-12b-it-Q4_K_M.gguf",
    },
    {
        "id": "qwen3-4b",
        "name": "Qwen3 4B Instruct",
        "mib": 2381,
        "note": "Rápido e correto. Cerca de 3 minutos por relatório em 2 núcleos. "
                "A escolha certa se não quiseres esperar.",
        "url": "https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
    },
    {
        "id": "gemma3-4b",
        "name": "Gemma 3 4B Instruct",
        "mib": 2374,
        "note": "Alternativa ao Qwen. Prosa mais solta, por vezes mais verbosa.",
        "url": "https://huggingface.co/unsloth/gemma-3-4b-it-GGUF/resolve/main/gemma-3-4b-it-Q4_K_M.gguf",
    },
    {
        "id": "llama3.2-3b",
        "name": "Llama 3.2 3B Instruct",
        "mib": 1925,
        "note": "Cerca de 30% mais rápido que os 4B, com alguma perda de fluência.",
        "url": "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
    },
    {
        "id": "qwen3-1.7b",
        "name": "Qwen3 1.7B",
        "mib": 1056,
        "note": "Para máquinas fracas ou com pouca RAM. Texto mais seco, mas cumpre.",
        "url": "https://huggingface.co/unsloth/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q4_K_M.gguf",
    },
]


def human(n: float) -> str:
    return f"{n / 1024:.1f} GiB" if n >= 1024 else f"{n:.0f} MiB"


def choose() -> dict | None:
    """Menu. COACH_MODEL permite correr sem interação."""
    preset = os.environ.get("COACH_MODEL")
    if preset:
        hit = next((m for m in CATALOGUE if m["id"] == preset), None)
        if hit:
            print(f"COACH_MODEL={preset}, a usar {hit['name']}.")
            return hit
        if preset.startswith("http"):
            return {"id": "custom", "name": "URL personalizado", "mib": 0, "url": preset, "note": ""}
        sys.exit(f"COACH_MODEL={preset} não corresponde a nenhuma opção do catálogo.")

    print("\nQue modelo queres usar para redigir os relatórios?\n")
    print("  Quanto maior, melhor escreve, e mais devagar. Numa NAS de dois")
    print("  núcleos fica-te pelos 4B; num PC com 8 ou mais, sobe.\n")
    for i, m in enumerate(CATALOGUE, 1):
        print(f"  {i}. {m['name']:<24} {human(m['mib']):>9}")
        print(f"     {m['note']}")
    print("\n  5. Outro URL de um ficheiro .gguf")
    print("  6. Nenhum, o relatório sai só com números, sem texto redigido\n")

    while True:
        try:
            answer = input("Escolha [1]: ").strip() or "1"
        except (EOFError, KeyboardInterrupt):
            print("\nCancelado.")
            return None
        if answer in {"1", "2", "3", "4"}:
            return CATALOGUE[int(answer) - 1]
        if answer == "5":
            url = input("URL do .gguf: ").strip()
            if url.startswith("http"):
                return {"id": "custom", "name": "URL personalizado", "mib": 0, "url": url, "note": ""}
            print("URL inválido.")
        elif answer == "6":
            return None
        else:
            print("Opção inválida.")


def download(model: dict, on_progress=None) -> bool:
    """Descarrega com retoma. Um 4B são 2,4 GB e as ligações caem.

    on_progress(feitos, total) permite à interface web mostrar a barra; sem
    ela imprime no terminal, como antes.
    """
    part = TARGET.with_suffix(".gguf.part")
    done = part.stat().st_size if part.exists() else 0

    req = urllib.request.Request(model["url"], headers={"User-Agent": "GarmiNAS/1.0"})
    if done:
        print(f"A retomar em {human(done / 1048576)}.")
        req.add_header("Range", f"bytes={done}-")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if done and resp.status != 206:
                done = 0  # servidor ignorou o Range; recomeçar
            total = int(resp.headers.get("Content-Length", 0)) + done
            with open(part, "ab" if done else "wb") as fh:
                last = -1
                while chunk := resp.read(1 << 20):
                    fh.write(chunk)
                    done += len(chunk)
                    pct = int(done * 100 / total) if total else 0
                    if pct != last and pct % 2 == 0:
                        if on_progress:
                            on_progress(done, total)
                        else:
                            print(f"\r  {pct:3d}%  {human(done / 1048576)}", end="", flush=True)
                        last = pct
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"\nDownload falhou: {exc}", file=sys.stderr)
        print("O ficheiro parcial fica guardado; corre o setup outra vez para retomar.")
        return False

    print()
    part.replace(TARGET)
    return True


def ask(question: str, default_yes: bool = True) -> bool:
    hint = "[S/n]" if default_yes else "[s/N]"
    try:
        answer = input(f"{question} {hint}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if not answer:
        return default_yes
    return answer in {"s", "sim", "y", "yes"}


def run(cmd: list[str], why: str) -> bool:
    """Corre um comando com o terminal ligado, para o utilizador responder."""
    if not shutil.which(cmd[0]):
        print(f"{cmd[0]} não existe nesta máquina; {why} tem de ser feito no container.")
        return False
    print(f"\n$ {' '.join(cmd)}\n")
    try:
        return subprocess.call(cmd) == 0
    except KeyboardInterrupt:
        print("\nInterrompido.")
        return False


def garmin_step() -> bool:
    """Login e primeira sincronização. O upstream é que pede as credenciais."""
    db = Path("/data/garmin.db")
    if db.exists():
        print(f"\nJá existe uma base de dados em {db}.")
        if not ask("Voltar a sincronizar tudo do início?", default_yes=False):
            return True

    print("""
Agora a ligação à Garmin Connect.

A seguir vais escrever o teu email e palavra-passe da Garmin. São pedidos pela
ferramenta upstream, que os guarda em /data, nunca passam por aqui nem saem
desta máquina. Se tiveres autenticação em dois passos, o código é pedido neste
mesmo terminal.

Abre um Chrome sem ecrã para passar a proteção da Cloudflare. A primeira
sincronização puxa o histórico todo e pode demorar cerca de 30 minutos.""")

    if not ask("\nAvançar para o login?"):
        print("Podes fazê-lo mais tarde com:  docker compose run --rm garmin auth")
        return False

    if not run(["xvfb-run", "-a", "garmin-givemydata", "--full"], "o login"):
        print("\nA sincronização não terminou bem. Podes repetir com:")
        print("  docker compose run --rm garmin auth")
        return False
    return True


def report_step() -> None:
    """Primeiro relatório, para a pessoa ver logo o resultado."""
    print("\nA gerar o primeiro relatório.")
    if not run([sys.executable, "/opt/coach/coach.py"], "o relatório"):
        print("O relatório falhou. Tenta:  docker compose run --rm garmin report")
        return
    print("\nGuardado em data/reports/latest.md.")
    print("A partir de agora é automático: sincroniza às 05:30 e escreve o")
    print("relatório às 06:30. Falta só deixar isto a correr:\n")
    print("  docker compose --profile llm up -d\n")


def main() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    if TARGET.exists():
        current = "desconhecido"
        if META.exists():
            current = json.loads(META.read_text()).get("name", current)
        size = human(TARGET.stat().st_size / 1048576)
        print(f"Já existe um modelo instalado: {current} ({size}).")
        try:
            if (input("Substituir? [s/N]: ").strip().lower() or "n") not in {"s", "sim", "y"}:
                print("Mantido.")
                return
        except (EOFError, KeyboardInterrupt):
            return

    model = choose()
    if model:
        print(f"\nA descarregar {model['name']} para {TARGET}.")
        if not download(model):
            sys.exit(1)
        META.write_text(json.dumps({
            "id": model["id"], "name": model["name"],
            "url": model["url"], "installed": date.today().isoformat(),
        }, indent=2, ensure_ascii=False))
        print(f"\nPronto: {model['name']}, {human(TARGET.stat().st_size / 1048576)}.")
    else:
        print("\nSem modelo: os relatórios saem com os números e o plano,")
        print("mas sem as secções escritas. Podes instalar um depois.")

    if garmin_step():
        report_step()


if __name__ == "__main__":
    main()
