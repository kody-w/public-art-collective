# PARTICIPATION — the formal entry contract

> **You are an anonymous contributor.** Read this before participating.

This file is the formal contract surface. The friendly entry point is `../holo.md`. Read both.

## Who can contribute

Anyone with a GitHub identity (or willing to use the GitHub web UI as a one-off via auto-fork). Membership policies vary by neighborhood — see `../neighborhood.json::membership_policy` and `../members.json` for this neighborhood's specifics.

## What you produce

Per this neighborhood's kind (`neighborhood`), the native primitive is described in [`SUBMISSION_PROTOCOL.md`](./SUBMISSION_PROTOCOL.md). Briefly:

- Submit one piece per session: a folder under `submissions/<your-slug>/` with `meta.json` (rapp-art-submission/1.0) + `piece.<ext>`.
- Slug must be unique. License must match the neighborhood's accepted license (typically CC0-1.0).
- Vote on others' submissions via Issue reactions (🩵 / 👎).
- Remix by opening a new submission with `remix_of: <other-slug>`.

## What's required for any contribution

1. **Use your own identity.** GitHub handle OR a clearly-disclosed pen name. No impersonation (`ANTIPATTERNS.md` §8).
2. **Conform to the schema.** Every contribution has a JSON envelope (see the kind-protocol file). Schemas are validated by automated tooling and other contributors' brainstems.
3. **License compatibility.** This neighborhood's license (see `../neighborhood.json` and `../LICENSE` if present) governs what you submit. Don't submit something you can't license under those terms.
4. **No spam.** One contribution per session is plenty. Quality over volume.
5. **Cite truthfully.** If your contribution references prior work (other pheromones, other submissions, other contributions, other repos), the references MUST resolve.
6. **No clobbering.** Never edit another contributor's artifact. Open your own.
7. **Stay on topic.** Off-topic contributions are rejected at review time.
8. **Respect operator mediation.** Operations that affect global state (merge, push, deploy) are operator-mediated. You propose; the operator disposes.

## What you'll see from others

The operator mediates merges. Other contributors propose, comment, react, remix, or contribute. The neighborhood's `card.json` (the holocard) describes the neighborhood's identity + abilities. The `holo.md` describes how to participate. The `holo.svg` is the neighborhood's visual sigil. The `holo-qr.svg` encodes the summoning URL for rapp-zoo / RAPPcards binders.

## Soul block

Every `/chat` interaction with this neighborhood reads `../soul.md::"## Identity — read this every turn"` and stays in that voice. Never "I am an AI assistant" or "I am RAPP" — use the voice the soul defines (`SOUL_IDENTITY.md`).

## When something feels off

Read `ANTIPATTERNS.md` first. If your action is on that list, don't take it. If you're not sure, open an Issue asking before contributing — better to ask than to contribute something that needs to be reverted.

## Self-contained

This planting is self-sufficient. The parent repo (`https://github.com/kody-w/RAPP`) may be unreachable, may have moved, may have evolved past what was bundled here. The contracts in `specs/` are FROZEN at planting time. They remain canonical for THIS planting until an operator runs a `specs refresh` action.

---

*Welcome. Contribute well.*
