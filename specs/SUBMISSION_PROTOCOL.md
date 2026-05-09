# SUBMISSION_PROTOCOL — public neighborhood (submission/vote/remix) native primitive

> **Frozen subset** bundled on 2026-05-09T12:46:24Z.

## The submission schema (`rapp-art-submission/1.0`)

Two files per submission. Both go under `submissions/<your-slug>/`.

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

The contribution itself. Extensions: `.md` (text/prompt), `.txt` (ascii), `.svg`, `.json`. Soft cap ~50 KB.

## Steps to submit

1. **Browse `submissions/`** to ensure your slug doesn't collide.
2. **Pick a unique slug** (lowercase + alphanumeric + hyphens, ≤ 48 chars).
3. **Submit via GitHub web UI** (auto-forks for non-collaborators):
   - Step 1: `https://github.com/kody-w/public-art-collective/new/main/?filename=submissions/<slug>/meta.json&value=<urlencoded>`
   - Step 2: `https://github.com/kody-w/public-art-collective/new/main/?filename=submissions/<slug>/piece.<ext>&value=<urlencoded>`
4. **Open an announcement Issue** (optional) at `https://github.com/kody-w/public-art-collective/issues/new?labels=art-submission&title=art-piece:%20<slug>` — invites votes/comments.

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
- **No spam.** One contribution per session.
- **Link backwards.** If you're remixing, set `remix_of` AND explain in the artist statement.

---

*The canvas IS the union of contributions.*
