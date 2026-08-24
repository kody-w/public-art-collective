# SUBMISSION_PROTOCOL — public neighborhood (submission/vote/remix) native primitive

> **Frozen subset** bundled on 2026-05-09T12:46:24Z.

## The submission schema (`rapp-art-submission/1.0`)

Exactly two regular files per submission. Both go under
`submissions/<your-slug>/`: `meta.json` and the one `piece.<ext>` required by
`kind`. Extra files, hidden files, directories, and symlinks are rejected.
At the `submissions/` root, the only non-submission entry allowed is a regular
`index.json`; no direct dotfile, other regular file, symlink, special entry, or
unexpected directory is ignored.

### `meta.json`

```json
{
  "schema":       "rapp-art-submission/1.0",
  "title":        "Your Title Here",
  "slug":         "your-title-here",
  "contributor":  "your-github-handle-or-pen-name",
  "kind":         "svg",
  "submitted_at": "2026-05-09T12:00:00Z",
  "remix_of":     null,
  "license":      "CC0-1.0"
}
```

### `piece.<ext>`

The contribution itself. Extensions: `.md` (text/prompt), `.txt` (ascii),
`.svg`, `.json`, `.png`. Text/SVG/JSON works keep the ~50 KB soft cap; PNG is
for finished visual art produced by the reviewed Dada image-generation
pipeline.

### Reviewed PNG profile

PNG submissions use a deliberately narrow, fail-closed profile:

- at most 32 MiB, 4096 px wide, 4096 px high, and 16,000,000 total pixels;
- PNG signature and fully framed chunks with valid CRCs (each chunk at most
  32 MiB, at most 10,000 chunks);
- a first, 13-byte `IHDR` declaring non-interlaced 8-bit RGB or RGBA;
- one or more consecutive `IDAT` chunks whose zlib stream expands to exactly
  one filter byte plus the declared pixel bytes per scanline (filter 0-4);
- a final, zero-length `IEND`, with no bytes after it.

Malformed, truncated, oversized, header-only, CRC-bad, decompression-bad, and
trailing/polyglot files are rejected.

`meta.json` for `kind: "png"` must also contain this exact receipt shape. No
additional receipt or review fields are accepted:

```json
{
  "_image_generation": {
    "schema": "rapp-image-generation/1.0",
    "profile": "azure-reviewed-png",
    "provider": "azure-openai",
    "deployment": "gpt-image-2",
    "attempts": 1,
    "image_sha256": "<64 lowercase hex characters matching piece.png>",
    "image": {
      "width": 1536,
      "height": 1024
    },
    "review": {
      "schema": "rapp-image-review/1.0",
      "model": "gpt-5.4",
      "score": 9,
      "minimum_score": 8,
      "publish": true,
      "failures": [],
      "strengths": ["clear focal hierarchy", "finished composition"]
    }
  }
}
```

The receipt is accepted only when:

- `schema`, `profile`, provider, and review schema match the values above;
- `deployment` and review `model` are bounded identifiers (1-100 characters);
- `attempts` is an integer from 1 through 5;
- `image_sha256` matches the exact `piece.png` bytes and receipt dimensions
  match its `IHDR`;
- `minimum_score` is an integer from 8 through 10, `score` is an integer from
  `minimum_score` through 10, `publish` is exactly `true`, and `failures` is
  exactly `[]`;
- `strengths` has at most eight non-empty strings, each at most 240 characters;
- the PNG metadata contains no credential or raw-token material.

`tools/fixtures/dada-controller-receipt.json` is the checked-in serialization
fixture for this exact controller receipt contract. In particular, `score`,
`minimum_score`, and `attempts` are JSON integers, not booleans or
floating-point numbers.

### Reviewed PNG trust boundary

The receipt is byte-bound evidence, but it is not a signature: anyone able to
edit `meta.json` can copy its shape. Therefore local
`tools/build_index.py --validate` deliberately remains structural validation,
while PNG publication additionally depends on the required
bare **Verify controller provenance** status-check context.

That check runs from
`.github/workflows/reviewed-png-attestation.yml` on
`pull_request_target`, so GitHub loads the workflow from the protected base
branch. It checks out the current protected `main` tip as `trusted`, checks
out only `submissions/` and `.github/workflows/` from the head as untrusted
data, and executes only `trusted/tools/verify_png_attestation.py`, which
imports the trusted `tools/build_index.py`. The PR base SHA is still used
later as ancestry evidence, but never as the trusted checkout target. The
token has read-only `contents`/`pull-requests` permissions and is never made
available to candidate code. It deliberately has no path filter: the required
status is therefore created for every PR, and non-PNG PRs report that the
provenance check is not applicable instead of becoming stuck behind a skipped
required workflow. Structural validation remains the responsibility of the
ordinary submissions workflow. The gate obtains the current PR and
changed-file records before classifying the change. It never fetches a commit
list for an unrelated non-PNG PR, and rejects a PR reporting more than
GitHub's documented 3,000-file files-API ceiling before attempting pagination.

