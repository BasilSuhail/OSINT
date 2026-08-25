# Supplementary material

The whole system drawn once, then one chapter per stage.

Each box is a stage and one line saying what it does. A stage whose chapter is
written is a link — click it and the chapter opens below; the arrow at the foot
of the chapter brings you back. Stages still in plain text have no chapter yet.

The long version of this diagram — every box with its reasoning, thresholds and
measured counts — is kept at
[`docs/supplementary/system-diagram-detailed.md`](docs/supplementary/system-diagram-detailed.md).

Counts are read from the code on this branch, not from the design documents.
Where the two disagree, the code is right.

---

<pre>

════════════════════════════ PART I — INGEST ════════════════════════════

   ┌────────────────────────────────────────────────────────────────────────┐
   │ <a id="map-1" href="#ch-1">§1  THE CLOCK</a>                                                          │
   │    decides when every job runs — 84 timetable rows, all UTC            │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ <a id="map-2" href="#ch-2">§2  THE BROKER</a>                                                         │
   │    a Redis mailbox holding jobs until a worker takes one               │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ <a id="map-3" href="#ch-3">§3  THE SOURCES  —  FIND</a>                                               │
   │    67 places data comes from — 14 public APIs, 53 news sites           │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ <a id="map-4" href="#ch-4">§4  THE REST GATE  —  SKIP BROKEN</a>                                      │
   │    a source that keeps failing is left alone for a while               │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ <a id="map-5" href="#ch-5">§5  FETCH  —  DOWNLOAD</a>                                                 │
   │    download only — no database, no scoring, no side effects            │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ <a id="map-6" href="#ch-6">§6  INLINE ENRICHMENT  —  UNDERSTAND</a>                                   │
   │    headlines get translated, placed on a map, read for tone            │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ <a id="map-7" href="#ch-7">§7  PUBLICATION-TIME REPAIR  —  FIX TIME</a>                               │
   │    nothing may claim it happened in the future                         │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ <a id="map-8" href="#ch-8">§8  FRESHNESS GATE  —  DROP STALE</a>                                      │
   │    rows too old for the live window are counted and dropped            │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ <a id="map-9" href="#ch-9">§9  UPSERT AND DEDUP  —  SAVE</a>                                          │
   │    one row per source event — re-fetching updates, never doubles       │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ <a id="map-10" href="#ch-10">§10  DID WE SEE ANYTHING?</a>                                              │
   │    a run that brings back nothing usable is recorded as such           │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ <a id="map-11" href="#ch-11">§11  events  —  THE DATASET</a>                                            │
   │    the one table every source writes into, whatever it measured        │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ <a id="map-12" href="#ch-12">§12  POST-INGEST ENRICHMENT  —  MAKE THE FEATURES</a>                      │
   │    hazard outlines, place names and severity added afterwards          │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ <a id="map-13" href="#ch-13">§13  RETENTION AND CAP</a>                                                 │
   │    rows older than ~30 days are deleted; 30 GB hard ceiling            │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼

═══════════════════════════ PART II — ANALYSIS ═══════════════════════════

   ┌────────────────────────────────────────────────────────────────────────┐
   │ <a id="map-14" href="#ch-14">§14  THE COMPOSITE INDEX</a>                                               │
   │    four domains, z-scored against a country's own past, into one score │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ <a id="map-15" href="#ch-15">§15  CII</a>                                                               │
   │    a same-day stress score: fixed country baseline plus today's events │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §16  STORIES                                                           │
   │    headlines about the same event grouped by word overlap              │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §17  CORROBORATION + SENSOR CHECKS                                     │
   │    how many independent owners tell it, and whether a sensor agrees    │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §18  DISAGREEMENT                                                      │
   │    how differently countries word the same story                       │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §19  VALIDATOR                                                         │
   │    a local model extracts the factual claims a story makes             │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §20  SEVERITY GRADING                                                  │
   │    how much harm to people a headline reports                          │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §21  THE BRAIN                                                         │
   │    a local model summarises stored rows and answers questions on them  │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §22  THE PREDICTION JOURNAL                                            │
   │    forecasts written down before the outcome, never rewritten          │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼

═════════════════════ PART III — OFFLINE EVALUATION ═════════════════════

   ┌────────────────────────────────────────────────────────────────────────┐
   │ §23  GROUND TRUTH                                                      │
   │    conflict records become the labels, in a table of their own         │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §24  THE PANEL                                                         │
   │    one row per country per month — 31,637 of them                      │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §25  THE EXAMS                                                         │
   │    the score against six baselines; the verdict is computed, not read  │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §26  HUMAN AUDIT SHEETS                                                │
   │    a person hand-checks a sample of every model output                 │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼

═══════════════════════════ PART IV — SERVING ═══════════════════════════

   ┌────────────────────────────────────────────────────────────────────────┐
   │ §27  THE API                                                           │
   │    31 endpoints — the only way anything leaves the database            │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §28  THE CONSOLE                                                       │
   │    map, panels and a live stream of arriving rows                      │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼

════════════════════════ PART V — WHAT COMES OUT ════════════════════════

   ┌────────────────────────────────────────────────────────────────────────┐
   │ §29  THE ARTEFACTS                                                     │
   │    the files under results/ that every published number comes from     │
   └───────────────────────────────────┬────────────────────────────────────┘
                                        
</pre>

# Chapters

One per stage of the diagram. Click a heading to open it, or click the stage
in the drawing above.

<details id="ch-1">
<summary><b>§1 &nbsp; The clock</b> &nbsp;—&nbsp; a program that watches the time and names the job that is due</summary>
<br>

**`app/tasks.py` → `beat_schedule`**

## What it is

**A custom program.** Not a file, not a cron job. It runs non-stop in its own
container, watches the clock, and when a job is due it publishes that job's
*name* to Redis for a worker to run. It does no work itself — no database, no
downloads, no scoring.

The library is **Celery**. Its three parts are all in the diagram: **beat** is
this scheduler, **broker** is Redis (§2), **worker** does the jobs (§3 onward).
`beat` means scheduler.

## The list it reads

`beat_schedule`, in `app/tasks.py`. That list is the whole schedule — nowhere
else sets a job's timing. One entry looks like this:

```python
"yfinance-5min": {                        # a name, for logs
    "task": "app.tasks.run_fetcher",      # which function
    "args": ["yfinance"],                 # what to give it
    "schedule": crontab(minute="*/5"),    # when
},
```

> **Every 5 minutes, run `run_fetcher`, and hand it the word `yfinance`.**

One entry is a **row**. A row is the only way anything gets scheduled — no row,
never runs. The 84 rows are not all written out one by one:

```
   84 rows
   ├── 31  written in the code
   │   ├── 14  data sources ─── the APIs and news feeds listed in §3
   │   └── 17  jobs that run on what those sources brought in:
   │           ├─ 3  scoring ......  the composite index · the CII ·
   │           │                     writing the day's forecasts down
   │           ├─ 5  story work ...  group headlines into stories ·
   │           │                     check a claim against a sensor ·
   │           │                     measure how differently countries
   │           │                     tell it · pull out the factual
   │           │                     claims · grade how harmful it is
   │           ├─ 2  local model ..  write the situation summary ·
   │           │                     summarise each new story
   │           ├─ 3  filling gaps .  hazard outlines · place names ·
   │           │                     article titles
   │           ├─ 3  self-checks ..  watchdog for silent sources ·
   │           │                     delete rows past 30 days ·
   │           │                     nightly audit of the data itself
   │           └─ 1  output ......   the weekly briefing
   └── 53  built from the news-site list
```

The 53 news rows are identical apart from the site name, so the code builds
them from a list of sites in `app/sources/rss_feeds.json` each time it starts.
The other 31 are all different from each other, so they are written out.

67 of those rows are sources. A **source** is one place data comes from: 14
**core** public APIs (share prices, quake magnitudes, satellite fire positions)
and 53 **RSS** news sites, RSS being the machine-readable list of latest
articles a site publishes. All 67 call the *same* function with a different
word, so adding a source needs no new code — add it to the JSON file and there
is one more row on the next restart.

## How often each row runs

```
   1 + 2 + 1 + 6 + 7 + 1 + 58 + 8  =  84
```

| Speed | Rows | What runs at that speed |
| --- | ---: | --- |
| every 5 min | 1 | Yahoo Finance share prices |
| every 15 min | 2 | the local language model writing a situation summary; the watchdog that notices a source has gone quiet |
| every 20 min | 1 | the local language model summarising new stories |
| every 15 min | 6 | USGS earthquakes · GDACS, the UN/EU **Global Disaster Alert and Coordination System** · GDELT, the **Global Database of Events, Language and Tone** · two abuse.ch cyber-threat feeds · hazard outlines for the map |
| every 30 min | 7 | grouping headlines into stories · checking a claim against a physical sensor reading · measuring how differently countries word a story · grading how harmful a headline is · resolving place names · NASA EONET, the **Earth Observatory Natural Event Tracker** · Polymarket odds |
| every 5 min | 1 | article titles for GDELT rows |
| hourly | 58 | the 53 RSS news sites · ACLED, the **Armed Conflict Location & Event Data Project** · NASA FIRMS, the **Fire Information for Resource Management System** · OpenSky aircraft positions · the **composite index** and the **CII (Country Instability Index)**, both computed here rather than downloaded |
| daily / weekly | 8 | FRED, **Federal Reserve Economic Data** · EM-DAT, the international disaster database · UK police crime records · the prediction journal · claim extraction · deleting expired rows · the nightly data check · the Monday briefing |

