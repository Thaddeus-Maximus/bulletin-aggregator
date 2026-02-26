# Parish Bulletin Aggregator

> If you want to know what's going on, the ground truth is the bulletin.

# Parishes
- HSPHT
- EPI
- SMB
- MHE
- OLOP

# Churches

### Core
- <span style="color:#0f902f">HSP</span>
- <span style="color:#1e90ff">HT</span>
- <span style="color:#f8c325">EPI</span>
- <span style="color:#255cf8">SMB</span>
- <span style="color:#60ffc2">MERNA</span>
- <span style="color:#ff8082">SMD</span>

### Fringes
- <span style="color:#8fff1e">SPW</span>
- <span style="color:#422cf1">SJC</span>
- <span style="color:#db25f8">SHFC</span>
- <span style="color:#a79358">SME</span>
- <span style="color:#ff00c3">ATL</span>
- <span style="color:#5448b7">LINC</span>
- <span style="color:#dff3ff">LEX</span>
- <span style="color:#b8b8b8">HOP</span>
- <span style="color:#454545">DEL</span>

# Workflow

## 1. Scrape PDFs

PDFs can be gathered from:
- https://parishesonline.com/organization/epiphany-church
- https://discovermass.com/church/st-patrick-bloomington-il/#bulletins
- https://discovermass.com/church/st-patrick-church-of-merna-bloomington-il/#bulletins
- https://discovermass.com/church/st-mary-bloomington-il/#bulletins

For each source, download every bulletin published after the last collected date for that source. Collect at this stage:
- the URL the bulletin can be accessed from
- the date of the bulletin

The last-collected date is tracked **per source** and stored in the persistent JSON store (see below).

Each source may require its own scraping logic, as site structures differ. This step is done purely with a Python script.

## 2. Process PDFs

PDFs are fed into Claude (via the CLI or GUI) with instructions to generate a structured list of all events found in the bulletin. Each event object should have:

- `location`
- `datetime` (a singular machine-parsable datetime used to place it on the calendar)
- `time_desc` (a human-readable description of the time, e.g. `February 6, 6–9 PM`; some events may have irregular descriptions)
- `details` (the details of the event as listed in the bulletin; mass intentions or other notes go here)
- `source` (the parish code that was scraped, e.g. `hsp` or `epi`)
- `bulletin_url` (the URL of the bulletin this was found in)
- `bulletin_page` (the page number of the bulletin this was found in, as an integer)
- `id` (not populated at this stage; will be assigned during the merge step)
- `type` (`misc`, `mass`, `adoration`, or `confession`)
- `cancelled` (boolean; `true` only if the bulletin explicitly states the event is cancelled)

### Rules for generating events

- Masses, adoration, and confession are often listed as recurring schedules (e.g. "Sundays at 9am"). Generate individual event objects for each occurrence up to **`weeks_ahead` weeks** from the bulletin date (default: 2). Do not speculatively generate events beyond that window.
- If a time description is abstract or irregular (e.g. "First Friday of the month"), generate occurrences up to **2 months ahead**.
- If an event is simply not mentioned in a bulletin, do not mark it as cancelled — silence is not cancellation.
- `id` is left null/empty at this stage.

The output is a JSON array of event objects.

## 3. Propose Diff

An LLM (via CLI) is given the current event store and the newly extracted events from Step 2. It produces a **proposed diff** — a structured JSON document describing what should change:

- **Add** events that are new
- **Cancel** events that are explicitly marked cancelled in the bulletin (set `cancelled: true`)
- **Merge/update** events that appear to be the same (same type, time, and location) with any new or additional detail
- **Remove** events whose `datetime` has already passed (day-of counts as past)

The LLM does **not** directly modify the data store. It outputs only a proposal. This step produces a file that can be reviewed before anything is committed.

## 4. Enact Diff

A deterministic Python script reads the proposed diff from Step 3 and applies it to the JSON store. This script:

- Validates the structure and types of the diff
- Assigns `id`s to new events — always incrementing from the stored `next_id`, never reused
- Applies updates, cancellations, and removals as specified
- Persists the updated store

This separation keeps the LLM's role confined to reasoning and proposal. All data mutation is done by code that can be inspected and is fully deterministic.

## 5. Publish through Hugo

A Python script generates Hugo content from the event store. The site:

- Has a page for each event type: `misc` (general events), `mass`, `adoration`, `confession`
- Lists events in chronological order by `datetime`
- Shows `location`, `time_desc`, and `details` for each event
- Clearly indicates cancelled events
- Includes a **proof link** labeled `P{page}` (e.g. `P5`) that links to `bulletin_url#page={bulletin_page}`
- Includes a detail link to `/event/{id}`
- Generates an individual page for each event at `/event/{id}`

This step is done purely with a Python script.

---

# Persistent Data Store

All state is stored in a single JSON file. Top-level structure:

```json
{
  "sources": {
    "<source_id>": {
      "last_collected": "YYYY-MM-DD"
    }
  },
  "next_id": 1,
  "events": []
}
```

`next_id` is the next integer to use when assigning an event `id`. It only ever increases.

---

# Configuration

| Parameter | Description | Default |
|---|---|---|
| `weeks_ahead` | How far ahead to generate recurring events (masses, etc.) | `2` |

---

# Decisions & Paths Not Taken

## Claude API vs. CLI

**Chose CLI.** Using the Claude CLI or GUI avoids managing API keys in code and keeps the barrier to run the pipeline low. Steps 2 and 3 are interactive rather than fully automated as a result. This can be revisited later.

## Database vs. JSON

**Chose JSON.** SQLite or a proper database would handle scale, indexing, and concurrency better. For a small number of events across a handful of parishes, a flat JSON file is simpler, human-readable, and git-friendly. Git history serves as the backup and audit trail.

## Automated scheduling vs. manual triggering

**Chose manual.** A cron job or GitHub Actions workflow would be more convenient but adds infrastructure overhead. Running the pipeline manually on demand is sufficient for now.

## LLM directly mutating the store vs. diff + deterministic enactment

**Chose diff + enact.** Allowing an LLM to directly write to the data store is risky — non-deterministic output could silently corrupt data. Instead, the LLM produces a structured proposal, and a deterministic Python script enacts it. This makes the LLM's decisions reviewable before they are committed, and keeps validation logic in code.

## Archiving past events vs. deletion

**Chose deletion.** Past events are removed from the store on the day they occur. The data store is in git, so any prior state is recoverable from history. The `bulletin_url` proof links also point back to the original source PDFs for reference.
