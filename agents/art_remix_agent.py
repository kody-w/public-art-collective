"""art_remix_agent.py — fork an existing submission as a new piece.

Reads the original meta + content, returns a new draft tagged `remix_of: <original_slug>`,
then hands off to art_submit_agent's PR draft URL flow."""
import json
import os
import time
import urllib.parse

from agents.basic_agent import BasicAgent


class ArtRemixAgent(BasicAgent):
    name = "art_remix"
    metadata = {
        "name": "art_remix",
        "description": "Remix an existing submission into a new piece. Reads the original, drafts a remix with `remix_of` lineage, returns the PR-draft URL.",
        "parameters": {
            "type": "object",
            "properties": {
                "original_slug": {"type": "string", "description": "Slug of the submission to remix."},
                "remixer_login": {"type": "string", "description": "GitHub login of the remixer."},
                "new_title": {"type": "string", "description": "Title of the remix."},
                "new_content": {"type": "string", "description": "The remix's artwork or prompt."}
            },
            "required": ["original_slug", "remixer_login", "new_title", "new_content"]
        }
    }

    def _seed_dir(self):
        return os.environ.get("NEIGHBORHOOD_SEED_DIR", os.getcwd())

    def _gate_repo(self):
        try:
            with open(os.path.join(self._seed_dir(), "neighborhood.json"), "r") as f:
                return (json.load(f) or {}).get("github") or ""
        except (FileNotFoundError, ValueError):
            return ""

    def _slugify(self, s):
        out = []
        for c in (s or "").lower():
            if c.isalnum():
                out.append(c)
            elif c in (" ", "-", "_"):
                out.append("-")
        return ("".join(out).strip("-") or "remix")[:48]

    def perform(self, original_slug, remixer_login, new_title, new_content, **kwargs):
        slug = self._slugify(new_title) + "-remix"
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        meta = {
            "schema": "rapp-art-submission/1.0",
            "title": new_title,
            "slug": slug,
            "contributor": remixer_login,
            "kind": "text",
            "submitted_at": ts,
            "remix_of": original_slug,
            "license": "CC0-1.0",
        }
        gate = self._gate_repo().rstrip("/")
        meta_path = f"submissions/{slug}/meta.json"
        content_path = f"submissions/{slug}/piece.md"
        meta_url = f"{gate}/new/main/?filename={urllib.parse.quote(meta_path)}&value={urllib.parse.quote(json.dumps(meta, indent=2))}"
        content_url = f"{gate}/new/main/?filename={urllib.parse.quote(content_path)}&value={urllib.parse.quote(new_content)}"
        return json.dumps({
            "schema": "rapp-art-remix-envelope/1.0",
            "drafted_meta": meta,
            "drafted_content_path": content_path,
            "lineage": {"remix_of": original_slug},
            "next_step": {
                "action": "open_remix_pr",
                "step_1_url": meta_url,
                "step_2_url": content_url,
            },
        }, indent=2)
