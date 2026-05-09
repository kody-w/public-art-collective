# HOLOCARD_SPEC — RAPPcards/1.1.2 (subset relevant to neighborhood plantings)

> **Frozen excerpt of the canonical spec at `kody-w/RAPPcards/SPEC.md` v1.1.2.**
> Bundled at planting time on 2026-05-09T12:46:24Z. The authoritative source is the parent repo; this is the self-contained subset every planting needs.

## Card data model

A holocard is a JSON object. Required fields are marked ✱. The neighborhood's `../card.json` MUST conform to this shape.

```json
{
  "schema":      "rappcards/1.1.2",   // ✱
  "id":          "@publisher/slug",   // ✱ — matches `../neighborhood.json::name` + the owner of this repo
  "name":        "Display Name",      // ✱
  "title":       "Type line",
  "seed":        "decimal-string",    // ✱ — 64-bit unsigned, BigInt-safe (always a STRING in JSON)
  "incantation": "FORGE ANVIL ...",   // 7-word mnemonic (per §3.2)

  "hp":          120,                 // ✱ — 10–300
  "stats": {                          // ✱ — all four required, 0–255
    "atk": 140, "def":  95,
    "spd":  80, "int": 110
  },

  "agent_types": ["LOGIC","DATA"],    // ✱ — 1–3 entries from {LOGIC, WEALTH, HEAL, CRAFT, SHIELD, SOCIAL, DATA}
  "weakness":    "SHIELD",            // single type
  "resistance":  "WEALTH",            // single type

  "rarity_tier":  "core",             // ✱ — starter | core | rare | mythic
  "rarity_label": "Core",             // human label

  "abilities": [                      // ✱ — 1–4 entries
    {"name": "...", "cost": 1, "damage": 30, "text": "...", "type": "LOGIC"}
  ],
  "retreat_cost": 2,                  // 0–5

  "flavor_text": "...",
  "avatar_svg":  "<svg>...</svg>",    // ≤64 KB

  "meta": {                           // free-form — version, category, license, kind, rappid, gate_url, etc.
    "version": "1.0.0",
    "kind":    "neighborhood",
    "rappid":  "<this neighborhood's rappid>",
    "license": "..."
  }
}
```

## Type system (§2.1)

Seven agent_types, directed attack cycle:

```
LOGIC → WEALTH → HEAL → CRAFT → SHIELD → SOCIAL → DATA → LOGIC
```

X → Y means X is strong against Y (×2 damage). Y resists X by one step in reverse.

| Type   | Color   | Domain             |
|--------|---------|--------------------|
| LOGIC  | #58a6ff | Reason             |
| DATA   | #3fb950 | Memory             |
| SOCIAL | #bc8cff | Empathy            |
| SHIELD | #d29922 | Defense            |
| CRAFT  | #ff7b72 | Making             |
| HEAL   | #7ee787 | Support            |
| WEALTH | #ffd480 | Economy            |

## Rarity tiers (§2.2)

| `rarity_tier` | `rarity_label` | `meta.quality_tier` |
|---|---|---|
| `starter` | Starter | `experimental` |
| `core`    | Core    | `community`    |
| `rare`    | Elite   | `verified`     |
| `mythic`  | Legendary | `official`   |

## Seed derivation (§3.1)

```python
import hashlib
def canonical_seed(source_bytes: bytes) -> int:
    h = hashlib.blake2b(source_bytes, digest_size=8)
    return int.from_bytes(h.digest(), 'big')
```

For a neighborhood, `source_bytes` = the rappid string (utf-8 encoded). The seed is **derived**, not chosen. Two different inputs have ~2⁻³² collision probability.

## Mnemonic incantation (§3.2)

7 words from a frozen 1024-word list (10 bits/word × 7 = 70 bits, covers all 64-bit seeds with 6 bits of zero-padding). The authoritative wordlist lives at `kody-w/RAR/rapp_sdk.py::MNEMONIC_WORDS`. Local generators may use a smaller interim list for round-tripping but interop with the canonical RAR registry requires the canonical wordlist.

## Composite ID (§4)

`id` = `@<publisher>/<slug>`:
- `publisher`: `[a-z0-9][a-z0-9-]{0,38}` — GitHub handle / DID / org slug
- `slug`: `[a-z0-9][a-z0-9-]{0,62}`

For this neighborhood: `id` = `@kody-w/public-art-collective`.

The ID is a friendly label for humans. **The seed is the true identity.**

## URL hash protocol for summoning (§5.1)

Binders MUST handle these URL hashes:

| Hash | Behavior |
|---|---|
| `#add=<id>`         | Resolve id, add to collection |
| `#seed=<dec-or-hex>`| Resolve by seed, open detail |
| `#incant=<w1>+...+<w7>` | Decode words → seed → same as `#seed=` |
| `#collection` / `#browse` / `#summon` / `#manage` | Deep-link to a tab |

The `../holo-qr.svg` in this repo encodes the canonical summon URL: `https://kody-w.github.io/RAPPcards/#summon&seed=<this-seed>`.

---

*Frozen excerpt. For the full spec (export envelope, registry block, advanced fields), see `kody-w/RAPPcards/SPEC.md` v1.1.2 if reachable.*
