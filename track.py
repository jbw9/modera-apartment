#!/usr/bin/env python3
"""Snapshot Modera Northgate's listed units and flag the ones that were held back.

The website, its SightMap unit map and its leasing chatbot all read the same
Entrata "available" list (41 of 409 units on 2026-11-11). On any single day a
vacant unit being held back looks exactly like a leased one; only history
separates them. Run this once a day.

    python3 track.py                # fetch today's list, save it, print the report
    python3 track.py sightmap.json  # same, from the API JSON saved in a browser
"""
import json
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

API = "https://sightmap.com/app/api/v1/8epmlg44v6d/sightmaps/70048"
SNAPSHOTS = Path(__file__).resolve().parent / "snapshots"
SITE = Path(__file__).resolve().parent / "site"
BEDS = {0: "studio", 1: "1 bed", 2: "2 bed", 3: "3 bed"}


def fetch(path=None):
    if path:
        raw = json.loads(Path(path).read_text())
    else:
        req = urllib.request.Request(API, headers={"User-Agent": "modera-unit-tracker"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.load(resp)
    data = raw["data"]
    plans = {}
    for p in data["floor_plans"]:
        name = p["name"]
        try:  # SightMap sends names as JSON text: {"name": "A08", "provider_id": ...}
            name = json.loads(name)["name"]
        except (ValueError, TypeError, KeyError):
            pass
        plans[p["id"]] = (name.strip(), p["bedroom_count"])
    units = {}
    for u in sorted(data["units"], key=lambda u: (len(u["unit_number"]), u["unit_number"])):
        plan, beds = plans[u["floor_plan_id"]]
        units[u["unit_number"]] = {"plan": plan, "beds": beds, "sqft": u["area"],
                                   "price": u["price"], "available_on": u["available_on"]}
    return units


def line(unit, info):
    return f"  {unit:>4}  {info['plan']:<32} ${info['price']:,.0f}  available {info['available_on']}"


def analyze(history):
    dates = [d for d, _ in history]
    position = {d: i for i, d in enumerate(dates)}
    current = history[-1][1]

    listings = {}  # unit -> [(date, info)] for every snapshot it was listed in
    for d, units in history:
        for unit, info in units.items():
            listings.setdefault(unit, []).append((d, info))

    plans_left = {}  # date -> plans of units that disappeared that day
    for (_, before), (d, after) in zip(history, history[1:]):
        plans_left[d] = {before[u]["plan"] for u in before.keys() - after.keys()}

    relisted, ready_on_release, gone = [], [], []
    for unit, rows in listings.items():
        for (d0, a), (d1, b) in zip(rows, rows[1:]):
            if position[d1] - position[d0] > 1:
                relisted.append({"unit": unit, **b, "gone_after": d0, "back": d1, "old_price": a["price"]})
        d, info = rows[0]
        if d != dates[0] and info["available_on"] <= str(date.fromisoformat(d) + timedelta(days=1)):
            ready_on_release.append({"unit": unit, **info, "first_listed": d,
                                     "replaced_same_plan": info["plan"] in plans_left.get(d, ())})
        if unit not in current:
            gone.append({"unit": unit, **rows[-1][1], "last_listed": rows[-1][0]})
    return {"relisted": relisted, "ready_on_release": ready_on_release, "gone": gone}


def report(history, flags):
    dates = [d for d, _ in history]
    today, current = history[-1]
    relisted = [f"{line(f['unit'], f)}  (gone after {f['gone_after']}, back {f['back']}, was ${f['old_price']:,.0f})"
                for f in flags["relisted"]]
    ready_on_release = [f"{line(f['unit'], f)}  (first listed {f['first_listed']}"
                        + (", same day a unit of this plan left" if f["replaced_same_plan"] else "") + ")"
                        for f in flags["ready_on_release"]]
    gone = [f"{line(f['unit'], f)}  (last listed {f['last_listed']})" for f in flags["gone"]]

    by_beds = {}
    for info in current.values():
        by_beds[info["beds"]] = by_beds.get(info["beds"], 0) + 1
    print(f"Modera Northgate, {today} ({len(dates)} snapshots since {dates[0]})")
    print(f"Listed now: {len(current)} units ("
          + ", ".join(f"{BEDS.get(b, b)} {n}" for b, n in sorted(by_beds.items())) + ")")
    if len(history) > 1:
        prev_date, previous = history[-2]
        print(f"\nSince {prev_date}:")
        for u in current.keys() - previous.keys():
            print("+" + line(u, current[u])[1:])
        for u in previous.keys() - current.keys():
            print("-" + line(u, previous[u])[1:])

    for title, rows in [
        ("PULLED, THEN RE-LISTED (wasn't leased: held back or a lease fell through)", relisted),
        ("RELEASED ALREADY MOVE-IN READY (was probably vacant before it was shown)", ready_on_release),
        ("NO LONGER LISTED (probably leased, unless it comes back)", gone),
    ]:
        print(f"\n{title}: {len(rows)}")
        print("\n".join(rows) or "  none yet")


def main():
    units = fetch(sys.argv[1] if len(sys.argv) > 1 else None)
    SNAPSHOTS.mkdir(exist_ok=True)
    (SNAPSHOTS / f"{date.today()}.json").write_text(json.dumps({"units": units}, indent=1))
    history = [(p.stem, json.loads(p.read_text())["units"]) for p in sorted(SNAPSHOTS.glob("*.json"))]
    flags = analyze(history)
    SITE.mkdir(exist_ok=True)
    (SITE / "history.json").write_text(json.dumps({"snapshots": dict(history), "flags": flags}))
    report(history, flags)


if __name__ == "__main__":
    main()
