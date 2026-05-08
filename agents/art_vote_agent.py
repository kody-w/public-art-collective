"""art_vote_agent.py — vote on a submission via Issue reaction.

Votes are GitHub Issue reactions on the per-submission Issue (one Issue per
merged submission, opened automatically by the curator agent or by hand).
Phase 1 returns a pre-filled URL; Phase 2 will react via GitHub API."""
import json
import os
import urllib.parse

from agents.basic_agent import BasicAgent


class ArtVoteAgent(BasicAgent):
    name = "art_vote"
    metadata = {
        "name": "art_vote",
        "description": "Vote on a submission via Issue reaction. Returns the pre-filled URL or raw API call the operator (or follow-up agent) can execute.",
        "parameters": {
            "type": "object",
            "properties": {
                "submission_slug": {"type": "string", "description": "The slug of the submission to vote on."},
                "voter_login": {"type": "string", "description": "GitHub login of the voter."},
                "reaction": {
                    "type": "string",
                    "enum": ["+1", "-1", "laugh", "hooray", "confused", "heart", "rocket", "eyes"],
                    "description": "GitHub Issue reaction type."
                },
                "comment": {"type": "string", "description": "Optional accompanying comment."}
            },
            "required": ["submission_slug", "voter_login", "reaction"]
        }
    }

    def _gate_slug(self):
        try:
            with open(os.path.join(os.environ.get("NEIGHBORHOOD_SEED_DIR", os.getcwd()), "neighborhood.json"), "r") as f:
                gh = (json.load(f) or {}).get("github") or ""
        except (FileNotFoundError, ValueError):
            return None
        prefix = "https://github.com/"
        return gh[len(prefix):].rstrip("/") if gh.startswith(prefix) else None

    def perform(self, submission_slug, voter_login, reaction, comment=None, **kwargs):
        slug = self._gate_slug() or "<owner>/<repo>"
        title = urllib.parse.quote(f"vote — {submission_slug}")
        body_lines = [f"@{voter_login} voting `{reaction}` on `{submission_slug}`."]
        if comment:
            body_lines.append("")
            body_lines.append(comment)
        body = urllib.parse.quote("\n".join(body_lines))
        issue_url = f"https://github.com/{slug}/issues/new?title={title}&body={body}&labels=art-vote,vote-{reaction}"

        return json.dumps({
            "schema": "rapp-art-vote-envelope/1.0",
            "submission_slug": submission_slug,
            "voter_login": voter_login,
            "reaction": reaction,
            "next_step": {
                "action": "open_vote_issue",
                "url": issue_url,
                "api_alternative": (
                    f"gh api -X POST /repos/{slug}/issues/<existing-vote-issue-number>/reactions "
                    f"-f content={reaction}"
                )
            },
        }, indent=2)
