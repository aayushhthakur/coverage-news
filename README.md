# Coverage: news ranked by who is reporting it

A working prototype that ranks news **events** (clusters of articles about the same
thing), not individual articles, and shows why each one is ranked where it is.
Phone-first PWA; on desktop the same layout sits in a centred 480px column.

No paid services, no API keys. Embeddings run locally (all-MiniLM-L6-v2).

```
config/      feeds.yaml · taxonomy.yaml · scoring.yaml · images.yaml   ← all tunables live here
backend/     FastAPI app, pipeline, tests
frontend/    React + Vite + Tailwind PWA
scripts/     build_feeds.py (validate feeds) · eval.py (cluster-precision labelling)
data/        news.db (SQLite) · raw/YYYY-MM-DD/*.json (every raw response)
.env         UNSPLASH_ACCESS_KEY (backend only, git-ignored; see .env.example)
```

## Setup

Requires Python 3.11+ and Node 18+. **Run every command from the project root**
(the folder containing `backend/`, `config/` and `frontend/`).

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
npm --prefix frontend install
```

The first pipeline run downloads the embedding model (~90 MB) from Hugging Face; after that it runs offline.

## Run

API (also runs the pipeline at startup and then every 15 minutes):

```bash
.venv/bin/uvicorn app.main:app --app-dir backend --port 8000
```

Web app (dev server, proxies `/api/*` to `:8000`):

```bash
npm --prefix frontend run dev -- --port 5180
```

Open http://localhost:5180. To try it on a phone, open `http://<your-computer's-LAN-IP>:5180` on the same Wi-Fi.

Installable PWA build (service worker is only registered in production builds):

```bash
npm --prefix frontend run build
npm --prefix frontend run preview -- --port 5181
```

Point the frontend at an API elsewhere with `VITE_API_BASE=https://host` at build time.

### Card images (Unsplash)

Put your Unsplash Access Key in `.env` at the project root (backend only, git-ignored):

```
UNSPLASH_ACCESS_KEY=your-access-key
```

Restart the API. Without a key, cards show no image and everything else works.

- Images are **illustrative**, not news photos. Each card gets a photo for its subtopic or topic, using the queries in `config/images.yaml`. Searching stock photos with headline words returns unrelated people and places.
- Photos are hotlinked from Unsplash. Each card is credited "Photo: name / Unsplash" with referral links, and the event screen says "Illustrative photo by…". Each photo's download endpoint is pinged once, as Unsplash's guidelines require.
- Demo keys allow 50 requests/hour, so each run spends at most 10 (`max_requests_per_run`), most visible cards first. Photo pools are cached for 24h. A fresh install needs about 2–3 runs (30–45 min) to fill every card.

### Pipeline by hand

```bash
cd backend && ../.venv/bin/python -m app.pipeline --report     # one full run + all stage reports
cd backend && ../.venv/bin/python -m app.pipeline --rank-only  # print current top 10s, no new run
```

### Tests

```bash
cd backend && ../.venv/bin/python -m pytest -q
```

Covers every scoring formula, distinct-publisher counting, snapshot-based velocity,
each re-ranking rule (one entry per event, 2-per-publisher cap, breaking boost,
clickbait demotion, 3-per-topic home interleave), representative selection,
stories, clickbait rules and every API endpoint.

### Cluster-precision evaluation

```bash
.venv/bin/python scripts/eval.py             # sample 50 multi-article events and label them
.venv/bin/python scripts/eval.py --resume    # continue where you stopped
.venv/bin/python scripts/eval.py --report    # event and article precision for the latest sample
```

### Rebuilding the feed list

```bash
.venv/bin/python scripts/build_feeds.py
```

Fetches every candidate feed, drops ones that fail, are empty or have nothing newer
than 7 days, rewrites `config/feeds.yaml` and prints the list.

## How it works

Every 15 minutes (`backend/app/pipeline.py`):

1. **Ingest**: RSS feeds from `feeds.yaml` plus one GDELT DOC 2.0 query. Raw responses are saved to `data/raw/YYYY-MM-DD/`.
2. **Normalise**: title, short summary (≤280 chars, never full text), publisher, published_at, canonical URL. Drops duplicates by URL and by normalised-title hash, and anything older than the 48h window. GDELT results count as a publisher only if their domain matches a `domains` entry in feeds.yaml.
3. **Classify**: multi-label topic/subtopic by cosine similarity to `taxonomy.yaml` descriptions, plus a small prior for topics the publisher covers.
4. **Cluster**: incremental. Each new article joins the most similar open event (centroid similarity ≥ 0.75, within 48h of its first report) or starts a new one. Event ids are stable across runs.
5. **Stories**: events whose centroids are ≥ 0.65 similar are linked, and outliers are trimmed. Groups of **6 or more** events become a *story* (e.g. every angle of one scandal). A story ranks as one entry and opens to show its sub-events.
6. **Snapshot + score** each event and story, per topic:

   | | |
   |---|---|
   | C = log(1+P) / log(1+N) | P = distinct publishers covering it, N = publishers in feeds.yaml |
   | V = publishers added in the last hour / P | 0 if P < 3; "an hour ago" comes from snapshots |
   | T = Tier 1 publishers covering it / Tier 1 list size for the topic | |
   | S = (0.4C + 0.3V + 0.3T) · 2^(−a/h) | a = hours since latest article; h = 6 Sports, 18 Tech, 24 Geopolitics, 36 Economics |

   Publishers are counted, never articles. If every headline in an event is flagged as clickbait, S × 0.5.
7. **Representative article**: the highest-tier publisher whose headline isn't clickbait, earliest first. For a story, it comes from its best-scoring sub-event.
8. **Write-up** (`backend/app/writeup.py`): each card gets a 60–90 word summary, and each event/story screen a write-up of up to ~1000 words in sections (What happened, Why, Where, Who, When, How it unfolded, What it means for those involved), followed by its sources ranked by how many passages were used. For now this is **extractive**: every passage is a sentence quoted from a publisher's feed summary and credited underneath, picked for the words most widely shared across publishers. Only the "When", "Where" and "Who" lead-ins are generated from metadata. A big story reaches ~1000 words; a small event only has a few hundred words of feed text to draw on. The response shape (`writeup.sections[].blocks[]`, `writeup.sources[]`) is what an LLM writer should return when one is added (`writeup.engine` in `config/scoring.yaml`).
9. **Re-rank** at request time (`backend/app/rank.py`): one entry per event; max 2 representative articles per publisher in a top 10 (switches to the event's next-best publisher before dropping it); breaking boost (under 2h old, V > 0 and in the topic's top 5%) lifts into the top 3 with a tag; home shows at most 3 per topic.

## API

| | |
|---|---|
| `GET /home` | top 10 across topics |
| `GET /topics/{topic}?subtopic=` | top 10 for a topic (`tech` works) or subtopic |
| `GET /events/{id}` | write-up, publishers grouped by tier, report timeline, score breakdown |
| `GET /stories/{id}` | same for a story, plus its sub-events (not shown in the app) |
| `GET /health` | last run, running flag, article/event/story counts, failed feeds |

Every list item carries its `score` block (publishers, added in last hour, Tier 1 n/size, C, V, T, age, decay, S), which is what the "Why this is ranked here" sheet shows.

## Known limitations

- **GDELT rate limit**: GDELT answers HTTP 429 to this network much of the time. It shows in `/health` as a failed source and the app runs on RSS alone.
- **Velocity needs history**: V uses snapshots an hour apart. On a fresh database it falls back to article timestamps until enough runs have accumulated.
- **Classification noise**: embedding similarity to short descriptions mislabels some items (e.g. "trade deadline" → Economics, a rugby listing → Cricket). About 20% of articles match no topic and are not shown.
- **Shopping posts**: Wired's coupon and deal posts are neither news events nor clickbait by the spec's rules, so they can still rank.
- **Extractive write-ups** read as a sequence of quoted sentences, not a written story, and the Who/Where name lists come from capitalisation, so they are sometimes noisy. Swapping in an LLM writer is the planned fix.
- **Story labels** are the most frequent name in the headlines ("Jensen Huang", "Giants"), not a written title.