<details>
<summary><b>Why each speed is what it is</b></summary>
<br>

Cadence is set by how fast the **source** changes, not by how often the data
would be nice to have. Sampling faster than the source publishes adds no
information and costs a request. The code states this where it applies:

```python
# OpenSky ADS-B is aggregated to one row per country per hour (#496), and
# the hour-keyed upsert means extra polls within an hour only refresh the
# same rows. Polling every 2 min bought nothing but CPU, so: hourly.
```

</details>

<details>
<summary><b>Why the job's name travels as text, not as code</b></summary>
<br>

**The scheduler and the worker are two separate programs**, running at the same
time in different containers. Celery calls the scheduler `beat`, which is why
the container is named that:

```yaml
# docker-compose.yml
beat:    image: osint-backend:local    # the scheduler
worker:  image: osint-backend:local    # does the actual jobs
```

Two separate programs cannot hand each other Python objects. A function lives
inside one program's memory and the other cannot reach in. The only thing they
both touch is Redis, and Redis holds text.

```text
   SCHEDULER                 REDIS                    WORKER
                            (mailbox)

   09:05 — this is due
   writes a note  ──────▶  "run_fetcher"
                           "yfinance"     ──────▶  reads the note
                                                   looks up "run_fetcher"
                                                     in its own code
                                                   runs it on "yfinance"
```

The worker already has the code. Both containers are built from the same image,
so both already contain `run_fetcher`. The worker does not need to be sent the
function — only told which one, and a name is text.

Like texting someone "call the plumber": it works because they already have a
phone and know what a plumber is. You send the instruction, not the plumber.

#### Why the list lives in a file

The timetable is a `.py` file tracked in git, so changing how often a source is
sampled is a commit — a diff, an author, a date, a reason — rather than a
number typed into a server that nobody can account for six months later.

</details>

<details>
<summary><b>How the timing is written — cron, UTC, and staggering</b></summary>
<br>

`cron` describes *when* by pattern-matching the current time, rather than by
counting sleep intervals.

| Written as | Fires |
| --- | --- |
| `crontab(minute="*/5")` | every minute divisible by 5 — 288×/day |
| `crontab(minute="0,15,30,45")` | those four minutes each hour — 96×/day |
| `crontab(hour="*/1", minute=10)` | ten past every hour — 24×/day |
| `crontab(hour=7, minute=0)` | 07:00 — 1×/day |
| `crontab(day_of_week=1, hour=6, minute=30)` | Monday 06:30 — 1×/week |

The reason to prefer this over `sleep(300)` is drift. A sleep loop that spends
three seconds working per cycle slides progressively off the hour, so the
interval between observations is not the interval you declared. Cron pins the
observation to the wall clock, so **the time index stays evenly spaced** and a
per-hour or per-day aggregate is comparable to the one before it.

```python
# app/celery_app.py
app.conf.update(
    timezone="UTC",
    enable_utc=True,
)
```

**One clock for everything, so every timestamp means the same thing.**

Why not the alternatives:

| Instead | Why not |
| --- | --- |
| Local time | Daylight saving gives one night two 02:30s and another none, so a nightly job runs twice and then not at all |
| Each source's own timezone | Two sources cannot be compared without converting at every query |
| Unix epoch numbers | No daylight-saving problem either, but nobody can read a column of them |

Two entries, three minutes apart on purpose:

```python
"gdelt-15min":        crontab(minute="0,15,30,45"),
"gdelt-titles-5min":  crontab(minute="3,8,13,18,23,28,33,38,43,48,53,58"),
```

```python
#: Offset from the fetcher's :00/:15/:30/:45 so a batch of outbound
#: article requests never lands in the same minute as the export
#: download (#788).
```

The same idea, at scale, for the news feeds. The 53 RSS rows are not typed out
— they are generated:

```python
**{
    f"{slug}-hourly": {
        "task": "app.tasks.run_fetcher",
        "args": [slug],
        "schedule": crontab(hour="*/1", minute=(10 + idx * 2) % 60),
    }
    for idx, slug in enumerate(feed_cadence_map().keys())
},
```

`(10 + idx * 2) % 60` spreads the feeds two minutes apart around the hour —
feed 0 at :10, feed 1 at :12, feed 2 at :14. Without it, 53 outbound requests
leave in the same second every hour, which is a load spike aimed at other
people's servers.

</details>

<details>
<summary><b>What it costs, and what puts gaps in the data</b></summary>
<br>

**Cost.** 3,151 messages a day, from a process using 72 MB. The scheduler is
the cheapest part of the system, which is the point — one that did real work
could not be restarted casually.

**Restarts.** It records what already ran in a small file on disk, so a restart
picks up where it left off instead of re-firing everything.

**Three failures, and what each does to the data:**

| Failure | Effect on the data |
| --- | --- |
| The scheduler dies | nothing is sampled at all, and **no error appears anywhere** — no job started, so nothing failed. Silence looks exactly like health. |
| Workers die, scheduler lives | messages queue up and run late, so rows arrive bunched instead of evenly spaced |
| A job fails every run | the scheduler neither knows nor cares; the watchdog in §10 is what catches it |

Nothing sets an expiry on a queued message, so a two-day outage leaves roughly
6,300 of them to drain at once on return.

</details>

<details>
<summary><b>One problem found in this stage</b></summary>
<br>

The cadences are written down twice — once in `beat_schedule`, and again by
hand in `app/watchdog.py`. The watchdog uses its own copy to decide what "late"
means, so changing one file and not the other makes it quietly wrong about
lateness — in the one component whose whole purpose is noticing silence.

Recorded as a finding. Not changed.

</details>

---

<a href="#ch-1">▲ top of §1</a> <sub>(click the heading there to fold it)</sub> &nbsp;·&nbsp; <a href="#map-1">↑ back to §1 in the diagram</a>

</details>

<details id="ch-2">
<summary><b>§2 &nbsp; The broker</b> &nbsp;—&nbsp; the mailbox jobs wait in, and why one queue is deliberately slow</summary>
<br>

**Redis · two queues · `app/celery_app.py`**

## What it is

A **mailbox**. §1 left off with two separate programs that cannot hand each
other anything, so the scheduler drops a note here and a worker collects it
when free.

Redis is the program holding the mailbox. It keeps the notes in memory and
also writes them to disk (`--appendonly yes`), so a restart does not lose the
queue. It also carries the signal that tells the console a new row has landed,
which is what makes the map in §28 update without a reload.

Nothing decides anything here. It stores notes and hands them out in order.

## Two trays, not one

The two names in the code — `celery` and `analytics` — are labels somebody
typed, like marking two trays IN and URGENT. `celery` is simply the name the
library gives a queue when nobody picks one, which unhelpfully matches the
library's own name. Read them as **the fast tray** and **the heavy tray**.

```
   TRAY 1 — the fast one                TRAY 2 — the heavy one
   (code name: celery)                  (code name: analytics)
   ─────────────────────────────        ─────────────────────────────
   4 workers pulling from it            1 worker pulling from it
   2,595 notes/day          82%           556 notes/day          18%
   the 67 downloads, plus two           scoring, grouping headlines,
   light jobs                           running the local model
   small — mostly sitting idle          big — holds a lot of memory
   waiting for a website to reply       for as long as it runs
```

82% + 18% = 100% of the 3,151 notes a day from §1. Not a running total.

**What is in the fast tray.** Almost all of it is downloading — 67 sources,
one row each, plus two jobs light enough not to need the slow lane. What each
source actually is belongs to §3; here it is only how much traffic it makes.

| Fast-tray job | Per day | Kind of data |
| --- | ---: | --- |
| the 53 news sites, one row each | 1,272 | headlines |
| `yfinance` | 288 | market prices |
| `gdelt` | 96 | machine-coded world events |
| `usgs-quake` | 96 | earthquakes |
| `gdacs` | 96 | disaster alerts |
| `abuse-ch-urlhaus` | 96 | cyber indicators |
| `abuse-ch-feodo` | 96 | cyber indicators |
| `eonet` | 48 | natural events |
| `polymarket` | 48 | prediction-market odds |
| `acled` | 24 | conflict records |
| `nasa-firms` | 24 | satellite fire detections |
| `opensky-adsb` | 24 | aircraft positions |
| `fred` | 1 | economic series |
| `emdat` | 1 | disaster archive |
| `uk-police` | 1 | crime records |
| `enrich_gdelt_titles` | 288 | *light job* — fetch article titles |
| `ingest_watchdog` | 96 | *light job* — has a source gone quiet |
| **67 sources + 2 jobs** | **2,595** | |

Just under half of that traffic — 1,272 of 2,595 — is the news sites. None of it holds much memory: a
download is mostly a program waiting for a website to reply, which is why four
can run at once without competing for anything.

**What is in the heavy tray**, every job and how often:

