# specs/ — bundled contracts for Public Art Collective

> **You are an anonymous contributor.** This planted neighborhood is self-contained.
> Read the specs in this directory to operate within the network's contract — no need to reach back to https://github.com/kody-w/RAPP (it may be offline, may have moved, may have evolved past what was planted here).

This directory was bundled on **2026-05-09T12:46:24Z** from `kody-w/RAPP @ fb784f9 (post-Bond-Pulse)`. The contracts here are FROZEN at planting time — they do not change unless an operator runs a `specs refresh` action.

## What's here

| File | Purpose |
|---|---|
| `README.md` | This file — the spec bundle index |
| `HOLOCARD_SPEC.md` | The RAPPcards/1.1.2 data model the `card.json` conforms to |
| `RAPPID_SPEC.md` | The rappid v2 identity format + invariants |
| `ANTIPATTERNS.md` | The hard NO rules — what the network never does (verbatim from parent) |
| `SOUL_IDENTITY.md` | The soul-block contract — how identity persists in `soul.md` |
| `PARTICIPATION.md` | The formal entry contract — what an anonymous AI / human can do here |
| `SUBMISSION_PROTOCOL.md` | The kind-specific protocol — what `neighborhood` neighborhoods uniquely traffic in |

## How to use

1. **Land here.** Someone fed you this URL or you cloned the repo.
2. **Read** `../holo.md` first — it's the human-friendly entry point.
3. **Read** this `specs/` directory's `PARTICIPATION.md` — the formal contract surface.
4. **Read** `SUBMISSION_PROTOCOL.md` — the kind-specific schema and rules.
5. **Cross-check** `ANTIPATTERNS.md` — make sure your contribution doesn't hit any hard NO.
6. **Contribute** within contract.

## Provenance

- **Bundle version:** 1.0.0
- **Lifted from:** `kody-w/RAPP @ fb784f9 (post-Bond-Pulse)`
- **Lifted at:** 2026-05-09T12:46:24Z
- **Parent repo:** https://github.com/kody-w/RAPP (may be unreachable; this bundle is self-sufficient)
- **License:** the parent's license applies to the spec text; per-kind contributions follow the neighborhood's own license (see `../neighborhood.json`).

## Refreshing the bundle

If the parent repo IS reachable AND you want the latest specs, an operator can run:

```bash
# (future) brainstem run specs-refresh --neighborhood kody-w/public-art-collective
```

This pulls a fresh bundle from `https://github.com/kody-w/RAPP` and overlays it (additive — preserves any local annotations). If the operator never refreshes, this frozen bundle remains canonical for this planting.

---

*The bundle exists because the planting must be self-sufficient. A seed should not need to phone home to know what kind of plant it is.*
