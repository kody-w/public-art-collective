"""art_curate_agent.py — browse + summarize current submissions.

Lists the contents of submissions/ in the seed (or fetches via raw.githubusercontent.com
when running outside a clone). Returns a curator-style summary."""
import json
import os
import urllib.error
import urllib.request

from agents.basic_agent import BasicAgent


RAW = "https://raw.githubusercontent.com"


class ArtCurateAgent(BasicAgent):
    name = "art_curate"
    metadata = {
        "name": "art_curate",
        "description": "Browse + summarize current submissions in the Public Art Collective. Returns recent merges with contributor + kind + title.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max submissions to return. Defaults to 10."},
                "filter_kind": {"type": "string", "description": "Optional — restrict to one medium (text / ascii / svg / prompt / json)."}
            },
            "required": []
        }
    }

    def _seed_dir(self):
        return os.environ.get("NEIGHBORHOOD_SEED_DIR", os.getcwd())

    def _gate_slug(self):
        try:
            with open(os.path.join(self._seed_dir(), "neighborhood.json"), "r") as f:
                gh = (json.load(f) or {}).get("github") or ""
        except (FileNotFoundError, ValueError):
            return None
        prefix = "https://github.com/"
        if gh.startswith(prefix):
            return gh[len(prefix):].rstrip("/")
        return None

    def _list_local(self):
        target = os.path.join(self._seed_dir(), "submissions")
        if not os.path.isdir(target):
            return []
        out = []
        for name in sorted(os.listdir(target)):
            sub_dir = os.path.join(target, name)
            meta_path = os.path.join(sub_dir, "meta.json")
            if not os.path.isfile(meta_path):
                continue
            try:
                with open(meta_path, "r") as f:
                    out.append(json.load(f))
            except (ValueError, OSError):
                continue
        return out

    def _list_remote(self, slug):
        if not slug:
            return []
        url = f"{RAW}/{slug}/main/submissions/index.json"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "rapp-art-curate"})
            with urllib.request.urlopen(req, timeout=4.0) as r:
                data = json.loads(r.read().decode("utf-8"))
                return data.get("submissions") or []
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError, ValueError):
            return []

    def perform(self, limit=10, filter_kind=None, **kwargs):
        items = self._list_local()
        source = "local"
        if not items:
            items = self._list_remote(self._gate_slug())
            source = "remote"

        if filter_kind:
            items = [s for s in items if (s.get("kind") or "").lower() == filter_kind.lower()]
        items = items[: int(limit or 10)]

        return json.dumps({
            "schema": "rapp-art-curate-report/1.0",
            "source": source,
            "count": len(items),
            "submissions": items,
        }, indent=2)