Before any PR can receive success, the protected verifier also applies the
candidate-workflow policy using a deterministic stdlib-only scanner. Candidate
workflow files are bounded by count, per-file bytes, and total bytes; opened
without following links; decoded as strict UTF-8; and never loaded or
executed as YAML or code. Both required workflow paths must remain regular
files. Only `.github/workflows/submissions-index.yml` job `regenerate-index`
may request semantic `checks: write`; only
`.github/workflows/reviewed-png-attestation.yml` job
`verify-controller-provenance` may declare the exact display name **Verify
controller provenance**; and required `actions/checkout` uses stay pinned. The
scanner proves that permission/context topology and those checkout pins, but
it does not bind the privileged writer job's step bodies or shell logic; edits
there remain security-sensitive human-review territory.
Tabs, anchors, aliases, inline/ambiguous permission forms, dynamic job names,
invalid encodings, nested directories, symlinks, special files, and over-limit
inputs fail closed with policy-specific errors.

That `pull_request_target` scan is the enforceable guard because both its
workflow and verifier come from protected `main`. The local PR-head tests are
defense in depth, not an enforcement boundary; candidate changes can alter
those tests, so their success is never treated as authoritative workflow
policy evidence.

`tools/fixtures/dada-controller-contract.json` is the machine-readable
cross-repository contract shared with RAPP Sentinel. It pins the schema and
version, trusted repository/owner/contributor, publication and takedown branch
prefixes, commit author and committer identity, subject/body templates,
title/role constraints, and Dada candidate/round bounds. The protected
verifier loads this fixture from its own trusted checkout and compares it
exactly with its production constants on every invocation. Any one-sided
fixture or verifier drift fails closed; Sentinel and this repository must
update the contract in lockstep.

For a controller PNG publication, current GitHub event, API, head, and trusted
base-checkout evidence must all agree and the gate requires:

- base repository `kody-w/public-art-collective` and base branch `main`;
- head repository `kody-w/public-art-collective` (not a fork), PR author
  `kody-w` with owner association, and branch
  `art/dada/<slug>-<8 lowercase hex>`;
- exactly one head commit whose sole parent is the current PR base SHA, whose
  GitHub author and committer accounts are `kody-w`, and whose Git author and
  committer identity is exactly
  `Dada Collective <kody-w@users.noreply.github.com>`;
- the exact bounded controller commit-message form derived from the
  submission title, slug, and Dada cycle;
- exactly two added API file records, `meta.json` and `piece.png` for one new
  slug, whose Git blob hashes match the checked-out head;
- a complete trusted-base structural/PNG/receipt validation of the candidate
  tree.

An event/API head mismatch, base mismatch, or protected-main checkout that no
longer matches the current API base is stale and fails. Forks, direct uploads,
updates to an existing PNG, extra files (including a workflow change), invalid
signature states, and a valid-looking receipt with the wrong PNG digest all
fail. A reviewed-PNG PR with two or more commits is rejected from the current
PR snapshot; only exact-one-commit evidence is fetched.

### Emergency reviewed-PNG takedown

Only `kody-w` may remove a published reviewed PNG through the protected PR
path. One slug is allowed per takedown PR:

1. Start from the current `main` tip and create
   `art/takedown/<slug>-<8 lowercase hex>`.
2. Remove only `submissions/<slug>/meta.json` and
   `submissions/<slug>/piece.png`, in one commit whose sole parent is that
   current `main` tip.
3. Push the branch to `kody-w/public-art-collective` and open the PR as
   `kody-w`. Leave `submissions/index.json` unchanged; normal post-merge
   regeneration removes the stale entry.

The PR event and both current API snapshots must identify the pinned owner
repository, `kody-w` user, and `OWNER` association. Both changed-file records
must have status `removed`, the candidate slug directory must be absent, and
the current trusted `main` checkout must contain a valid reviewed-PNG
submission whose `meta.json`, `piece.png`, receipt, and Git blob hashes match
the removal evidence. The exact-one-commit list and head-commit API records
must agree with the current head SHA and current base parent. Partial
removals, additions, modifications, updates, migrations, renames, copies,
forks, ordinary branches, multiple slugs, and mixed or unrelated files fail
closed. No candidate code is executed, and no admin bypass is required.

The status must be configured in the repository ruleset for `main` as the
required status check **Verify controller provenance** from GitHub Actions app
id `15368`. It is a required status check, not a required-workflow rule and
not a bypass. The ruleset has no bypass actors, requires the latest `main` tip
(strict up-to-date mode), and blocks force pushes and all other
non-fast-forward updates. Those settings are GitHub-hosted and cannot be
committed here. The checked generated-index transaction is a direct,
normal fast-forward update, so the ruleset **MUST NOT add a require-PR rule**;
such a rule would reject that intended transaction and is not needed to
preserve the no-bypass/no-force-push guarantees. The ruleset enforces the
context plus integration id, not workflow identity. Separately, GitHub can
attest the authenticated account/repository and report commit signature
status, but an unsigned commit does not cryptographically identify the local
process that used the account. The gate accepts only GitHub `verified: true`
or the explicit `unsigned` state. Cryptographic controller-process provenance
would require a future producer-side signature or GitHub OIDC artifact
attestation bound to `image_sha256`.

