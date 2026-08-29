#!/usr/bin/env python3
"""Several profiles in one installation, one per person in the house.

Each person has their own Garmin account, and the upstream tool keeps
everything belonging to an account under a single directory: database,
credentials, FIT files, and the Chrome profile that holds the Cloudflare
session. So a profile here is exactly that, a directory:

    /data/profiles/pedro/garmin.db
    /data/profiles/pedro/.env
    /data/profiles/pedro/browser_profile/
    /data/profiles/pedro/reports/

Nobody is asked for a name or a photograph: both come from the user_profile
table of the account's own database, which Garmin fills in. The photograph is
downloaded once and kept alongside, so the page works offline afterwards.

Older single-account installations have everything loose in /data. migrate()
tidies them into a profile on first start, without losing anything.
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
PROFILES = DATA / "profiles"

# The directory used to be called "perfis". Renamed for consistency with the
# rest of the code; existing installations are moved on first start.
LEGACY_PROFILES = DATA / "perfis"

# Everything that is not the profiles directory belongs to the old account. A
# fixed list would leave behind files the upstream creates without warning, and
# some are critical: moving garmin.db without garmin.db-wal next to it loses
# whatever has not been checkpointed yet.
KEEP_OUT = {"profiles", "perfis"}


def slug(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    clean = re.sub(r"[^a-zA-Z0-9]+", "-", plain).strip("-").lower()
    return clean or "profile"


def identity(db: Path) -> dict:
    """Name, photograph and language, read from the account's own database."""
    if not db.exists():
        return {}
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = dict(con.execute("SELECT key, raw_json FROM user_profile").fetchall())
    except sqlite3.Error:
        return {}

    def field(key: str, *names: str):
        try:
            d = json.loads(rows.get(key) or "{}")
        except json.JSONDecodeError:
            return None
        for n in names:
            if isinstance(d, dict) and d.get(n):
                return d[n]
        return None

    name = field("social_profile", "fullName")
    if not name:
        first = field("user_profile_base", "firstName")
        last = field("user_profile_base", "lastName")
        name = " ".join(x for x in (first, last) if x) or None

    # The language comes from the account, not from whoever installed this.
    # Without one, English.
    from language import pick
    locale = field("personal_info", "locale") or field("user_profile_base", "locale") or ""

    return {
        "name": name,
        "first": field("user_profile_base", "firstName") or (name or "").split(" ")[0],
        "photo_url": field("social_profile", "profileImageUrlLarge", "profileImageUrlMedium"),
        "locale": locale or None,
        "language": pick(str(locale) if locale else None),
    }


def save_photo(folder: Path, url: str | None) -> str | None:
    """Downloads the photograph once. After that the page lives offline."""
    if not url:
        return None
    target = folder / ("photo" + (Path(url.split("?")[0]).suffix or ".png"))
    if target.exists():
        return target.name
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "GarmiNAS/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(5 * 1024 * 1024)
    except (urllib.error.URLError, OSError, TimeoutError):
        return None
    target.write_bytes(data)
    return target.name


def read(folder: Path) -> dict:
    try:
        return json.loads((folder / "profile.json").read_text())
    except (OSError, json.JSONDecodeError):
        pass
    try:                                  # older installations
        return json.loads((folder / "perfil.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def write(folder: Path, data: dict) -> None:
    (folder / "profile.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
    old = folder / "perfil.json"
    if old.exists():
        old.unlink()


def register(folder: Path) -> dict:
    """Fills in name, photograph and language from the database if missing."""
    data = read(folder)
    if data.get("name") and data.get("photo") and data.get("language"):
        return data

    who = identity(folder / "garmin.db")
    if who.get("language"):
        data.setdefault("language", who["language"])
        data.setdefault("locale", who.get("locale"))
    if who.get("name"):
        data.setdefault("name", who["name"])
        data.setdefault("first", who.get("first") or who["name"].split(" ")[0])
    photo = save_photo(folder, who.get("photo_url"))
    if photo:
        data["photo"] = photo
    data.setdefault("slug", folder.name)
    write(folder, data)
    return data


def listing() -> list[dict]:
    """The existing profiles, in alphabetical order of first name."""
    if not PROFILES.exists():
        return []
    out = []
    for folder in sorted(p for p in PROFILES.iterdir() if p.is_dir()):
        data = register(folder)
        name = data.get("name") or folder.name
        out.append({
            "slug": folder.name,
            "dir": str(folder),
            "name": name,
            "first": data.get("first") or name.split(" ")[0],
            "photo": data.get("photo"),
            "has_db": (folder / "garmin.db").exists(),
            "has_password": bool(data.get("password") or data.get("senha")),
            "language": data.get("language", "en"),
        })
    return sorted(out, key=lambda p: p["first"].lower())


def folder_of(name: str) -> Path | None:
    target = PROFILES / name
    return target if target.is_dir() else None


def create(name: str) -> Path:
    folder = PROFILES / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def migrate() -> str | None:
    """Tidies an old installation, everything loose in /data, into a profile.

    Moves rather than copies: instant, and it does not duplicate gigabytes of
    FIT files. Also renames the old Portuguese-named profiles directory.
    """
    if LEGACY_PROFILES.is_dir() and not PROFILES.exists():
        LEGACY_PROFILES.rename(PROFILES)

    old_db = DATA / "garmin.db"
    if not old_db.exists():
        return None

    # A profile.json here means this directory IS a profile, not an old
    # installation waiting to be tidied. Without this guard, pointing
    # GARMIN_DATA_DIR at a profile buried it inside itself, at
    # profiles/<name>/profiles/<name>. That happened.
    if (DATA / "profile.json").exists() or (DATA / "perfil.json").exists() \
            or DATA.parent.name in KEEP_OUT:
        return None

    name = identity(old_db).get("first") or "profile"
    target = create(slug(name))

    for source in sorted(DATA.iterdir()):
        if source.name in KEEP_OUT:
            continue
        destination = target / source.name
        if not destination.exists():
            shutil.move(str(source), str(destination))
    register(target)
    return target.name