| Heavy job | Per day | What it does |
| --- | ---: | --- |
| `enrich_footprints` | 96 | fetch the real outline of a hazard for the map |
| `brain_narrate` | 96 | local model writes the situation summary |
| `brain_enrich` | 72 | local model summarises each new story |
| `enrich_news_places` | 48 | work out which place a headline is about |
| `cluster_stories` | 48 | group headlines covering the same event |
| `sensor_check_stories` | 48 | check a story's claim against a sensor reading |
| `score_disagreement` | 48 | measure how differently countries word a story |
| `grade_news_severity` | 48 | grade how much harm a headline reports |
| `compute_composite` | 24 | **the composite index** — the score under test |
| `compute_cii` | 24 | **the CII** — the same-day stress score |
| `journal_daily` | 1 | write the day's forecasts down, before the outcome |
| `extract_claims` | 1 | pull the factual claims out of stories |
| `run_housekeeping` | 1 | delete rows past 30 days |
| `data_audit` | 1 | nightly check of the data against itself |
| `weekly_briefing` | 0 | Mondays only |
| **15 jobs** | **556** | |

§1 counted **17** jobs that are not downloads. Two of them are light enough to
stay in the fast tray: `enrich_gdelt_titles` (288/day, fetching article titles)
and `ingest_watchdog` (96/day, checking whether a source has gone quiet).
`17 − 2 = 15`.

## The speed limit

One worker means jobs run one after another, never side by side. So the whole
stage rests on a single question: **can the worker clear a job before the next
one arrives?**

§2's heavy tray takes 556 jobs a day, and a day is 1,440 minutes. One division,
read two ways:

```
     556 jobs  ÷  1,440 minutes   =   0.39 jobs arriving per minute
   1,440 minutes  ÷  556 jobs     =   one arriving every 2.6 minutes
```

0.39 and 2.6 are the same fact. **2.6 minutes is the worker's window.**

Now try three job durations. Every number below is worked out in the cell, so
nothing has to be taken on trust:

| If a job takes | it clears<br>**1 ÷ job time** per min | jobs arrive at<br>**556 ÷ 1440** | **arrive ÷ clear** | what that means | after 100 jobs |
| --- | ---: | ---: | ---: | --- | --- |
| 1.0 min | 1 ÷ 1.0 = **1.00** | 0.39 | 0.39 ÷ 1.00 = **0.39** | clearing faster than they arrive | queue still empty |
| 2.6 min | 1 ÷ 2.6 = **0.385** | 0.39 | 0.39 ÷ 0.385 = **1.01** | exactly on the line | empty, but no slack at all |
| 4.0 min | 1 ÷ 4.0 = **0.25** | 0.39 | 0.39 ÷ 0.25 = **1.56** | **arriving faster than they leave** | **140 minutes behind** |

That last column has to stay **below 1**. Below 1 the worker clears each job
before the next one arrives and is free to take it. Above 1 it is still busy
when the next one lands, so work stacks up and never unstacks. Nothing here
measures how long a job takes, so which side of the line this sits on is
unknown — recorded as a gap.

<details>
<summary><b>The issue we hit</b> &nbsp;—&nbsp; one tray had no worker at all (fixed)</summary>
<br>

Originally the command had no `-Q` at all:

```
celery -A app.celery_app worker
```

When `-Q` is missing, Celery falls back to a default tray — the one named
`celery`. So the worker went to tray 1 and started emptying it.

Nobody ever started a worker with `-Q analytics`.

```
   BEFORE                                AFTER

   tray 1 ──▶ worker ✅                  tray 1 ──▶ worker  (-Q celery)     ✅
   tray 2 ──▶  ???                       tray 2 ──▶ worker  (-Q analytics)  ✅
              (nobody)
```

</details>



---

<a href="#ch-2">▲ top of §2</a> <sub>(click the heading there to fold it)</sub> &nbsp;·&nbsp; <a href="#map-2">↑ back to §2 in the diagram</a>

</details>

<details id="ch-3">
<summary><b>§3 &nbsp; The sources</b> &nbsp;—&nbsp; the 67 places data comes from, and what each one feeds</summary>
<br>

**`app/fetcher_registry.py` · `app/sources/rss_feeds.json`**

## What it is

A **source** is one website or one public API this project downloads from.
There are 67, each with one row in the timetable from §1. Nothing else is
collected — if it is not in this table, the project has never seen it.

## All 67

The last column is the one that matters: **which score, if any, this source
ends up inside.**

| Source | What it gives | Where it is pulled from | Fetched | Feeds |
| --- | --- | --- | ---: | --- |
| `yfinance` | share prices, indices, currencies | `yf.Ticker(sym).history(...)` | 288/day | composite → market |
| `fred` | inflation, unemployment, yields | `fred.stlouisfed.org` API | 1/day | composite → market |
| `gdelt` | machine-coded world events | `data.gdeltproject.org/gdeltv2/lastupdate.txt` | 96/day | composite → geopolitical · CII |
| `acled` | recorded conflict events | `acleddata.com/api/acled/read`, or local `.csv`/`.xlsx` | 24/day | composite → geopolitical · **labels §23** |
| `usgs-quake` | earthquakes | `earthquake.usgs.gov/.../4.5_day.geojson` | 96/day | composite → hazard · CII |
| `gdacs` | cyclone, flood, drought alerts | `gdacs.org/xml/rss.xml` | 96/day | composite → hazard · CII |
| `eonet` | ongoing natural events | `eonet.gsfc.nasa.gov/api/v3/events` | 48/day | composite → hazard · CII |
| `emdat` | historical disaster archive | a local file, `EMDAT_CSV_PATH` | 1/day | composite → hazard |
| `nasa-firms` | satellite fire detections | `firms.modaps.eosdis.nasa.gov/api/area/csv/` | 24/day | composite → wildfire |
| `uk-police` | recorded crimes, 6 UK cities | `data.police.uk/api` | 1/day | CII only |
| 53 news sites | headlines | each site's RSS URL, one entry per site in `rss_feeds.json`:<br><br>`{`<br>&nbsp;&nbsp;`"source": "rss-bbc-world",`<br>&nbsp;&nbsp;`"url": "https://feeds.bbci.co.uk/news/world/rss.xml",`<br>&nbsp;&nbsp;`"pretty_name": "BBC World",`<br>&nbsp;&nbsp;`"cadence_min": 60,`<br>&nbsp;&nbsp;`"owner": "bbc",`<br>&nbsp;&nbsp;`"country": "GB",`<br>&nbsp;&nbsp;`"class": "mainstream"`<br>`}` | 24/day each | CII · §16 · §18 · §20 |
| `opensky-adsb` | aircraft positions | `opensky-network.org/api/states/all` | 24/day | **nothing scored** — map only |
| `abuse-ch-urlhaus` | URLs currently serving malware — from abuse.ch, a Swiss non-profit publishing free lists of known-bad internet infrastructure | `urlhaus.abuse.ch/downloads/csv_recent/` | 96/day | **nothing scored** — map only |
| `abuse-ch-feodo` | IP addresses running botnet control servers — same publisher, a blocklist of the kind a firewall loads | `feodotracker.abuse.ch/downloads/ipblocklist.csv` | 96/day | **nothing scored** — map only |
| `polymarket` | prediction-market odds | `gamma-api.polymarket.com/markets` | 48/day | **nothing scored** — map only |

Two things fall out of the last column.

**Four sources feed no score at all.** Aircraft, two cyber feeds and prediction
markets are collected, stored and drawn on the map, and no number in this
project depends on them.

**News does not enter the composite index.** News rows are stored with category
`NEWS`, and the composite only reads `market`, `geopolitical` and `hazard`. So
the 53 news sites — half of all traffic in §2's fast tray — feed the story and
disagreement work, and the CII, but **not the score that gets tested in §25.**

## What the 53 news sites are

| Property | Count | What is actually in it |
| --- | ---: | --- |
| Declared in `rss_feeds.json` | 55 | every feed the project knows about, on or off |
| Switched on | **53** | the 2 off are `rss-nhk-world` and `rss-rt-news`, parked as dead URLs |
| Publishing in English | **54 of 55** | everything except one |
| Publishing in another language | **1** | `rss-aljazeera-arabic` — Arabic |
| Countries the outlets sit in | **28** | GB×12 · US×6 · PK×4 · KE×3 · QA, FR, RU, IN, IL, NL ×2 each · then DE, JP, CA, AU, NZ, SG, SA, UA, ZA, EG, UY, MX, BR, KR, HK, ID, VN, TR with one apiece |
| Based in the UK or US | **18 of 55** | the GB×12 and US×6 above — a third of the sample from two countries |
| Distinct owners | **49** | 55 feeds, 49 owners: `bbc` and `reach` own 3 each, `aljazeera` and `russian-state` own 2 each, the other 45 own one apiece |
| By type | **4 groups** | 24 regional (Dawn, Geo, Times of India) · 16 mainstream (BBC, Reuters, Guardian) · 8 state-owned (RT, TASS, Arab News, SABC) · 7 independent (The Intercept, Middle East Eye, Antiwar.com) |

## What that costs a claim

The news sample is **almost entirely English-language**, and a third of it is
UK- or US-based. Every narrative measurement in this project is computed over
that sample.

So when §18 reports how differently countries word a story, it is in practice
reporting how differently **mostly Anglophone outlets** word it. That is a
narrower claim than "how the world reports this", and the difference is not
recoverable by weighting — a viewpoint that was never collected cannot be
re-weighted into existence.

---

