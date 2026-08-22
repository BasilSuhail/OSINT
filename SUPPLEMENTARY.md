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
   │ <a id="map-3" href="#ch-3">§3  THE SOURCES</a>                                                        │
   │    67 places data comes from — 14 public APIs, 53 news sites           │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ <a id="map-4" href="#ch-4">§4  THE REST GATE</a>                                                      │
   │    a source that keeps failing is left alone for a while               │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ <a id="map-5" href="#ch-5">§5  FETCH</a>                                                              │
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
which is what makes the map in §29 update without a reload.

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
| `acled` | recorded conflict events | `acleddata.com/api/acled/read`, or local `.csv`/`.xlsx` | 24/day | composite → geopolitical · **labels §24** |
| `usgs-quake` | earthquakes | `earthquake.usgs.gov/.../4.5_day.geojson` | 96/day | composite → hazard · CII |
| `gdacs` | cyclone, flood, drought alerts | `gdacs.org/xml/rss.xml` | 96/day | composite → hazard · CII |
| `eonet` | ongoing natural events | `eonet.gsfc.nasa.gov/api/v3/events` | 48/day | composite → hazard · CII |
| `emdat` | historical disaster archive | a local file, `EMDAT_CSV_PATH` | 1/day | composite → hazard |
| `nasa-firms` | satellite fire detections | `firms.modaps.eosdis.nasa.gov/api/area/csv/` | 24/day | composite → wildfire |
| `uk-police` | recorded crimes, 6 UK cities | `data.police.uk/api` | 1/day | CII only |
| 53 news sites | headlines | each site's RSS URL, one entry per site in `rss_feeds.json`:<br><br>`{`<br>&nbsp;&nbsp;`"source": "rss-bbc-world",`<br>&nbsp;&nbsp;`"url": "https://feeds.bbci.co.uk/news/world/rss.xml",`<br>&nbsp;&nbsp;`"pretty_name": "BBC World",`<br>&nbsp;&nbsp;`"cadence_min": 60,`<br>&nbsp;&nbsp;`"owner": "bbc",`<br>&nbsp;&nbsp;`"country": "GB",`<br>&nbsp;&nbsp;`"class": "mainstream"`<br>`}` | 24/day each | CII · §17 · §19 · §21 |
| `opensky-adsb` | aircraft positions | `opensky-network.org/api/states/all` | 24/day | **nothing scored** — map only |
| `abuse-ch-urlhaus` | malicious URLs | `urlhaus.abuse.ch/downloads/csv_recent/` | 96/day | **nothing scored** — map only |
| `abuse-ch-feodo` | botnet servers | `feodotracker.abuse.ch/downloads/ipblocklist.csv` | 96/day | **nothing scored** — map only |
| `polymarket` | prediction-market odds | `gamma-api.polymarket.com/markets` | 48/day | **nothing scored** — map only |

Two things fall out of the last column.

**Four sources feed no score at all.** Aircraft, two cyber feeds and prediction
markets are collected, stored and drawn on the map, and no number in this
project depends on them.

**News does not enter the composite index.** News rows are stored with category
`NEWS`, and the composite only reads `market`, `geopolitical` and `hazard`. So
the 53 news sites — half of all traffic in §2's fast tray — feed the story and
disagreement work, and the CII, but **not the score that gets tested in §26.**

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

So when §19 reports how differently countries word a story, it is in practice
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

67 sources publish 67 different formats — CSV, GeoJSON, RSS, XML, JSON. Every
one is converted into the same row before it goes anywhere:

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

Three choices in that shape do real work later:

| Field | Why |
| --- | --- |
| `occurred_at` **and** `fetched_at` | the gap between them is reporting delay, which §3 showed is not evenly distributed. Collapse them into one column and that bias becomes unmeasurable. |
| `country`, `lat`, `lon` nullable | *unknown* is a valid answer. Filling a guess in here would make every downstream count wrong in a way nobody could see. |
| `payload` keeps the raw record | the conversion is never the only copy. Anything dropped by mistake can be recovered without re-fetching. |

`severity` is **not** comparable across sources. A 0.8 earthquake and a 0.8
headline share a scale name and nothing else.

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

The middle one is deliberately **not re-raised for retry**. Five automatic
retries against a URL that just answered `403` is five more wasted requests,
which is how one dead feed cost 420 in a week.

## Nothing changed vs nothing there

A source can answer correctly and hand back an empty list. Two very different
reasons for that:

- the source genuinely has no new records
- the fetcher checked and the file is byte-identical to last time

An empty list alone cannot tell them apart, so a fetcher that *knows* it is the
second case says so:

```python
FetchBatch(events=[], unchanged=True)
```

That distinction is what stops a healthy static source being counted as a
failure in §10.

---

<a href="#ch-5">▲ top of §5</a> <sub>(click the heading there to fold it)</sub> &nbsp;·&nbsp; <a href="#map-5">↑ back to §5 in the diagram</a>

</details>
