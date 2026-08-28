#!/usr/bin/env python3
"""build_presence.py — Article XXIV (Static Data Covenant, kody-w/RAR CONSTITUTION.md).

Harvests recent repository events, once, here in CI, and writes
state/presence.json: a list of {created_at, actor: {login}} — the two fields
index.html's live-presence banner reads out of a GitHub events-API response —
trimmed from the full event objects (payload, org, repo, etc. are not needed).

Replaces: index.html's per-visitor, unauthenticated
`fetch("https://api.github.com/repos/<slug>/events?per_page=50")`.

CAUTION (see agent flags): this repo's main branch is guarded by a hardened,
audited protected-push mechanism (see .github/workflows/submissions-index.yml)
that a plain `git push` from a new scheduled workflow will likely not satisfy.
This script produces the static snapshot; wiring a workflow that refreshes it
on a schedule was deliberately left undone pending a decision on how to land
commits against that protection (see the migration flags for this repo).
"""

import datetime
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "state" / "presence.json"
SLUG = "kody-w/public-art-collective"


def main():
    req = urllib.request.Request(
        f"https://api.github.com/repos/{SLUG}/events?per_page=50",
        headers={"User-Agent": "public-art-collective-build", "Accept": "application/vnd.github+json"},
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            events = json.loads(r.read())
    except Exception as e:
        print(f"  ! events fetch failed: {e}", file=sys.stderr)
        return 1

    slim = [
        {"created_at": e.get("created_at"), "actor": {"login": (e.get("actor") or {}).get("login")}}
        for e in events
        if isinstance(e, dict)
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "schema": "public-art-collective-presence/1",
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "events": slim,
    }, indent=2, sort_keys=True) + "\n")
    print(f"✓ {OUT.relative_to(ROOT)} — {len(slim)} events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
