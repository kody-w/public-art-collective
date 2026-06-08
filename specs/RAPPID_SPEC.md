# RAPPID_SPEC — Identity (Eternity format)

> **Frozen excerpt** of the canonical rappid contract (`rapp-rappid/2.0`). Bundled at planting time on 2026-05-09T12:46:24Z. Updated to the Eternity format (Constitution Art. XXXIV.1, locked 2026-06-03).

## Format

The one current rappid form (Constitution Art. XXXIV.1):

```
rappid:@<owner>/<slug>:<hex>
```

Example (this neighborhood's):

```
rappid:@kody-w/public-art-collective:<hex>
```

No `v2:`/`v3:` prefix, no inline `<kind>:` segment, no trailing `@github.com/...` suffix. `kind` now lives in the record (a field), not the string. The hash is the identity and the join key; matching/dedup is always on the hash.

(See `../card.json` / `../neighborhood.json` for the actual value.)

## Components

| Part | Rule |
|---|---|
| Prefix `rappid:` | Literal. Tells parsers this is a rappid. |
| `@<owner>/<slug>` | The GitHub composite identity and canonical location. The `@` prefix is literal and required. `github.com/<owner>/<slug>` is the door. |
| `<hex>` | The identity hash (lowercase hex). Existing 32-hex values are grandfathered; new identities are full 64-hex SHA-256. Minted ONCE at planting; permanent thereafter. |

`kind` is recorded in `../rappid.json` / the holocard record, not in the string.

### Legacy forms (read forever, never emitted)

Every legacy form still resolves and is canonicalized to the form above (hash preserved) — only the consolidated form is emitted:

```
rappid:v2:<kind>:@<owner>/<repo>:<32-hex-no-dashes>@github.com/<owner>/<repo>   (v2 — legacy)
<uuid>                                                                          (v1 — bare UUID, legacy)
```

## Invariants (Constitution Art. XXXIV.5)

1. **Permanence.** Once minted, a rappid is permanent for the lifetime of the neighborhood. Re-grafting, re-planting, kernel upgrades — none of these mint a new rappid.
2. **Bond preservation.** The bond technique (egg → overlay → hatch back) preserves the rappid through every kernel upgrade.
3. **Lineage chain.** A neighborhood's `parent_rappid` chains back to its ancestor (the species root for many, canonicalized to the Eternity form: `rappid:@kody-w/RAPP:0b635450c04249fbb4b1bdb571044dec`). Legacy `parent_rappid` strings are read and canonicalized; the hash is preserved.
4. **No two organisms share a rappid.** Mint via `uuid.uuid4().hex` — collision probability is negligible.
5. **The rappid is the seed source for the neighborhood's holocard.** `derive_seed(rappid_str)` via BLAKE2b-64 produces a deterministic 64-bit ID. Same rappid → same seed → same incantation, forever.

## Required fields in `../rappid.json` (`rapp-rappid/2.0`)

| Field | Required | Notes |
|---|---|---|
| `schema`       | yes | `rapp-rappid/2.0` |
| `rappid`       | yes | The Eternity string `rappid:@<owner>/<slug>:<hex>` |
| `kind`         | yes | The record-level kind (e.g. `neighborhood`) — now carried in the record, not the string |
| `_migrated_from` | when migrated | The prior rappid string, recorded when the top-level rappid changed |
| `name`         | yes | Slug — matches the repo name |
| `display_name` | yes | Human-readable |
| `github`       | yes | `https://github.com/<owner>/<repo>` |
| `parent_rappid`| yes (may be null for species roots) | The lineage anchor |
| `parent_repo`  | yes | Where the parent's rappid lives |
| `planted_by`   | yes | GitHub handle of the operator who planted |
| `planted_at`   | yes | ISO-8601 UTC |
| `kernel_version` | yes | The kernel version at planting time |

## Don't

- Don't change the rappid after minting — that's identity destruction. Use a new rappid for a new neighborhood instead.
- Don't synthesize rappids by hand — always mint via UUID4.
- Don't include personal data in the rappid — it travels publicly.
- Don't reuse a rappid string across neighborhoods (uniqueness is critical for seed derivation).

---

*Frozen excerpt. For full identity / lineage / bonding rules, see `CONSTITUTION.md` Art. XXXIV.5 in the parent repo if reachable.*