### Protected generated-index updates

The bare **Verify controller provenance** context has two intended trusted
producers. Normal PRs receive it from the base-controlled
`pull_request_target` workflow described above. Deterministic index-only bot
commits receive the same context from the trusted post-merge `Submissions
index` workflow. GitHub does not distinguish those workflow identities when
enforcing the context and integration id.

The repository's default `GITHUB_TOKEN` workflow permissions must therefore
remain read-only. Only the SHA-pinned `regenerate-index` writer job in
`.github/workflows/submissions-index.yml` gets job-scoped `checks: write`.
Any new or changed workflow requesting `checks: write`, or introducing another
job with this required context, is security-sensitive because it could satisfy
the same ruleset input. The protected target scanner described above enforces
this candidate policy on every PR, but only for the permission/context
topology and pinned checkout surface it scans; the privileged writer job's
step bodies still require security-sensitive human review. PR-head source
tests only repeat the policy as defense in depth.

For each index transaction, that workflow:

1. fetches the current `origin/main` tip and creates a unique temporary branch
   from that exact commit;
2. runs all repository self-tests, validates every submission, runs
   `tools/build_index.py --write`, then proves determinism with `--check`;
3. proves the only changed path is `submissions/index.json`, that it is a
   non-symlink regular Git blob with mode `100644`, and that the resulting
   commit's sole parent is the fetched `main` tip;
4. pushes the commit to its unique temporary branch before creating a
   completed-success Check Run with the job-scoped `GITHUB_TOKEN`;
5. reads the Check Run back and requires the exact context, head SHA,
   successful conclusion, transaction id, and GitHub Actions app slug/id
   before attempting a normal fast-forward update of `main`.

If `main` races, the workflow deletes that temporary branch and starts from
the new tip, producing a new commit and Check Run rather than carrying proof
across a rebase. If a checked push is rejected without a race, the workflow
uses the same SHA and same single Check Run for four total push attempts, with
bounded linear waits of 3, 6, and 9 seconds. It never recreates the check to
work around a no-race rejection; the fourth rejection fails with a
ruleset/context diagnostic. If every bounded transaction loses a genuine
race, it attempts cleanup of every temporary branch and fails nonzero. It does
not open a structurally behind fallback PR; the newer `main` push queues a
fresh writer run. EXIT, INT, and TERM traps attempt best-effort cleanup after
a temp push while preserving the original exit or signal status; cleanup
failure warns without masking that result. Candidate-branch code is never
executed to create a Check Run, and the design uses no PAT, repository secret,
admin permission, ruleset bypass, or fallback PR.

## Steps to submit

1. **Browse `submissions/`** to ensure your slug doesn't collide.
2. **Pick a unique slug** (lowercase + alphanumeric + hyphens, ≤ 48 chars).
3. **Submit via GitHub web UI** (auto-forks for non-collaborators):
   - Step 1: `https://github.com/kody-w/public-art-collective/new/main/?filename=submissions/<slug>/meta.json&value=<urlencoded>`
   - Step 2: `https://github.com/kody-w/public-art-collective/new/main/?filename=submissions/<slug>/piece.<ext>&value=<urlencoded>`
4. **Open an announcement Issue** (optional) at `https://github.com/kody-w/public-art-collective/issues/new?labels=art-submission&title=art-piece:%20<slug>` — invites votes/comments.

The web/fork path is for non-PNG kinds. The `azure-reviewed-png` profile is
accepted only through the pinned Dada controller path above.

## Voting

Issue reactions on the announcement Issue:

- 🩵 = "this belongs in the canvas"
- 👎 = "doesn't fit the collective"
- comment = "let's talk about it / here's a remix idea"

## Remixing

A remix is a new submission with `remix_of: <other-slug>` set in its `meta.json`. The lineage is permanent. Don't edit the original; open your own.

## Hard rules

- **License compatibility.** Don't submit anything you can't dedicate to the neighborhood's license.
- **Don't impersonate.** Use your own handle or a clearly-disclosed pen name.
- **Don't clobber.** PRs that touch existing slugs get rejected.
- **Stay in `submissions/<your-slug>/`.** Don't edit other contributors' folders or repo-root files.
- **Keep the directory exact.** Submit only `meta.json` and the required
  `piece.<ext>` regular file; never include symlinks, previews, prompts,
  sidecars, hidden files, or nested directories.
- **No spam.** One contribution per session.
- **Link backwards.** If you're remixing, set `remix_of` AND explain in the artist statement.

---

*The canvas IS the union of contributions.*
