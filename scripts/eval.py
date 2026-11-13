"""Manual cluster-precision evaluation.

Samples events (default 50) and asks you, one event at a time, whether every
headline in it is about the same thing. Labels are saved after each answer, so
you can quit and resume. At the end (or with --report) it prints:

  event precision    share of events whose members ALL belong together
  article precision  share of sampled articles that belong to their event

Singleton events cannot be wrong, so by default only events with 2+ articles are
sampled; pass --include-singletons to sample from all events.

    .venv/bin/python scripts/eval.py                  # label a new sample of 50
    .venv/bin/python scripts/eval.py --resume         # continue the latest sample
    .venv/bin/python scripts/eval.py --report         # report on the latest sample
    .venv/bin/python scripts/eval.py --n 30 --seed 7
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import db_path, scoring  # noqa: E402

EVAL_DIR = ROOT / "data" / "eval"


def sample(conn: sqlite3.Connection, n: int, seed: int, include_singletons: bool) -> list[dict]:
    min_articles = 1 if include_singletons else 2
    events = conn.execute(
        "SELECT e.id, e.story_id FROM events e WHERE (SELECT COUNT(*) FROM articles a WHERE a.event_id = e.id) >= ?",
        (min_articles,),
    ).fetchall()
    rng = random.Random(seed)
    picked = rng.sample(events, min(n, len(events)))
    out = []
    for e in picked:
        arts = conn.execute(
            "SELECT id, publisher, title, published_at FROM articles WHERE event_id=? ORDER BY published_at",
            (e["id"],),
        ).fetchall()
        out.append({"event_id": e["id"], "story_id": e["story_id"], "articles": [dict(a) for a in arts]})
    return out


def latest_file() -> Path | None:
    files = sorted(EVAL_DIR.glob("sample_*.json"))
    return files[-1] if files else None


def save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False))


def ask(ev: dict, i: int, total: int) -> dict | None:
    """Returns a label dict, {} to skip, or None to quit."""
    print(f"\n[{i}/{total}] event {ev['event_id']}" + (f"  (part of story {ev['story_id']})" if ev["story_id"] else ""))
    for k, a in enumerate(ev["articles"], 1):
        print(f"  {k:>2}. {a['publisher'][:18]:18}  {a['title'][:100]}")
    while True:
        try:
            ans = input("All the same event? [Enter/y = yes, n = no, s = skip, q = quit] ").strip().lower()
        except EOFError:
            return None
        if ans in ("", "y", "yes"):
            return {"correct": True, "wrong": []}
        if ans == "s":
            return {}
        if ans == "q":
            return None
        if ans in ("n", "no"):
            try:
                raw = input("  Numbers of the articles that do NOT belong (e.g. 2,5): ").replace(" ", "")
            except EOFError:
                return None
            try:
                wrong = sorted({int(x) for x in raw.split(",") if x})
            except ValueError:
                print("  Please enter numbers separated by commas.")
                continue
            if not wrong or any(w < 1 or w > len(ev["articles"]) for w in wrong):
                print(f"  Enter one or more numbers between 1 and {len(ev['articles'])}.")
                continue
            if len(wrong) == len(ev["articles"]):
                print("  At least one article must define the event; mark the odd ones out.")
                continue
            return {"correct": False, "wrong": wrong}


def report(data: dict) -> None:
    labelled = [e for e in data["events"] if e.get("label")]
    if not labelled:
        print("No labels yet.")
        return
    n_ev = len(labelled)
    ok = sum(e["label"]["correct"] for e in labelled)
    n_art = sum(len(e["articles"]) for e in labelled)
    wrong = sum(len(e["label"]["wrong"]) for e in labelled)
    print(f"\nSample: {data['created_at']}  threshold {data['cluster_threshold']}  seed {data['seed']}")
    print(f"Labelled {n_ev} of {len(data['events'])} events ({n_art} articles)")
    print(f"  Event precision:   {ok}/{n_ev} = {ok / n_ev:.1%}")
    print(f"  Article precision: {n_art - wrong}/{n_art} = {(n_art - wrong) / n_art:.1%}")
    bad = [e for e in labelled if not e["label"]["correct"]]
    if bad:
        print("\nImpure events:")
        for e in bad:
            print(f"  event {e['event_id']}:")
            for k in e["label"]["wrong"]:
                print(f"     x {e['articles'][k - 1]['title'][:90]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--include-singletons", action="store_true")
    ap.add_argument("--resume", action="store_true", help="continue labelling the latest sample")
    ap.add_argument("--report", action="store_true", help="only print the report for the latest sample")
    a = ap.parse_args()

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    if a.report or a.resume:
        path = latest_file()
        if not path:
            print("No saved sample. Run without --report/--resume first.")
            return 1
        data = json.loads(path.read_text())
        if a.report:
            report(data)
            return 0
    else:
        conn = sqlite3.connect(db_path())
        conn.row_factory = sqlite3.Row
        seed = a.seed if a.seed is not None else random.randrange(10**6)
        events = sample(conn, a.n, seed, a.include_singletons)
        if not events:
            print("No events to sample. Run the pipeline first.")
            return 1
        now = datetime.now(timezone.utc)
        path = EVAL_DIR / f"sample_{now:%Y%m%d_%H%M%S}.json"
        data = {"created_at": now.isoformat(timespec="seconds"), "seed": seed,
                "cluster_threshold": scoring()["cluster_threshold"], "events": events}
        save(path, data)
        print(f"Sampled {len(events)} events (seed {seed}) -> {path.relative_to(ROOT)}")

    todo = [e for e in data["events"] if "label" not in e]
    done = len(data["events"]) - len(todo)
    for i, ev in enumerate(todo, done + 1):
        label = ask(ev, i, len(data["events"]))
        if label is None:
            print("Saved. Resume with: .venv/bin/python scripts/eval.py --resume")
            break
        if label:
            ev["label"] = label
            save(path, data)
    report(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
