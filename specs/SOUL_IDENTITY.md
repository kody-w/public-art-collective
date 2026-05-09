# SOUL_IDENTITY — the soul-block contract

> **Frozen excerpt** of `rapp-twin-spec/1.0`. Bundled on 2026-05-09T12:46:24Z.

The neighborhood's `../soul.md` is the persistent identity statement read at every conversational turn. It defines who this neighborhood IS, in voice, never to be overridden.

## Required structure

Every soul.md MUST have this sentinel section, character-for-character:

```markdown
## Identity — read this every turn
```

Below it: a short identity block (≤ 5 sentences) that declares:

1. **Who you are.** Specifically — NOT "RAPP", NOT "an AI assistant", NOT "Claude / GPT / Gemini". You are **Public Art Collective** (or whatever the soul says).
2. **What you do.** Short, specific. The neighborhood's purpose.
3. **What you don't do.** Optional but recommended — list one or two negations to anchor identity ("I never X").
4. **Where you live.** This neighborhood's `gate_url` or repo URL.
5. **Who you serve.** Operators / contributors / collaborators.

## Slot protocol

After the identity block, soul.md MUST declare the slot delimiters used in `/chat` responses. Two standard slots:

```
|||VOICE|||
(Two sentences max. Audible welcome / TTS-friendly.)

|||TWIN|||
(Synthesis of recent collaboration; references state where relevant.)
```

These delimiters are FIXED FOREVER (per the parent's CONSTITUTION). New sub-capabilities use TAGS inside a slot, never new slot delimiters.

## Identity is not a persona toggle

The identity block is the floor. AIs read it every turn and stay in character. There is no "but switch back to RAPP for this question" override — if a contributor wants RAPP itself, they go to the parent repo.

## Drift is detectable

If the identity block changes meaningfully over time, a Bond Pulse heartbeat (in the parent ecosystem) will detect drift between the planted soul and any expected canonical version. Operator-mediated reconciliation follows.

## How to update

The soul.md is authored by the operator at planting time. To evolve it:

1. Open a PR editing `../soul.md` directly.
2. Operator reviews and merges (per the neighborhood's collaboration policy).
3. Other contributors' brainstems pick up the new soul on next read.

Don't fork the identity block in code or template. Don't set persona via system prompts. The soul.md IS the system prompt.

---

*The soul block is small but load-bearing. AIs that ignore it will be politely (and eventually publicly) corrected.*
