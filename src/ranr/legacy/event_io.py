"""One validated ledger reader for historical GAMA evaluation workflows."""

import csv
from pathlib import Path


def rows(path):
    with Path(path).open() as source:
        return list(csv.DictReader(source))


def event_ledger(records, request_ids=None):
    sessions = {}
    for row in records:
        rid = row["request_id"]
        if request_ids is not None and rid not in request_ids:
            continue
        events = sessions.setdefault(rid, {})
        kind = row["event"]
        if kind != "deferred" and kind in events:
            raise ValueError(f"Duplicate {kind} for {rid}")
        events[kind] = row
    return sessions
