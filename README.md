# garmin-nas

Dockerised [garmin-givemydata](https://github.com/nrvim/garmin-givemydata) for
always-on servers and NAS boxes. Pulls your Garmin Connect history into a local
SQLite database on a daily schedule, with no subscription and no cloud
middleman.

Built and tested on a Synology DS923+, but it runs anywhere Docker does on
x86_64.

*[Leia-me em português](LEIAME.md)*

---

## Why a NAS

The upstream tool logs into Garmin Connect with a real Chrome instance, because
in March 2026 Garmin tightened its Cloudflare bot protection and every
credential-based Python library stopped working. The clearance cookie that
Chrome earns is tied to your egress IP address.

That makes a NAS the ideal host: stable IP, always on, so a session survives for
weeks instead of breaking every time your laptop changes networks.

## What you get

- SQLite database with roughly 50 tables — sleep, HRV, training readiness,
  activities, splits, GPS trackpoints, body composition
- Original FIT files, kept lossless
- Daily incremental sync via `supercronic`
- Optional MCP server so an AI assistant can query the database directly

## Quick start

```bash
git clone https://github.com/OWNER/garmin-nas.git
cd garmin-nas
cp .env.example .env
mkdir -p data
```

Edit `.env` — set `TZ`, and set `PUID`/`PGID` to match the owner of the `data`
directory. On DSM, find them with `id yourusername`.

### First run: authenticate and fetch everything

Credentials are **not** placed in `.env`. The first run is interactive: the tool
prompts for them and stores them itself inside `/data`.

```bash
docker compose run --rm garmin \
  xvfb-run -a garmin-givemydata --full
```

This launches Chrome under a virtual display, solves the Cloudflare challenge,
logs in, and pulls your entire history. Expect around 30 minutes for ten years
of data. The browser profile is saved to `data/browser_profile/`, so subsequent
runs need no interaction.

If your account has multi-factor authentication, the prompt appears in this same
terminal — keep the session attached until login completes.

### Then: leave it running

```bash
docker compose up -d
```

The container now sleeps until 05:30 each day, runs an incremental sync, and
appends to `data/sync.log`.

```bash
docker compose logs -f garmin      # container output
tail -f data/sync.log              # sync detail
docker compose exec garmin garmin-givemydata --status
```

## Layout

```
data/
├── garmin.db          # everything, queryable with plain SQL
├── fit/               # original activity files
├── browser_profile/   # Cloudflare session — keep this
├── .env               # credentials, written by the tool
└── sync.log
```

## Querying your data

Straight SQL works:

```bash
docker compose exec garmin sqlite3 /data/garmin.db \
  "SELECT calendar_date, resting_heart_rate FROM daily_health
   ORDER BY calendar_date DESC LIMIT 30;"
```

Or export:

```bash
docker compose exec garmin garmin-givemydata --export /data/export
docker compose exec garmin garmin-givemydata --export-gpx /data/gpx
```

### Connecting an AI assistant

The upstream MCP server speaks stdio, not HTTP, so it cannot be reached across
the network from the container. Mount the NAS share on your workstation and
point the MCP client at the database file there:

```bash
claude mcp add -s user garmin \
  -e GARMIN_DATA_DIR=/mnt/nas/docker/garmin/data \
  -- garmin-mcp
```

## Troubleshooting

**403 or session errors.** The clearance cookie is IP-bound. If your public IP
changed, delete `data/browser_profile/` and repeat the interactive first run.

**Chrome crashes mid-sync.** Raise `shm_size` in `docker-compose.yml`. Chrome
needs real shared memory; the Docker default of 64 MB is nowhere near enough.

**Container is killed.** Lower the sync scope with `--profile health` or raise
`mem_limit`. Chrome peaks around 1 GB.

**Empty HRV, Body Battery, or training readiness.** These need a compatible
device — Fenix 7 and later, Forerunner 265 and later, Venu 3 and later.

## Credits and licence

All the real work belongs to [nrvim/garmin-givemydata](https://github.com/nrvim/garmin-givemydata),
which in turn credits GarminDB, python-garminconnect, garth, and
garmin-connect-export. This repository is packaging only.

The upstream project is AGPL-3.0, and the published image contains it, so this
repository is AGPL-3.0 as well. The image pins an upstream version; source for
the AGPL components is at the link above.

## Disclaimer

Unofficial, and not affiliated with Garmin. It signs in with your own
credentials to retrieve your own data. Garmin's terms of service may prohibit
this, so the risk is yours. Data portability rights under GDPR Article 20 and
the EU Data Act exist, but they bind Garmin — they do not authorise you to
bypass access controls, and that distinction matters.
