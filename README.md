# GarmiNAS

Your Garmin data, on your own machine, with a coach that reads it every morning.

GarmiNAS pulls your Garmin Connect history into a local SQLite database, works
out where your training actually stands, builds the next fortnight from rules,
and has a language model running on your own CPU write the parts that are worth
reading. No subscription, no cloud, nothing leaves the machine.

Built for an always-on box: a NAS, a mini PC, a home server. Tested on a
Synology DS923+.

---

## The idea

Every training app either shows you numbers and leaves you to interpret them, or
hands the interpretation to a model that will cheerfully invent a number to
finish a sentence. GarmiNAS does neither.

**Arithmetic is arithmetic.** Load, freshness, ramp rate, sleep, HRV, the plan
for the next fourteen days: all computed, all from your own history. The plan
comes out of eligibility rules and a forward simulation of CTL, ATL and TSB, not
out of a prompt.

**The model narrates, it does not decide.** It receives verdicts that have
already been reached and writes them in a way you would want to read. It never
picks a session, never overrides a recovery flag, never does a sum.

This is not caution for its own sake. A 4B model given the sentence "0.65, below
0.8: last week fell short, you are losing fitness" and asked to repeat it wrote
"within the safe range". Given raw recovery numbers it read a rising HRV and a
falling resting heart rate, both good signs, as "an imbalance between effort and
recovery". So it no longer sees the numbers it used to misread.

**And what it writes is checked.** Every number in the generated text is matched
against the numbers it was given; anything invented gets one retry and is then
dropped, because in a health report a confidently wrong sentence is worse than
no sentence. The language is checked too.

## What you get

A page, on your network, that opens with what to do next.

- **How the last session went**, compared with the ones before: pace per
  kilometre as bars, time in each heart rate zone, and two sentences that say
  whether it was good or bad and why.
- **Am I improving?** Answered with pace at the same heart rate, five recent
  sessions against the twenty before, because running faster at 170 bpm is not
  improvement, it is trying harder.
- **Eight or nine readings with verdicts**, each with a scale showing where the
  value falls between bad and good, the target in words, and one concrete thing
  to do. Sorted worst first; what is fine collapses to a single line.
- **The next session, in full.** Not "easy run, 35 min" but the warm-up, the
  intervals, and the speed to put on the treadmill, worked out from the speeds
  you actually hold at the heart rates you actually hold them at.
- **A fortnight of plan**, each day clickable, with a drawn figure for every
  strength exercise and a timeline for every run.
- Roughly 50 tables of raw data underneath, queryable with plain SQL, and the
  original FIT files kept lossless.

## One profile per person

A household has more than one Garmin account. Each profile gets its own
database, its own browser session, its own reports, under
`data/profiles/<name>/`. Nobody types a name or uploads a photograph: both come
from the Garmin account itself on the first sync.

Each person can also brief the coach in their own words. Two boxes, because they
are two different things: how you want to be spoken to, which joins the style
rules, and what the coach should know about you, which joins the data. "Right
knee is sensitive" turns into a report that watches the knee. Neither can make
the coach invent a number or rewrite the plan.

## Languages

The report comes out in the language of the Garmin account, and in English when
the account does not say. English, Portuguese, Spanish, French, German, Italian
and Chinese are complete; anything missing from a translation falls back to
English rather than breaking the page. A profile can override the choice.

## Quick start

You need Docker with the Compose plugin, and about 6 GB of free disk.

```bash
docker build -t garmin-nas:1.0 .
cp .env.example .env
docker compose --profile llm up -d
```

Then open <http://localhost:8090>, or `http://your-nas:8090` from another
machine, and add a profile. The page asks which language model you want and
downloads it, asks for your Garmin credentials, prompts for the two-factor code
if Garmin asks for one, pulls your history, and writes the first report. Around
30 minutes for ten years of data, with a live log throughout.

After that it runs itself: an incremental sync at 05:30, a fresh report at
06:30. The **Update now** button does both on demand, for when you have just
finished a session and would rather not wait until morning.

### Choosing a model

Short on purpose, because this runs on CPU:

| | Size | Notes |
|---|---|---|
| Qwen3 4B Instruct | 2.3 GiB | Recommended. Two to three minutes per report on two cores. |
| Gemma 3 4B Instruct | 2.3 GiB | Looser prose, sometimes more verbose. |
| Llama 3.2 3B Instruct | 1.9 GiB | About 30% faster, slightly less fluent. |
| Qwen3 1.7B | 1.0 GiB | For weak CPUs or little RAM. |
| Gemma 3 12B Instruct | 6.8 GiB | Best writing here. Needs 8 cores and 8 GB free; hopeless on a two-core NAS. |

Every URL is checked, and every model is a non-reasoning one: a model that
thinks before answering fills the context with its own reasoning and dies with
"Context size has been exceeded" before writing a word.

