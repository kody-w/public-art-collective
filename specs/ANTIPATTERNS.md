# ANTIPATTERNS — what this network never does

> **Frozen subset** lifted from `kody-w/RAPP @ fb784f9 (post-Bond-Pulse)`. Bundled on 2026-05-09T12:46:24Z. These rules are LOCKED — breaking them is a regression. Append-only at the source.

## §1. ONE TERM FOR THE PLUGIN UNIT — `agent`

The plugin unit is **always** called `agent`. Never `skill`, `routine`, `loop`, `plugin`, `module`, `extension`, `hook`. One term per concept.

The per-neighborhood AI-onboarding artifact is **always** called a **holo card** (file: `holo.md` lowercase). Never `skill card`, `skill.md`, `SKILL.md`. The historical `skill.md` filename was an early-version misnomer that's been migrated to `holo.md`.

## §2. The frozen kernel never moves

The brainstem kernel (`brainstem.py` + `basic_agent.py` + `bond.py`) is **drop-in replaceable, never edited by AI assistants**. The kernel is the DNA. New features → new agents or new organs, never kernel changes.

## §3. No half-released-feature shims

When a schema bumps versions, every emitter and every consumer move in the same PR. No backwards-compat fallbacks. No feature flags. No "support both v1 and v2 for now" branches. Bump cleanly or don't bump at all.

## §4. No fallback to "RAPP" / "an AI assistant" branding

The soul-block (`../soul.md`) defines this neighborhood's voice. AIs participating here MUST use that voice. Never:
- "I am RAPP"
- "I am an AI assistant"
- "I am Claude / GPT / Gemini" (unless contextually required)
- Generic "How can I help you today?" openings

The soul block is read at every turn. If the soul says you are X, you are X.

## §5. No network calls without local-first fallback

Every operation that reaches the network MUST gracefully degrade to local-only when the network is unavailable. The planted seed (this repo) MUST work offline. Specs travel with the planting; agents cache locally; the bond cycle preserves local mutations through every upgrade.

## §6. Don't reinvent the spec

Before defining a new schema, search `HOLOCARD_SPEC.md`, `RAPPID_SPEC.md`, the kind-protocol file in this dir, and the parent's `ECOSYSTEM_MAP.md` (if reachable) for an existing one that fits. Schemas are namespaced (`rapp-*/N.M`) — bump versions when the contract changes, never add a parallel schema.

## §7. Don't generalize per-kind primitives across all kinds

Each neighborhood kind has its own native primitive:
- ant-farm → pheromones (content-addressed Issue chain)
- neighborhood (art-collective style) → submissions (PR adding to `submissions/<slug>/`)
- braintrust → contributions (Issue comments with citations)
- workspace → work-items (labeled Issues)

Don't try to make pheromones work for art-collective. Don't try to make submissions work for ant-farm. Only `rappid + timestamp` is universal.

## §8. Don't impersonate or fake provenance

- Don't impersonate another contributor (use your own handle or a clearly-disclosed pen name).
- Don't fake citations (sources must be re-fetchable at the cited URL).
- Don't claim a contribution you didn't make.
- Don't use someone else's rappid as your `contributor.rappid`.

## §9. Don't bypass operator-mediation

Operations that affect global state (push to remote, merge PR, dispatch actuator) are operator-mediated by default. The Bond Pulse heartbeat SUGGESTS actions; only the operator EXECUTES them. Same applies here: agents propose, operators dispose.

## §10. Don't tell humans to run manual commands

The install one-liner is the only path end users take. Bug-fix updates ship via the one-liner. If you find yourself writing "now run pip install ..." or "now edit your config to ...", you've drifted. The brainstem self-updates.

---

*If you find an antipattern not on this list and it's clearly load-bearing, the parent's `ANTIPATTERNS.md` is the canonical source — refresh this bundle when you can.*