<a href="#ch-3">▲ top of §3</a> <sub>(click the heading there to fold it)</sub> &nbsp;·&nbsp; <a href="#map-3">↑ back to §3 in the diagram</a>

</details>

<details id="ch-4">
<summary><b>§4 &nbsp; The rest gate</b> &nbsp;—&nbsp; a source that keeps failing is left alone for a while</summary>
<br>

**`app/ingest/quarantine.py`**

## What it is

Before any download starts, one question: **is this source resting?**

A source that has failed repeatedly is put to sleep for a while. When its turn
comes round again, the job returns immediately instead of making the request.

```
   timetable row fires
        │
        ▼
   is this source resting?
        │
        ├── yes ──▶ stop. one database query, no request made
        │
        └── no  ──▶ download (§5)
```

Without it, a feed that has been dead for a week is still asked every hour,
forever. One dead feed cost **420 requests in a week** before this existed.

## What counts as a failure worth resting for

Not everything. Only what the server actually said:

| Server replies | Meaning | Result |
| --- | --- | --- |
| `401` unauthorised | you may not have this | **permanent** rest |
| `403` forbidden | you may not have this | **permanent** rest |
| `404` not found | nothing is here | **permanent** rest — *usually, see below* |
| `410` gone | nothing is here, ever | **permanent** rest |
| `429` too many requests | slow down | **throttled** rest |
| anything else | timeout, network blip, 500 | no rest — try again next time |

## How long it rests

Each consecutive failure makes the nap longer:

| Failure | `permanent` waits | `throttled` waits |
| ---: | --- | --- |
| 1st | 1 hour | 15 minutes |
| 2nd | 6 hours | 1 hour |
| 3rd | 1 day | 6 hours |
| 4th | 3 days | 1 day |
| 5th+ | 7 days | 1 day |

Capped at **7 days**. One success wipes the record clean.

Throttled recovers faster on purpose — `429` means *later*, not *never*.

## The one exception

A `404` normally means "this is not here and will not be". That is true when a
URL names the same thing every time — `bbc.co.uk/rss.xml` is the same document
tomorrow.

**GDELT is different.** Its URL names the fifteen-minute window it covers, so
every fetch asks for a *different* file. A `404` there means **not published
yet** — a fact about this minute, not about the source.

Each fetcher declares which kind it is:

```python
stable_urls: bool = True     # same URL, same resource → 404 is permanent
```

GDELT sets it `False`. Without that flag, a `404` parked the largest feed in
the system for an hour, over a file that answered normally 200 minutes later.

`401` and `403` stay permanent either way — being forbidden is a fact about the
resource however it is addressed.

---

<a href="#ch-4">▲ top of §4</a> <sub>(click the heading there to fold it)</sub> &nbsp;·&nbsp; <a href="#map-4">↑ back to §4 in the diagram</a>

</details>

<details id="ch-5">
<summary><b>§5 &nbsp; Fetch</b> &nbsp;—&nbsp; download only, and turn 67 different shapes into one</summary>
<br>

**`app/sources/base.py` · `app/models.py`**

## What it is

Download the data, convert it, hand it back. Nothing else.

A fetcher **cannot** touch the database, Redis or the scheduler. It is a
function: URL in, list of rows out. That is enforced by the contract every
fetcher inherits:

```python
class Fetcher(ABC):
    """Pure HTTP-side fetcher. No database, no Redis, no Celery awareness."""

    name: str                      # the source slug, e.g. "gdelt"
    stable_urls: bool = True       # the §4 flag

    @abstractmethod
    def fetch(self) -> list[Event] | FetchBatch: ...
```

Why it matters: a fetcher can be run and tested with no database, no queue and
no network of its own. Fetching and storing fail separately, so a parsing bug
cannot be mistaken for a dead feed.

## The one shape everything becomes

67 sources publish 67 different formats — CSV, GeoJSON, RSS, XML, JSON. Each
source gets its own small translator, and all 67 produce the same output:

```
   USGS GeoJSON   ─┐
   BBC RSS        ─┤
   NASA CSV       ─┼──▶  67 translators  ──▶  one shape  ──▶  everything else
   ACLED xlsx     ─┤
   ...            ─┘
```

Everything after this stage only ever sees one shape:

```python
class Event(BaseModel):
    source: str            # which feed
    source_event_id: str   # that feed's own ID for this thing
    occurred_at: datetime  # when it happened
    fetched_at: datetime   # when we saw it
    category: Category     # market / geopolitical / hazard / news / cyber / ...
    severity: float | None # 0-1, and only comparable within one source
    country: str | None    # ISO code, or None
    lat / lon: float | None
    payload: dict          # the original record, kept whole
```

### Two timestamps, always

```
   occurred_at   when the world moved
   fetched_at    when this system found out
```

The gap between them is **reporting delay**. Some sources are fast — USGS
publishes an earthquake in seconds. Some are slow — UK police publish about two
months in arrears.

Store only one timestamp and that difference cannot be measured. Not reduced,
**invisible**: you cannot correct for something you never recorded. §3 already
showed the sources are not evenly fast, so this is a real bias, not a
hypothetical one.

### Two smaller ones

**Location can be empty.** `None` means *we do not know*. The alternative —
filling in the source's home country, or a country's centre point — would make
every downstream count wrong in a way nobody could see from the outside.

**The original is kept whole.** `payload` holds the source's own record, so the
translation is never the only copy. A translator bug can be fixed and the rows
re-derived without asking the source again — which for feeds that only publish
recent data would be impossible anyway.

### One warning

`severity` is **not** comparable across sources. A 0.8 earthquake and a 0.8
headline share a column name and a scale, and nothing else. §14 is where that
had to be dealt with.

## Three ways a fetch ends

```
   fetch()
     │
     ├── raises SourceMisconfiguredError  →  local setup is wrong
     │                                       (missing API key). Not a rest,
     │                                       not a retry — its own state.
     │
     ├── raises anything else             →  record failure, ask §4 whether
     │                                       this earns a rest
     │
     └── returns rows                     →  on to §6
```

## What happens when it fails

**Nothing is stored.** A failed fetch writes no rows at all — there is no half
a batch. The failure itself is recorded, and what happens next depends on what
broke:

| What broke | Recorded as | Retried? | What happens next |
| --- | --- | --- | --- |
| Local setup — missing API key, bad file path | `misconfigured` | no | a person has to fix it; the source is asked again on its next turn |
| Server said `401` `403` `404` `410` `429` | `failed`, with the error text | **no** | §4 puts the source to sleep, 1 hour to 7 days |
| Timeout, `500`, network blip | `failed`, with the error text | **yes — up to 5 times**, with a growing gap between attempts | if all five fail, the run is given up and the next scheduled turn starts fresh |

The difference between the last two rows is the point of §4. A `403` will still
be a `403` in five seconds, so retrying is five wasted requests — that is how
one dead feed spent 420 requests in a week. A timeout might not be a timeout in
five seconds, so it is worth asking again.

Two things are always true on failure:

- **No partial writes.** The database is untouched, so a later run cannot find
  half-imported data.
- **The failure is visible.** A counter goes up in `ingest_health` and the full
  error text is stored in `ingest_failures`, which is what lets §10 say *which*
  source is broken and *why* rather than just that something is quiet.

---

<a href="#ch-5">▲ top of §5</a> <sub>(click the heading there to fold it)</sub> &nbsp;·&nbsp; <a href="#map-5">↑ back to §5 in the diagram</a>

</details>

<details id="ch-6">
<summary><b>§6 &nbsp; Inline enrichment</b> &nbsp;—&nbsp; news headlines only, and the order is the point</summary>
<br>

**`app/sources/rss_news_fetcher.py` → `entry_to_event()`**

## What it is

A headline arrives as a line of text and nothing else. No country, no
coordinates, no idea how bad it is. Five steps add that, **while the row is
still being built** — before it reaches the database.

Only news rows go through this. The other 14 sources already publish structured
fields.

```
   "Blast kills 12 in Karachi market"
        │
        ├─ 1. translate   → English title, original kept in the payload
        │                   local model, only if the feed declares another language
        │
        ├─ 2. severity    → 0.0 - 1.0 plus a written reason
        │                   keyword rules — provisional, replaced later by §20
        │
        ├─ 3. locate      → country + lat/lon, or nothing at all
        │                   scored: country names and demonyms → regions →
        │                   city gazetteer → the outlet's own desk
        │
        ├─ 4. sentiment   → -1.0 to +1.0
        │                   VADER, over title + summary
        │
        └─ 5. names       → people, places, organisations
                            spaCy; empty list if the model is not installed
        │
        ▼
   one Event row, ready for §7
```

## What the severity keywords are

Step 2 is a word list, not a model. Three groups, checked hardest-first, each
with a floor the score cannot fall below:

| Group | Example words | Floor |
| --- | --- | ---: |
| **lethal** | killed · dead · died · fatal · fatalities · massacre · murdered · assassinated · executed · beheaded | **0.60** |
| **mass casualty** | the lethal words *plus* 10 or more deaths, or a massacre | **0.80** |
| **violent** | attack · explosion · blast · bomb · shooting · strike | below 0.60 |

Those floors land the row in one of five bands, which tile `[0, 1]` with no
gaps — every score belongs to exactly one:

