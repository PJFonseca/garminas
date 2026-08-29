#!/usr/bin/env python3
"""Vários perfis na mesma instalação, um por pessoa da casa.

Cada pessoa tem a sua conta Garmin, e o upstream guarda tudo o que é de uma
conta debaixo de um único diretório: base de dados, credenciais, ficheiros FIT
e o perfil do Chrome que segura a sessão da Cloudflare. Portanto um perfil
aqui é exatamente isso, um diretório:

    /data/perfis/pedro/garmin.db
    /data/perfis/pedro/.env
    /data/perfis/pedro/browser_profile/
    /data/perfis/pedro/reports/

O nome e a fotografia não são pedidos a ninguém: vêm da tabela user_profile
da própria base de dados, que a Garmin preenche. A fotografia é descarregada
uma vez e guardada ao lado, para a página não depender da internet depois.

Instalações antigas têm tudo à solta em /data. migrar() arruma-as no primeiro
arranque, sem perder nada.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

DATA = Path(os.environ.get("GARMIN_DATA_DIR_ROOT", "/data"))
PERFIS = DATA / "perfis"

# Tudo o que não seja a própria pasta de perfis pertence à conta antiga. Uma
# lista fechada deixaria para trás ficheiros que o upstream cria sem avisar,
# e alguns são críticos: mover garmin.db sem o garmin.db-wal ao lado perde as
# escritas que ainda não foram integradas.
NAO_MIGRAR = {"perfis"}


def slug(nome: str) -> str:
    sem_acentos = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    limpo = re.sub(r"[^a-zA-Z0-9]+", "-", sem_acentos).strip("-").lower()
    return limpo or "perfil"


def identidade(db: Path) -> dict:
    """Nome e fotografia, lidos da base de dados da própria conta."""
    if not db.exists():
        return {}
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        linhas = dict(con.execute("SELECT key, raw_json FROM user_profile").fetchall())
    except sqlite3.Error:
        return {}

    def campo(chave: str, *nomes: str):
        try:
            d = json.loads(linhas.get(chave) or "{}")
        except json.JSONDecodeError:
            return None
        for n in nomes:
            if isinstance(d, dict) and d.get(n):
                return d[n]
        return None

    nome = campo("social_profile", "fullName")
    if not nome:
        primeiro = campo("user_profile_base", "firstName")
        ultimo = campo("user_profile_base", "lastName")
        nome = " ".join(x for x in (primeiro, ultimo) if x) or None

    # O idioma vem da conta, não de quem instalou. Sem ele, inglês.
    locale = (campo("personal_info", "locale")
              or campo("user_profile_base", "locale") or "")
    from idioma import escolher
    idioma = escolher(str(locale) if locale else None)

    return {
        "nome": nome,
        "primeiro": campo("user_profile_base", "firstName") or (nome or "").split(" ")[0],
        "foto_url": campo("social_profile", "profileImageUrlLarge", "profileImageUrlMedium"),
        "locale": locale or None,
        "idioma": idioma,
    }


def guardar_foto(pasta: Path, url: str | None) -> str | None:
    """Descarrega a fotografia uma vez. Depois disto a página vive offline."""
    if not url:
        return None
    destino = pasta / ("foto" + (Path(url.split("?")[0]).suffix or ".png"))
    if destino.exists():
        return destino.name
    try:
        pedido = urllib.request.Request(url, headers={"User-Agent": "garmin-nas/1.0"})
        with urllib.request.urlopen(pedido, timeout=30) as resposta:
            dados = resposta.read(5 * 1024 * 1024)
    except (urllib.error.URLError, OSError, TimeoutError):
        return None
    destino.write_bytes(dados)
    return destino.name


def ler(pasta: Path) -> dict:
    ficheiro = pasta / "perfil.json"
    try:
        return json.loads(ficheiro.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def escrever(pasta: Path, dados: dict) -> None:
    (pasta / "perfil.json").write_text(json.dumps(dados, ensure_ascii=False, indent=1))


def registar(pasta: Path) -> dict:
    """Preenche nome e fotografia a partir da base de dados, se ainda faltarem."""
    dados = ler(pasta)
    if dados.get("nome") and dados.get("foto") and dados.get("idioma"):
        return dados
    quem = identidade(pasta / "garmin.db")
    if quem.get("idioma"):
        dados.setdefault("idioma", quem["idioma"])
        dados.setdefault("locale", quem.get("locale"))
    if quem.get("nome"):
        dados.setdefault("nome", quem["nome"])
        dados.setdefault("primeiro", quem.get("primeiro") or quem["nome"].split(" ")[0])
    foto = guardar_foto(pasta, quem.get("foto_url"))
    if foto:
        dados["foto"] = foto
    dados.setdefault("slug", pasta.name)
    escrever(pasta, dados)
    return dados


def listar() -> list[dict]:
    """Os perfis existentes, por ordem alfabética do primeiro nome."""
    if not PERFIS.exists():
        return []
    saida = []
    for pasta in sorted(p for p in PERFIS.iterdir() if p.is_dir()):
        dados = registar(pasta)
        saida.append({
            "slug": pasta.name,
            "dir": str(pasta),
            "nome": dados.get("nome") or pasta.name,
            "primeiro": dados.get("primeiro") or (dados.get("nome") or pasta.name).split(" ")[0],
            "foto": dados.get("foto"),
            "tem_db": (pasta / "garmin.db").exists(),
            "tem_senha": bool(dados.get("senha")),
            "idioma": dados.get("idioma", "en"),
        })
    return sorted(saida, key=lambda p: p["primeiro"].lower())


def pasta_de(slug_: str) -> Path | None:
    alvo = PERFIS / slug_
    return alvo if alvo.is_dir() else None


def criar(slug_: str) -> Path:
    pasta = PERFIS / slug_
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def migrar() -> str | None:
    """Arruma uma instalação antiga, com tudo à solta em /data, num perfil.

    Move em vez de copiar: é instantâneo e não duplica gigabytes de ficheiros
    FIT. Se não houver base de dados à solta, não há nada a migrar.
    """
    antiga = DATA / "garmin.db"
    if not antiga.exists():
        return None

    nome = (identidade(antiga).get("primeiro") or "perfil")
    destino = criar(slug(nome))

    for origem in sorted(DATA.iterdir()):
        if origem.name in NAO_MIGRAR:
            continue
        alvo = destino / origem.name
        if not alvo.exists():
            shutil.move(str(origem), str(alvo))
    registar(destino)
    return destino.name
