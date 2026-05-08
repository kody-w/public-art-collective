"""art_submit_agent.py — open a PR submitting a new piece to the public art collective.

Drafts the metadata file + the artwork content (text, ASCII, SVG, prompt — anything
that fits in a file), then constructs a GitHub create-file URL the LLM (or a human)
can follow to open the PR. Phase 1 stops at the URL; Phase 2 will use the GitHub
API directly when an authed token is present."""
import json
import os
import time
import urllib.parse

from agents.basic_agent import BasicAgent


class ArtSubmitAgent(BasicAgent):
    name = "art_submit"
    metadata = {
        "name": "art_submit",
        "description": "Submit a new piece to the Public Art Collective. Drafts the submission metadata and returns a pre-filled GitHub create-file URL so the operator can review + open the PR.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title of the piece."},
                "contributor_login": {"type": "string", "description": "Submitter's GitHub login."},
                "kind": {
                    "type": "string",
                    "enum": ["text", "ascii", "svg", "prompt", "json"],
                    "description": "Artwork medium."
                },
                "content": {"type": "string", "description": "The artwork itself (or a prompt that generates it)."},
                "remix_of": {"type": "string", "description": "Optional — slug of an existing submission this remixes."}
            },
            "required": ["title", "contributor_login", "kind", "content"]
        }
    }

    def _seed_dir(self):
        return os.environ.get("NEIGHBORHOOD_SEED_DIR", os.getcwd())

    def _slugify(self, s):
        out = []
        for c in (s or "").lower():
            if c.isalnum():
                out.append(c)
            elif c in (" ", "-", "_"):
                out.append("-")
        slug = "".join(out).strip("-")
        return slug[:48] or "untitled"

    def _gate_repo(self):
        try:
            with open(os.path.join(self._seed_dir(), "neighborhood.json"), "r") as f:
                return (json.load(f) or {}).get("github") or ""
        except (FileNotFoundError, ValueError):
            return ""

    def perform(self, title, contributor_login, kind, content, remix_of=None, **kwargs):
        slug = self._slugify(title)
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        meta = {
            "schema": "rapp-art-submission/1.0",
            "title": title,
            "slug": slug,
            "contributor": contributor_login,
            "kind": kind,
            "submitted_at": ts,
            "remix_of": remix_of,
            "license": "CC0-1.0",
        }
        meta_path = f"submissions/{slug}/meta.json"
        content_ext = {"text": "md", "ascii": "txt", "svg": "svg", "prompt": "md", "json": "json"}.get(kind, "txt")
        content_path = f"submissions/{slug}/piece.{content_ext}"

        gate = self._gate_repo().rstrip("/")
        repo_meta_url = f"{gate}/new/main/?filename={urllib.parse.quote(meta_path)}&value={urllib.parse.quote(json.dumps(meta, indent=2))}"
        repo_content_url = f"{gate}/new/main/?filename={urllib.parse.quote(content_path)}&value={urllib.parse.quote(content)}"

        return json.dumps({
            "schema": "rapp-art-submission-envelope/1.0",
            "drafted_meta": meta,
            "drafted_content_path": content_path,
            "next_step": {
                "action": "open_two_files_pr",
                "step_1_url": repo_meta_url,
                "step_2_url": repo_content_url,
                "note": "GitHub auto-forks for non-collaborators. Step 1 creates the metadata, step 2 the content; both go in one branch. Operator merges or rejects."
            },
        }, indent=2)