| Band | Range | Means |
| --- | --- | --- |
| `routine` | 0.00 – 0.20 | policy, business, sport — nothing happened to anyone |
| `tension` | 0.20 – 0.40 | protest, strike, diplomatic rupture — no violence |
| `violence` | 0.40 – 0.60 | violence without confirmed death, or mass displacement |
| `grave` | 0.60 – 0.80 | confirmed deaths (1–9), or serious armed attack |
| `mass_casualty` | 0.80 – 1.00 | 10+ dead, massacre, mass-fatality disaster |

The example headline hits `kills` → lethal → floor `0.60`, and `12` deaths →
mass casualty → floor `0.80`. It lands in `mass_casualty`.

**Why a word list at all**, given §20 replaces it with a model: so no row is
ever unscored. A model needs a running local LLM and a spare few seconds; the
word list needs neither, and gives every row a defensible floor the moment it
arrives.

## What the sentiment number is

Step 4 is **VADER** — also a word list, scored and combined into one number
between `-1` and `+1` called the *compound* score.

| Compound | Label | Reading |
| --- | --- | --- |
| `≥ +0.05` | positive | |
| `-0.05` to `+0.05` | neutral | most factual headlines land here |
| `≤ -0.05` | negative | |

Two cautions, because this number is easy to over-read:

- It measures the **tone of the words**, not whether the event was good or bad.
  "Aid reaches survivors" scores positive; the event behind it is a disaster.
- The cut-offs are **VADER's own published defaults**, not tuned on this data,
  and the label exists so the console can colour a chip. Nothing scored is
  decided by it.

## Why translate first

This is the one ordering that is load-bearing, and it was learned the hard way.

Steps 2, 3 and 5 all read **English words**. The severity rules match English
keywords. The locator matches English country names and demonyms. The story
tokeniser in §16 splits English text.

Run them on an Arabic headline and every one of them finds nothing:

```
   Arabic desk, before translation was moved first:
     0 of 25 rows resolved to a country
     every row scored the same constant severity
```

A feed can therefore look perfectly healthy — rows arriving, no errors — while
contributing **nothing** to any measurement. Translation goes first so the four
steps after it have English to work with.

## Two refusals worth noting

**A story about nowhere gets no country.** The locator scores candidates; a
headline naming several countries and being about none of them resolves to
`None` rather than picking the highest score. An unknown location is recorded
as unknown.

**The severity here is provisional.** Keyword rules are a floor, not an answer —
they exist so a row is never unscored. §20 replaces the value with a model
grade, and §26 is where a person checks whether that grade is any good.

## What gets written down

Every enrichment records **which method produced it**, so a value can be traced
back to the version of the thing that made it:

```python
"enrichment_meta": {
    "sentiment_model": SENTIMENT_METHOD_VERSION,
    "ner_model":       NER_METHOD_VERSION if ner_available() else "none",
    "geo_model":       GEO_METHOD_VERSION,
}
```

`"none"` is stored honestly when a model is missing, rather than the field being
quietly absent — so a row enriched by nothing is distinguishable from a row
nothing was found in.

---

<a href="#ch-6">▲ top of §6</a> <sub>(click the heading there to fold it)</sub> &nbsp;·&nbsp; <a href="#map-6">↑ back to §6 in the diagram</a>

</details>

<details id="ch-7">
<summary><b>§7 &nbsp; Publication-time repair</b> &nbsp;—&nbsp; nothing is allowed to claim it happened in the future</summary>
<br>

**`app/ingest/publication_time.py`**

## What it is

Some feeds stamp an article with a time that has not happened yet — the feed
says `16:25` while the clock says `14:06`. Usually a timezone written wrongly:
one feed stamps local time and labels it `GMT`, so every row is exactly three
hours out.

Three things break if that reaches the database:

| | |
| --- | --- |
| **sorting** | newest-first puts future rows permanently on top; they never age out |
| **freshness** | "latest data is N minutes old" goes negative |
| **windows** | "the last 24 hours" includes things that have not happened |

## The two repairs

Worked on a real case: **four articles from one feed's front page**, read at
`14:06 UTC`. The feed says three of them were published at `16:25`, `16:17` and
`15:43` — all still in the future — and one at `13:57`, which is fine.

| | **shift** | **clamp** |
| --- | --- | --- |
| **What the word means** | move **every** row back by the **same** amount | force each future row to **now** |
| **When it is used** | 3+ rows ahead, and at least a quarter of the batch — so it looks like the feed is wrong, not one row | that test fails, so no pattern can be proved |
| **How far to move** | biggest lead is 139 min → round up to whole hours → **3 hours** | not a distance — every future row becomes `14:06` |
| **Which rows change** | **all** of them, even ones already in the past | **only** the ones dated ahead |
| **What the feed said → what gets stored** | `16:25` → `13:25`<br>`16:17` → `13:17`<br>`15:43` → `12:43`<br>`13:57` → `10:57` | `16:25` → `14:06`<br>`16:17` → `14:06`<br>`15:43` → `14:06`<br>`13:57` → `13:57` |
| **What ends up stored** | the **real publication time** — only the label was wrong | the time **we happened to look**; `occurred_at` becomes `fetched_at` |
| **PRO** | the stored time is true, so everything computed from it is too | always works, nothing has to be proved |
| **CON** | assumes the whole batch shares one offset — a feed mixing timezones would have correct rows moved wrongly | the true time is lost. A row really published `31 Jan 23:40` and clamped to `1 Feb 00:10` is counted in the wrong **month** by §14, and a row stamped *now* never looks old enough for §8 to reject |
| **What is done about the CON** | the thresholds must pass first, and the original timestamp is stored beside the corrected one, so any wrong shift is reversible | same — the original is kept, and clamps are counted separately from shifts, so a feed that is *always* clamped is identifiable as genuinely broken rather than merely mislabelled |

Nothing automatic acts on a feed that is always clamped. It is recorded so it
can be found, and that is all — noted as a gap.

## Two things worth knowing

**This is bias, not noise.** A feed three hours out is three hours out every
time. It does not average away, so it has to be corrected rather than tolerated.

**It runs before §8.** The freshness gate discards rows that are too old. Judge
a three-hour-wrong batch on its stated time and real news is thrown away to fix
a clock.

---

<a href="#ch-7">▲ top of §7</a> <sub>(click the heading there to fold it)</sub> &nbsp;·&nbsp; <a href="#map-7">↑ back to §7 in the diagram</a>

</details>

<details id="ch-8">
<summary><b>§8 &nbsp; The freshness gate</b> &nbsp;—&nbsp; how old is too old, decided per source</summary>
<br>

**`app/ingest/freshness.py`**

## What it is

Drop rows that are too old to count as current. One rule, one age limit —
except the limit is **different for each source**, and that is the only
interesting part of the stage.

## How old is too old

| Source | Typical age on arrival | Limit |
| --- | --- | --- |
| news, hazard | hours | **30 days** |
| `abuse-ch-*` | 30 days — republishes a rolling window | **45 days** |
| `yfinance`, `fred`, `emdat`, `acled`, `polymarket` | months to years | **none** |
| `uk-police` | a month, always — released monthly | **none** |

Two different reasons a source has no limit:

- **the history is the point** — a market or economic series exists to be long
- **the publisher is slow** — crime data is released monthly, so every row is
  already a month old when it becomes available

## Where the 30 comes from

Not chosen. Retention deletes rows at 30 days (§13), so the rule is: **do not
store what the next cleanup would delete anyway.**

Stricter would be worse. Legitimate news feeds routinely run 10–20 days behind,
and dropping real news leaves no trace — while the stale rows it removes are at
least visible in the data.

**Worth stating plainly:** the 30 days and the 30 GB ceiling are *settings*
(`RETENTION_*_DAYS`, `STORAGE_CAP_GB`), not limits the hardware imposes — the
machine this runs on has several times that free. So the number is a policy
choice, and this gate inherits it rather than deriving one of its own.

That matters for reading any result built on the live window. Change the
retention policy and this bound should be revisited with it, because its only
justification is *"do not store what the cleanup deletes"* — remove the cleanup
and the justification goes with it.

---

<a href="#ch-8">▲ top of §8</a> <sub>(click the heading there to fold it)</sub> &nbsp;·&nbsp; <a href="#map-8">↑ back to §8 in the diagram</a>

</details>

<details id="ch-9">
<summary><b>§9 &nbsp; Upsert and dedup</b> &nbsp;—&nbsp; one row per real event, however many times it arrives</summary>
<br>

**`app/persistence.py`**

## The two words

| Word | Short for | Means |
| --- | --- | --- |
| **upsert** | *update* + *insert* | if this row is new, insert it; if it already exists, update the one that is there |
| **dedup** | *deduplicate* | make sure the same real-world event never becomes two rows |

## Why this stage exists at all

The same event arrives **again and again**. That is normal, not a bug:

- a news feed keeps a story on its front page for hours; every hourly fetch sees it
- a hazard feed re-publishes every *active* cyclone on every 15-minute fetch
- a fetch is retried after a timeout and pulls the same batch twice

Without this stage, one cyclone becomes **96 rows a day**.

**Why that is fatal, in data terms:** §14 scores a country by counting events
per month. A duplicated event is a **fabricated observation** — the count goes
up, the z-score goes up, the score goes up, and nothing in the data reveals it.
Deduplication is not tidiness. It is the difference between counting events and
counting fetches.

## How a duplicate is recognised

