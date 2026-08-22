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
   │ §3  THE SOURCES                                                        │
   │    67 places data comes from — 14 public APIs, 53 news sites           │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §4  THE REST GATE                                                      │
   │    a source that keeps failing is left alone for a while               │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §5  FETCH                                                              │
   │    download only — no database, no scoring, no side effects            │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §6  INLINE ENRICHMENT                                                  │
   │    headlines get translated, placed on a map, read for tone            │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §7  PUBLICATION-TIME REPAIR                                            │
   │    nothing may claim it happened in the future                         │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §8  FRESHNESS GATE                                                     │
   │    rows too old for the live window are counted and dropped            │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §9  UPSERT AND DEDUP                                                   │
   │    one row per source event — re-fetching updates, never doubles       │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §10  OUTCOME CLASSIFICATION                                            │
   │    a fetch returning nothing usable is not a success                   │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §11  THE FAILURE LEDGER                                                │
   │    every failure, quarantine and silent source is recorded             │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §12  events                                                            │
   │    the one table every source writes into, whatever it measured        │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §13  POST-INGEST ENRICHMENT                                            │
   │    hazard outlines, place names and severity added afterwards          │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §14  RETENTION AND CAP                                                 │
   │    rows older than ~30 days are deleted; 30 GB hard ceiling            │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼

═══════════════════════════ PART II — ANALYSIS ═══════════════════════════

   ┌────────────────────────────────────────────────────────────────────────┐
   │ §15  THE COMPOSITE INDEX                                               │
   │    four domains, z-scored against a country's own past, into one score │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §16  CII                                                               │
   │    a same-day stress score: fixed country baseline plus today's events │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §17  STORIES                                                           │
   │    headlines about the same event grouped by word overlap              │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §18  CORROBORATION + SENSOR CHECKS                                     │
   │    how many independent owners tell it, and whether a sensor agrees    │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §19  DISAGREEMENT                                                      │
   │    how differently countries word the same story                       │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §20  VALIDATOR                                                         │
   │    a local model extracts the factual claims a story makes             │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §21  SEVERITY GRADING                                                  │
   │    how much harm to people a headline reports                          │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §22  THE BRAIN                                                         │
   │    a local model summarises stored rows and answers questions on them  │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §23  THE PREDICTION JOURNAL                                            │
   │    forecasts written down before the outcome, never rewritten          │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼

═════════════════════ PART III — OFFLINE EVALUATION ═════════════════════

   ┌────────────────────────────────────────────────────────────────────────┐
   │ §24  GROUND TRUTH                                                      │
   │    conflict records become the labels, in a table of their own         │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §25  THE PANEL                                                         │
   │    one row per country per month — 31,637 of them                      │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §26  THE EXAMS                                                         │
   │    the score against six baselines; the verdict is computed, not read  │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §27  HUMAN AUDIT SHEETS                                                │
   │    a person hand-checks a sample of every model output                 │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼

═══════════════════════════ PART IV — SERVING ═══════════════════════════

   ┌────────────────────────────────────────────────────────────────────────┐
   │ §28  THE API                                                           │
   │    31 endpoints — the only way anything leaves the database            │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ §29  THE CONSOLE                                                       │
   │    map, panels and a live stream of arriving rows                      │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼

════════════════════════ PART V — WHAT COMES OUT ════════════════════════

   ┌────────────────────────────────────────────────────────────────────────┐
   │ §30  THE ARTEFACTS                                                     │
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
| A job fails every run | the scheduler neither knows nor cares; the watchdog in §11 is what catches it |

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

<a href="#ch-1">▲ collapse §1</a> &nbsp;·&nbsp; <a href="#map-1">↑ back to §1 in the diagram</a>

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
queue.

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
<summary><b>The failure this design already had</b></summary>
<br>

The worker names its queue explicitly:

```
["celery", "-A", "app.celery_app", "worker", "-Q", "celery", ...]
```

Before that `-Q` was written, the worker took only the default queue, **nothing
consumed `analytics` at all**, and every heavy job was published into a mailbox
no one emptied.

Nothing raised an error. The scheduler published correctly. Redis accepted the
notes correctly. The jobs simply never ran — the same shape as §1's dead
scheduler: **silence is not distinguishable from health.** A queue with no
consumer looks exactly like a queue with nothing to do.

</details>

<details>
<summary><b>What else Redis does here</b></summary>
<br>

Three jobs, not one:

1. **The queue** — notes waiting for a worker.
2. **The results store** — where a finished job leaves its answer.
3. **A broadcast channel** — when new rows land, a message is published on
   `events:new`, and the console (§29) is listening. That is what makes the map
   update without the page being reloaded.

</details>


---

<a href="#ch-2">▲ collapse §2</a> &nbsp;·&nbsp; <a href="#map-2">↑ back to §2 in the diagram</a>

</details>