You can also pick none. The report still comes out with the figures, the tables
and the plan, just without the written sections.

## Why an always-on host

The upstream tool logs into Garmin Connect with a real Chrome instance, because
in March 2026 Garmin tightened its Cloudflare bot protection and every
credential-based Python library stopped working. The clearance cookie Chrome
earns is tied to your egress IP.

That makes a NAS the natural host: stable IP, always on, so a session survives
for weeks instead of breaking every time a laptop changes network. A laptop
works too, with more re-authentication.

## Moving it to a NAS

No registry involved. Build where the CPU is good, ship the image as a file:

```bash
docker save garmin-nas:1.0 | gzip > garmin-nas-1.0.tar.gz
scp garmin-nas-1.0.tar.gz docker-compose.yml .env.example user@nas:/volume1/docker/garmin/
```

Then, on the NAS over SSH:

```bash
cd /volume1/docker/garmin
docker load < garmin-nas-1.0.tar.gz
cp .env.example .env
docker compose --profile llm up -d
```

Both machines must be x86_64. Set the profiles up **on the NAS**, through its
own page: the Cloudflare cookie is bound to the egress IP, so a session created
elsewhere will not survive.

Set `PUID` and `PGID` in `.env` to your own user, or everything the container
writes ends up owned by root.

## A word on exposure

The page listens on every interface by default, so anyone on your network can
reach it, including the form you type your Garmin password into, over plain
HTTP. On a home network behind a router that is usually what people want. To
restrict it to the machine itself, set `WEB_BIND=127.0.0.1` in `.env` and reach
it through an SSH tunnel:

```bash
ssh -L 8090:localhost:8090 you@your-nas
```

A profile password only keeps the household's reports from being open to
everyone on the network. It is not security.

## Layout

```
data/
└── profiles/
    └── pedro/
        ├── garmin.db          # everything, queryable with plain SQL
        ├── fit/               # original activity files
        ├── browser_profile/   # Cloudflare session, keep this
        ├── reports/           # daily reports, markdown and JSON
        ├── profile.json       # name, photo, language, preferences
        └── .env               # credentials, owner-readable only
models/
└── model.gguf                 # chosen on the setup page
```

## Commands

The image takes a verb:

```bash
docker compose run --rm garmin setup      # full first-time configuration, in a terminal
docker compose run --rm garmin report     # regenerate the reports now, every profile
docker compose run --rm garmin status     # upstream sync status
docker compose run --rm garmin metrics --discover   # print the real database schema
```

## Querying your own data

```bash
docker compose exec garmin sqlite3 /data/profiles/pedro/garmin.db \
  "SELECT calendar_date, resting_heart_rate FROM daily_summary
   ORDER BY calendar_date DESC LIMIT 30;"
```

The upstream MCP server speaks stdio, so point an AI assistant at the database
file over a mounted share rather than across the network:

```bash
claude mcp add -s user garmin \
  -e GARMIN_DATA_DIR=/mnt/nas/docker/garmin/data/profiles/pedro \
  -- garmin-mcp
```

## Troubleshooting

**403 or session errors.** The clearance cookie is IP-bound. If your public IP
changed, delete `data/profiles/<name>/browser_profile/` and set the profile up
again.

**Chrome crashes mid-sync.** Raise `shm_size` in `docker-compose.yml`. Chrome
needs real shared memory and the Docker default of 64 MB is nowhere near enough.

**The container is killed.** Lower `LLM_MEM`, or the sync scope with
`--profile health`. Chrome peaks around 1 GB and a 4B model wants about 4.

**Empty HRV, Body Battery or training readiness.** These need a compatible
device: Fenix 7 and later, Forerunner 265 and later, Venu 3 and later.

**The plan is nearly all rest.** That is the volume brake. It caps the next
fortnight against the higher of your last week and your four-week average, so a
single light week cannot become the new normal, and recovery flags cut the
catalogue to easy sessions regardless.

## Credits and licence

All the real work belongs to
[nrvim/garmin-givemydata](https://github.com/nrvim/garmin-givemydata), which in
turn credits GarminDB, python-garminconnect, garth and garmin-connect-export.
This repository is the packaging, the coach, and the interface around it.

The upstream project is AGPL-3.0 and the image contains it, so this repository
is AGPL-3.0 as well.

## Disclaimer

Unofficial, and not affiliated with Garmin. It signs in with your own
credentials to retrieve your own data. Garmin's terms of service may prohibit
this, so the risk is yours. Data portability rights under GDPR Article 20 and
the EU Data Act exist, but they bind Garmin: they do not authorise you to bypass
access controls, and that distinction matters.

The reports are general guidance generated from your own data. They do not
replace medical or coaching supervision, especially if there is pain, dizziness
or persistent symptoms.