Every row carries the source's **own** identifier for the thing:

```python
source            = "gdacs"
source_event_id   = "CY-1001234"     # GDACS's ID, not one we invented
```

The pair `(source, source_event_id)` is declared unique in the database. Two
rows with the same pair are, by definition, the same event.

Using **the source's own ID** matters. Anything we invented — a hash of the
title, say — would break the moment the source edited a typo in that title, and
the same event would become two.

## What happens on a repeat

```sql
INSERT ... ON CONFLICT (source, source_event_id) DO UPDATE
```

Plain English: *try to insert; if that pair already exists, update the existing
row instead.* The database does this in one operation, so there is no gap where
a second process could insert a duplicate.

But **not every column is updated**, and that split is the substance of the
stage:

| Column group | On a repeat | Why |
| --- | --- | --- |
| **identity** — `source`, `source_event_id`, `category` | **never touched** | these define which row it is; changing them would make it a different event |
| **live values** — `occurred_at`, `fetched_at`, `severity`, `confidence`, `keywords` | **replaced** | an ongoing cyclone must not freeze at its first-seen state and drop out of the live window |
| **location** — `country`, `lat`, `lon` | **news replaces, others keep** | empty from news is an *answer* — the locator re-read the text and it no longer supports that country; empty from an API is a *gap*, and §12 may fill it later. Never overwrite an answer with a gap |
| **enrichment inside `payload`** — the extras *we* added after the row landed: real map outline, place name, sentiment, entity names (22 keys, listed in `ENRICHMENT_PAYLOAD_KEYS`) | **protected** — the incoming payload is *merged over* the stored one, never replaces it | The fetcher never sends these back; it does not know they exist. Replacing the whole payload deletes them — and did: a hazard feed re-published every active event every 15 minutes and each refresh wiped the real map geometry. Silent for weeks — nothing errored, the map just showed circles instead of shapes. A test walks the key list, so a refresh that starts destroying enrichment fails the suite instead of quietly emptying the map |

### Replace, or merge

`payload` is the only column with **two writers** — the fetcher, and our own
later jobs. Replacing it lets the fetcher speak for both:

```python
stored   = {"title": "Cyclone Alpha", "footprint_geojson": {...}, "sentiment": -0.4}
incoming = {"title": "Cyclone Alpha"}      # the fetcher only knows its own half

replace = incoming                 # {"title": ...}      — geometry and sentiment gone
merge   = {**stored, **incoming}   # keeps both, and upstream still wins on `title`
```

The database does exactly that merge, one operator:

```sql
payload = events.payload || EXCLUDED.payload   -- stored first, incoming layered on top
```

Read it left to right: start from what is stored, let the incoming keys
overwrite the ones they mention, leave the rest alone. Every other column keeps
plain `= EXCLUDED.x`, because for those the source is the only writer.

<details>
<summary>The 22 protected keys, by family</summary>
<br>

Every one is written *after* the row lands, by a job the fetcher knows nothing
about. Note the shape: each enrichment stores the **value** and also **who,
when, how sure** — provenance, so a published number can be traced back to what
produced it.

| Family | Keys | What they hold |
| --- | --- | --- |
| **map shape** (3) | `footprint_geojson`, `footprint_checked_at`, `footprint_source_key` | the real hazard outline instead of a drawn circle; when we last looked, so a source with no geometry is not asked forever; which upstream document it came from |
| **verified place** (13) | `place_name`, `place_wikidata_id`, `place_description`, `place_locations`, `place_candidate_count`, `place_verified_count`, `place_rejections`, `place_rejected_count`, `place_checked_at`, `place_model`, `place_resolution`, `geo_precision`, `geo_source` | the location label plus an external ID so it is auditable; every point verified for one story; how many names the text proposed, how many survived, and the evidence for each refusal; when, by which model, at what exactness, from which authority |
| **text read** (4) | `sentiment`, `sentiment_label`, `entities`, `city` | tone as a number in −1…+1 and as a word; names pulled out of the text; city recovered from the headline |
| **bookkeeping** (2) | `news_scope`, `enrichment_meta` | local / national / international reach; which enricher and model wrote all of the above |

3 + 13 + 4 + 2 = **22**.

</details>

## Duplicates inside one batch

A single fetch can contain the same ID twice. The database cannot update the
same key twice in one statement, so duplicates are collapsed **before** the
write — keeping the newest by `fetched_at`, then `occurred_at`.

Rows with **no** ID are passed through untouched: they cannot collide with
anything, and dropping them would lose real events.

## Scale

Written **1,000 rows per statement** — 12 columns × 1,000 = 12,000 bound
parameters, well under the database's 65,535 limit, with headroom for more
columns later.

---

<a href="#ch-9">▲ top of §9</a> <sub>(click the heading there to fold it)</sub> &nbsp;·&nbsp; <a href="#map-9">↑ back to §9 in the diagram</a>

</details>

<details id="ch-10">
<summary><b>§10 &nbsp; Did we see anything?</b> &nbsp;—&nbsp; a run that brings back nothing usable is recorded as such</summary>
<br>

**`app/ingest/outcome.py`**, **`app/watchdog.py`**

The diary of whether the system was actually working. It writes one word per
run, and something else reads that diary and shouts when a source has gone
quiet.

## One fetch, 10:00

```
10:00   ask a news feed         → replies with 50 stories
        §8 checks the dates     → 8 too old, thrown away
        §9 writes the other 42  → 12 brand new, 30 already stored
```

Four numbers now exist:

```
fetched   = 50     handed to us
rejected  =  8     §8 threw away
accepted  = 42     §9 wrote
inserted  = 12     never seen before
```

Those four are **all §10 works with**. It never looks at the stories themselves.

## Step 1 — hand the numbers over

```python
result = ingest_outcome.classify(
    fetched=50, accepted=42, affected=42, inserted=12, rejected=8
)
```

## Step 2 — pick the word

```python
if accepted == 0:      state = "empty"
elif inserted > 0:     state = "new_data"
else:                  state = "unchanged"
```

Three questions in order:

| Question | Our fetch | Result |
| --- | --- | --- |
| did we write **anything**? | 42 — yes | not `empty` |
| was any of it **new**? | 12 — yes | → **`new_data`** |
| otherwise | — | `unchanged` |

A broken hour goes the other way: `fetched = 0, accepted = 0` → `accepted == 0`
→ **`empty`**. The feed replied and nothing arrived. Recording that as *empty*
rather than *success* is the entire point of the stage.

Two more words exist for cases the counts cannot describe: `misconfigured` (a
key or setting of ours is missing — never the source's fault, never a reason to
quarantine it in §4) and `failed` (the run raised: timeout, bad status,
unreadable body).

Impossible counts are refused rather than stored, so a bug upstream cannot
produce a healthy-looking row:

```python
if inserted > affected or affected > accepted:
    raise ValueError("inserted <= affected <= accepted must hold")
if accepted + rejected > fetched:
    raise ValueError("accepted and rejected rows cannot exceed fetched rows")
```

## Step 3 — write it down

```python
row.last_state   = "new_data"
row.last_checked = 10:00      # we looked
row.last_success = 10:00      # it replied
row.last_output  = 10:00      # data actually arrived
```

Three separate facts. On a good hour all three read the same time, which is why
keeping them apart looks pointless — until something breaks.

## Why three clocks

The interesting failure is the quiet one: the feed keeps replying, with nothing
inside.

| Time | Replies? | Rows | `last_checked` | `last_success` | `last_output` |
| --- | --- | --- | --- | --- | --- |
| 10:00 | yes | 42 | 10:00 | 10:00 | **10:00** |
| 11:00 | yes | 0 | 11:00 | 11:00 | 10:00 |
| 12:00 | yes | 0 | 12:00 | 12:00 | 10:00 |
| 13:00 | yes | 0 | 13:00 | 13:00 | 10:00 |

The last column is frozen while the other two look perfectly fresh.

- watching `last_success` → *"replied a minute ago, all good"* — the lie
- watching `last_output` → *"no data for three hours"* — the truth

The alarm reads the frozen one. Two static archives are the exception, judged on
`last_success`, because they genuinely publish nothing most days.

## How long before shouting

```python
threshold = cadence_min * 6
is_stale  = (now - last_output) > threshold
```

A fixed number of minutes cannot work — sources run at different speeds:

| Source runs every | Silent for | Shout? |
| --- | --- | --- |
| 15 min | 90 min (6 × 15) | yes |
| 60 min | 6 hours | yes |
| once a day | 6 days | yes |

Six and not one: a single missed run is normal — a slow response, a restart. Six
in a row is not. Give it six chances before crying wolf.

Each crash also stores one row of evidence — error class, message, request URL,
response body — so a gap can be explained later instead of guessed at.

## Why any of this matters

Months later something reads:

```
country X, March:  0 events
```

| The diary says | The zero means |
| --- | --- |
| `new_data` all month | we were watching, nothing happened — a **real** zero |
| `empty` all month | we were not watching — a **fake** zero |

Same number, opposite meaning, and nothing inside the events table separates
them. §14 counts events per country per month, so the fake zero is published as
*that country was calm*.

**A bias, not noise:** a broken feed is not spread evenly. One feed covers one
region, so when it breaks that region alone loses events and the index reads
"improving".

<details>
<summary><b>Issue</b> &nbsp;—&nbsp; a table nothing writes</summary>
<br>

