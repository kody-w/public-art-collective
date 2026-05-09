# RAPPID_SPEC — Identity v2

> **Frozen excerpt** of the canonical rappid contract (`rapp-rappid/2.0`). Bundled at planting time on 2026-05-09T12:46:24Z.

## Format

```
rappid:v2:<kind>:@<owner>/<repo>:<32-hex-no-dashes>@github.com/<owner>/<repo>
```

Example (this neighborhood's):

```
rappid:v2:<kind>:@kody-w/public-art-collective:<32-hex>@github.com/kody-w/public-art-collective
```

(See `../rappid.json` for the actual value.)

## Components

| Part | Rule |
|---|---|
| Prefix `rappid:v2:` | Literal. Tells parsers this is a v2 rappid. |
| `<kind>` | One of: `neighborhood`, `ant-farm`, `braintrust`, `workspace`, `twin`, `prototype`. |
| `@<owner>/<repo>` | The GitHub composite identity. The `@` prefix is literal and required. |
| `<32-hex-no-dashes>` | A UUID4 with dashes stripped — 32 lowercase hex characters. Minted ONCE at planting; permanent thereafter. |
| `@github.com/<owner>/<repo>` | The substrate URL, suffixed for self-resolution. |

## Invariants (Constitution Art. XXXIV.5)

1. **Permanence.** Once minted, a rappid is permanent for the lifetime of the neighborhood. Re-grafting, re-planting, kernel upgrades — none of these mint a new rappid.
2. **Bond preservation.** The bond technique (egg → overlay → hatch back) preserves the rappid through every kernel upgrade.
3. **Lineage chain.** A neighborhood's `parent_rappid` chains back to its ancestor (the species root for many: `rappid:v2:prototype:@rapp/origin:0b635450c04249fbb4b1bdb571044dec@github.com/kody-w/RAPP`).
4. **No two organisms share a rappid.** Mint via `uuid.uuid4().hex` — collision probability is negligible.
5. **The rappid is the seed source for the neighborhood's holocard.** `derive_seed(rappid_str)` via BLAKE2b-64 produces a deterministic 64-bit ID. Same rappid → same seed → same incantation, forever.

## Required fields in `../rappid.json` (`rapp-rappid/2.0`)

| Field | Required | Notes |
|---|---|---|
| `schema`       | yes | `rapp-rappid/2.0` |
| `rappid`       | yes | The full v2 string |
| `kind`         | yes | One of the 6 kinds above |
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