`dead_letter_queue` is created by the first migration and described in the
architecture notes: after five failed retries a job was to be parked there and
re-enqueued hourly. Nothing writes to it, and no such worker exists.

It is a leftover from an **event-driven** design, where a failed message is lost
work that has to be stored and replayed. Here the scheduler (§1) fires the same
source again in 5, 15 or 60 minutes anyway — the next run does the same job, so
there is nothing to replay. The problem that turned out to be real was the
opposite one, a broken source being hammered five times a run forever, and that
is what quarantine (§4) solved.

</details>

---

<a href="#ch-10">▲ top of §10</a> <sub>(click the heading there to fold it)</sub> &nbsp;·&nbsp; <a href="#map-10">↑ back to §10 in the diagram</a>

</details>

<details id="ch-11">
<summary><b>§11 &nbsp; events</b> &nbsp;—&nbsp; the one table every source writes into, whatever it measured</summary>
<br>

**`app/db_models.py`**, **`app/models.py`**

Everything before this chapter was collection. This is **the dataset** — the
thing every later number is computed from.

## The problem

An earthquake, a share price, a headline and a malware address have nothing in
common. Give each its own table and §14 — *how many events in this country last
month* — has to join 67 tables with 67 date columns and 67 ideas of location.
Every new source rewrites every query downstream.

So there is one table, and all 67 conform to it.

## The 12 columns

| Column | Holds | Note |
| --- | --- | --- |
| `source` | who reported it | `gdacs`, `rss-bbc` |
| `source_event_id` | their own id for it | with `source`, unique — §9's key |
| `occurred_at` | when it **happened** | |
| `fetched_at` | when **we pulled it** | a different fact, kept separate |
| `updated_at` | when the row last changed | |
| `category` | which of ten kinds | `hazard`, `market`, `news`, `cyber`, … |
| `severity` | how bad, **0…1** | nullable |
| `confidence` | how sure, **0…1** | nullable |
| `keywords` | tags the fetcher attaches | not free text — a short fixed list per source: `["usgs", "earthquake", "m6"]`, `["^VIX", "etf", "drawdown"]`. Search matches on list overlap, so they are filters, not description |
| `country` | the country **code**, two letters | `GB`, `US`, `SD` — the ISO 3166-1 standard, uppercase enforced. A code and not a name because *UK*, *United Kingdom* and *Britain* would group as three different countries. Nullable |
| `lat`, `lon` | where | nullable |
| `payload` | the original record, untouched | JSON. The receipt: everything the source sent, so nothing is lost in flattening and a row can be re-read later. Also where §12's enrichment is stored — the 22 protected keys of §9 |

## The same shape, three different worlds

```
earthquake   source="usgs-quake"  category="hazard"  severity=0.62
                                  payload={"magnitude": 6.1, "depth_km": 10}

market move  source="yfinance"    category="market"  severity=0.30
                                  payload={"ticker": "^VIX", "close": 24.1}

headline     source="rss-bbc"     category="news"    severity=0.45
                                  payload={"title": "…", "url": "…"}
```

Nothing downstream asks what kind of thing a row is. It asks *how many rows,
this country, this month, severity above this* — and the question is written
once for all 67 sources.

This is **tidy data**: one row is one observation, one column is one variable,
and a variable means the same thing in every row.

## Two kinds of storage in one row

```
┌──────────────────────────────────────────┬────────────────────┐
│  11 fixed columns  —  relational         │  payload  —  JSON  │
│  the analysis view, same for everyone    │  the raw receipt   │
│  indexed, constrained, groupable         │  source-specific   │
└──────────────────────────────────────────┴────────────────────┘
```

| | Relational columns | JSON bag |
| --- | --- | --- |
| shape | fixed, every row identical | free-form, every source different |
| good at | filtering, grouping, counting | holding whatever arrived |
| enforced | `severity BETWEEN 0 AND 1` | nothing |

One rule decides which side a field lands on:

> **anything you filter, group or count by is a real column. Everything else
> goes in the bag.**

`country`, `occurred_at`, `category` and `severity` are columns because §14
groups by them. `magnitude` and `ticker` are in the bag because nothing does.

## Two choices a reader should push on

| Choice | What it buys | What it costs |
| --- | --- | --- |
| **`severity` forced onto 0…1** for every category | a quake and a volatility spike become addable — *sum the severity for this country* is only legal because of it | the mapping is a modelling choice, not a measurement. §20 is where it is made, and where it should be challenged |
| **geography allowed to be empty** | a market event has no country, and inventing one would be fabricating data | *events in country X* silently excludes every unplaced row — a country total counts **located** events, not all of them |

## Enforced by the database, not by trust

```sql
UNIQUE (source, source_event_id)      -- §9's dedup
CHECK  (severity   BETWEEN 0 AND 1)   -- the scale cannot drift
CHECK  (confidence BETWEEN 0 AND 1)
```

---

<a href="#ch-11">▲ top of §11</a> <sub>(click the heading there to fold it)</sub> &nbsp;·&nbsp; <a href="#map-11">↑ back to §11 in the diagram</a>

</details>

<details id="ch-12">
<summary><b>§12 &nbsp; Post-ingest enrichment</b> &nbsp;—&nbsp; hazard outlines, place names and severity added afterwards</summary>
<br>

**`app/enrichment/`**, **`app/tasks.py`**

Raw data is never what an analysis eats. A source hands over a headline; the
analysis needs a number. Turning *"50 killed in a market bombing"* into
`severity = 0.85`, or a headline into `country = SD`, is **feature
engineering** — building the variables that will actually be counted. This is
where most of this project's features are made.

## Why they are not made during the fetch

A fetch has seconds, and must not make an extra network call per row.

| Feature | Needs | Cost per row |
| --- | --- | --- |
| real hazard outline | a second download from upstream | one HTTP call |
| verified place name | a lookup against an external knowledge base | one HTTP call |
| severity of a headline | a local language model reading the text | seconds of compute |
| story gist and embedding | another model pass | seconds of compute |

Inline, one slow lookup would stall a whole batch. So the row lands
**incomplete** and scheduled jobs come back for it.

## Every job, the same five steps

```
1. ask the database which rows are still missing this field
2. take a batch — a limit, never everything
3. fetch or compute the value
4. merge it into payload      (never replace — §9's protected keys)
5. one row fails → leave it, take it again next run
```

| Job | Runs at | Fills |
| --- | --- | --- |
| `enrich_footprints` | :11 :26 :41 :56 | real hazard geometry; without it the map draws a circle |
| `enrich_news_places` | :13 :43 | verified place name and an external id for it |
| `enrich_gdelt_titles` | every 5 min | article titles the feed does not ship |
| `grade_news_severity` | :14 :44 | severity 0–1 for a headline, by local model |
| `brain_enrich` | every 20 min | story summaries and embeddings |

The minute offsets are deliberate: none of them land in the same minute as the
fetchers that feed them.

## What this does to the data

**A feature made late is a feature that is partly missing.** Every enriched
column has a coverage rate below 100%, and blank means *not looked at yet* — not
*zero*. Reading an ungraded headline as severity 0 is the §10 mistake one level
up.

**Coverage can correlate with what is being measured.** Each job takes a limited
batch, so anything beyond capacity waits. If busy days overflow, the busiest
days end up the least enriched — the feature is weakest exactly when the world
is loudest. That is why the severity job is sized against arrivals rather than
left to drift: roughly 2,400 headlines a day of capacity against roughly 863
arriving, so a backlog drains instead of growing.

**Some columns are estimates wearing the same clothes as observations.**

| Column | Where it comes from | Status |
| --- | --- | --- |
| `occurred_at` | the source stated it | observation |
| `lat`, `lon` on a hazard | the source stated it | observation |
| `severity` of a headline | a model judged it | **estimate, with error** |
| `country` of a headline | a locator inferred it | **estimate, with error** |

Nothing in the schema marks which is which. An estimated feature needs an
accuracy claim attached to it, which is what §20 and §26 are for.

**A feature can expire.** A cyclone's stored outline was true when fetched and
wrong a day later — GDACS publishes a moving hazard as a numbered series, each
episode at its own URL, so the stored shape is a photograph of where the storm
was when first seen. Comparing the stored source key with the event's current
one costs a single string comparison and refetches only what actually moved.

---

<a href="#ch-12">▲ top of §12</a> <sub>(click the heading there to fold it)</sub> &nbsp;·&nbsp; <a href="#map-12">↑ back to §12 in the diagram</a>

</details>

<details id="ch-13">
<summary><b>§13 &nbsp; Retention and the cap</b> &nbsp;—&nbsp; old rows are deleted, so the dataset is a window and not an archive</summary>
<br>

**`app/housekeeping.py`**

Every stage before this one adds rows. This one deletes them — which makes the
dataset **a rolling window of the last 30 days**, not everything ever collected.

One job, nightly at 03:00 UTC, two rules:

```python
delete_rows_older_than(30, "days")        # rule 1 — age
if db_size > 30_GB:                       # rule 2 — size
    delete_oldest_whole_days_until_it_fits()
```

## What is kept, and for how long

| Data | Kept | Why |
| --- | --- | --- |
| news, GDELT, hazard, cyber, aviation, live markets | 30 days | a feed — a deleted row comes back on the next poll |
| FRED macro, EM-DAT disasters | **forever** | history — a deleted year does not come back |

## What that does to your numbers

| | |
| --- | --- |
| **Short memory** | *"how did this change over the past year?"* cannot be answered from `events`. The year is not in there — which is why Part III builds its own tables (§23, §24) |
| **Deleting a row deletes its labels** | a severity score (§12) is stored inside the row it describes, so a batch graded by hand today is gone in a month |
| **A falling count may be a delete** | not a quieter world. `housekeeping_runs` records what each night removed |

## It is a setting, not a fact

30 days and 30 GB are configuration (`RETENTION_*_DAYS`, `STORAGE_CAP_GB`),
picked for a small disk. **The deployment that runs all the time is not using
them** — it is set to a much longer window, so it is building a real long-term
series rather than a rolling month. Same code, two different datasets.

So **every count in this document is a count inside a 30-day window** unless it
says otherwise.

---

<a href="#ch-13">▲ top of §13</a> <sub>(click the heading there to fold it)</sub> &nbsp;·&nbsp; <a href="#map-13">↑ back to §13 in the diagram</a>

</details>

<details id="ch-14">
<summary><b>§14 &nbsp; The composite index</b> &nbsp;—&nbsp; four topics, scored against a country's own past, into one number</summary>
<br>

**`app/composite/`**

One number per country per month, 0 to 1: **how unusual is this country this
month, compared with its own past?**

## First, where this actually runs

The formula needs **12 months** of a country's past. The live table keeps
**30 days** (§13). So live it has nothing to compare against, and returns 0.5
for every country.

Where it does work is `app/composite/backfill.py`, which builds 2015→2024
history **in memory** — the rows never touch the events table, so retention
cannot eat them — and then runs the exact same pipeline. That is what feeds
`results/data/panel.csv` and the exams in Part III.

So the composite is an **offline evaluation instrument, not a live dashboard
number.**

## Step 1 — one number per month

Forget everything else. Pick one country. Count how much bad stuff happened,
each month:

```
Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec  |  NOW
 17  24  15  21  28  16  23  12  25  19  26  14  |   35
```

Two numbers come out of that row, and **neither is chosen — both are
calculated from the row itself.**

**Its normal** — the average:

```
17+24+15+21+28+16+23+12+25+19+26+14 = 240
240 ÷ 12 = 20                       ← normal
```

**Its wobble** — how far a typical month sits away from 20:

```
distances from 20:  3  4  5  1  8  4  3  8  5  1  6  6
54 ÷ 12 = 4.5                       ← wobble, call it 5
```

So this country's normal month is **20**, and it usually swings about **5**
either way. This month is **35**.

## Step 2 — the z-score = "how many wobbles above normal?"

```
z = (this month − normal) ÷ wobble
z = (35        − 20    ) ÷ 5
z = 15 ÷ 5
z = 3
```

`35 − 20 = 15` — fifteen above normal. A typical swing is only 5, so fifteen is
**three typical swings**.

Three wobbles above its own normal. That's it. That's the whole z-score.

- `z = 0` → totally normal month
- `z = 1` → a bit high
- `z = 3` → very unusual
- `z = −2` → unusually quiet

> **The wobble** is the standard deviation. The textbook recipe squares the
> distances before averaging and square-roots at the end — 5.02 for the row
> above — but *"how far a typical month sits from normal"* is the right picture
> and lands in the same place.

**Why divide by the wobble at all?** Because "15 above normal" means nothing on
its own. Another country could also be 15 above normal, but if *its* typical
swing is 15, that is a Tuesday — `z = 1`. Same gap, completely different
meaning. Dividing asks *is this big **for them***.

## Step 3 — four scores → one score

You do that same sum four times — markets, conflict, disasters, fires. You get
four z-scores. Then just average them:

```
markets   z = 0
conflict  z = 3
disasters z = 1
fires     z = 0

average = (0 + 3 + 1 + 0) ÷ 4 = 1
```

The `0.25 ×` in the code is the ÷ 4. Each of the four counts equally.

## Step 4 — squash it into 0–1

Average z can be anything — could be −6, could be +9. Ugly to display. So
divide **1** by **(1 + e^−z)**. That is the whole thing.

`e` is a fixed constant, 2.718…, like π — nothing to choose. All you need to
know is `e^−z` **shrinks fast** as z grows:

```
z = 0     e^-0 = 1.00     1 ÷ (1 + 1.00) = 1 ÷ 2.00  = 0.50
z = 1     e^-1 = 0.37     1 ÷ (1 + 0.37) = 1 ÷ 1.37  = 0.73
z = 2     e^-2 = 0.14     1 ÷ (1 + 0.14) = 1 ÷ 1.14  = 0.88
z = 3     e^-3 = 0.05     1 ÷ (1 + 0.05) = 1 ÷ 1.05  = 0.95
z = -1    e^1  = 2.72     1 ÷ (1 + 2.72) = 1 ÷ 3.72  = 0.27
```

Normal month → **0.5**. Bad month → toward **1**. Quiet month → toward **0**.
Our example: average z = 1 → score **0.73**.

It can never leave 0–1: the bottom of the fraction is always more than 1, so
the answer is always under 1.

**One catch.** By z = 3 the shrinking number is already 0.05; at z = 5 it is
0.007. Both are nearly nothing, so the scores land at 0.95 and 0.99. A disaster
and a much worse disaster look the same. That is the price of a tidy 0-to-1
number.

## Whole thing in one breath

> Take a country's last 12 months. Work out its normal and its wobble. Ask how
> many wobbles off normal this month is. Do that for four topics, average the
> four, squash to 0–1.

---

<a href="#ch-14">▲ top of §14</a> <sub>(click the heading there to fold it)</sub> &nbsp;·&nbsp; <a href="#map-14">↑ back to §14 in the diagram</a>

</details>

<details id="ch-15">
<summary><b>§15 &nbsp; CII</b> &nbsp;—&nbsp; a same-day stress score: fixed country baseline plus today's events</summary>
<br>

**`app/cii/`** — CII is the **Country Instability Index**.

One number per country per day, 0 to 1: **how stressed is this country
today?** It reads the last 24 hours and runs every hour.

## The formula

```python
CII = 0.40 * baseline + 0.60 * event_score
```

The two numbers add to 1.00, so read them as a percentage split of the
answer: **40% is what kind of country this is in general, 60% is what
happened there today.**

Where does 0.40 come from? Nowhere. It is a dial typed into the code, not a
number that fell out of a fit. Here is what turning it does — same country,
same busy day:

```
split        busy day    dead-quiet day
0.0 / 1.0      0.72          0.00      ← today only, the table ignored
0.4 / 0.6      0.61          0.18      ← what the code uses
0.9 / 0.1      0.49          0.41      ← barely reacts to events at all
```

The right column is the **floor**: with nothing happening, the score is just
`baseline_weight × baseline ÷ 100`. Turn the dial up and every country sits
near its typed-in number whatever the day brings; turn it to 0 and a country
with a violent decade behind it reads like a calm one on its first quiet day.
0.40 splits the difference — a judgement, not a measurement.

Two halves, then. **baseline** is a hand-typed number per country that never
changes and was never measured:

```
UA 46    SY 48    PK 42    US 18    GB 14    everyone else 15
```

**event_score** is today — four counts from the last 24 hours, weighted:

| part | what it counts | weight |
|---|---|---|
| unrest | serious news rows | 0.25 |
| conflict | GDELT fight / attack events | 0.30 |
| security | big quakes, hazard alerts | 0.20 |
| information | how much news there was at all | 0.25 |

Each is squashed to 0–100 with a log, so one huge count cannot drown the
other three. Then a per-country multiplier is applied (UA ×1.25, US ×0.60) —
200 news rows is a quiet day in the US, not stress.

## A real output

One country, one day, straight out of the scoring module:

```json
{
  "baseline":    46.0,
  "unrest":      88.8,
  "conflict":    69.9,
  "security":    30.0,
  "information": 90.6,
  "event_score": 71.82,
  "total":       0.61,
  "multiplier":  1.25
}
```

Read it bottom-up. The four parts came out at 88.8, 69.9, 30.0 and 90.6.
Weight and add them:

```
0.25(88.8) + 0.30(69.9) + 0.20(30.0) + 0.25(90.6) = 71.82   ← event_score
```

Then blend that with the country's fixed 46, and divide by 100 to land in
0–1:

```
0.40(46) + 0.60(71.82) = 61.49   →   ÷ 100   →   0.61   ← total
```

## §14 and §15 side by side

| | §14 composite | §15 CII |
|---|---|---|
| asks | unusual **for this country**? | bad **today**? |
| window | 1 month | 24 hours |
| needs history | 12 months | none |
| runs live | no | yes |

## What that 0.61 does not tell you

**A country cannot score low.** Its floor of 0.184 is sitting there before
any event arrives, so part of what this number measures is **the baseline
table, not the world**.

Nothing in it is fitted — baselines, multipliers and both sets of weights are
typed by hand — and it appears in no accuracy test in Part III. §14 is a
measured instrument that cannot run live; CII is a live instrument that has
never been checked.

---

<a href="#ch-15">▲ top of §15</a> <sub>(click the heading there to fold it)</sub> &nbsp;·&nbsp; <a href="#map-15">↑ back to §15 in the diagram</a>

</details>
