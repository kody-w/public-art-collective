#!/usr/bin/env python3
"""Verify protected reviewed-PNG publication and takedown PRs.

This script is intended to run from the protected base branch under
pull_request_target. It treats the PR checkout as data only, validates that
tree with the protected base branch tip's build_index module, and then binds a
reviewed PNG addition to the pinned Dada controller identity or an exact
reviewed PNG removal to the pinned repository owner.

The GitHub event and API evidence are injectable JSON files so the complete
gate can be tested offline:

  python3 tools/verify_png_attestation.py \
    --event-path event.json \
    --api-fixture api.json \
    --candidate-root candidate \
    --base-root base
"""
import argparse
import hashlib
import json
import os
import re
import stat
import sys
import urllib.error
import urllib.request
from urllib.parse import quote

import build_index


CONTROLLER_CONTRACT_SCHEMA = "rapp-dada-controller-contract/1.0"
CONTROLLER_CONTRACT_VERSION = 1
CONTROLLER_CONTRACT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "dada-controller-contract.json",
)

TRUSTED_REPOSITORY = "kody-w/public-art-collective"
TRUSTED_OWNER = "kody-w"
TRUSTED_CONTRIBUTOR = build_index.REVIEWED_PNG_TRUSTED_CONTRIBUTOR
TRUSTED_BASE_BRANCH = "main"
TRUSTED_AUTHOR_ASSOCIATION = "OWNER"

DADA_COMMIT_AUTHOR_NAME = "Dada Collective"
DADA_COMMIT_AUTHOR_EMAIL = "kody-w@users.noreply.github.com"
DADA_COMMITTER_NAME = "Dada Collective"
DADA_COMMITTER_EMAIL = "kody-w@users.noreply.github.com"
DADA_COLLECTIVE_NAME = "Dada Collective"
DADA_BRANCH_PREFIX = "art/dada"
TAKEDOWN_BRANCH_PREFIX = "art/takedown"
DADA_COMMIT_SUBJECT_TEMPLATE = "art: {title} ({slug})"
DADA_COMMIT_BODY_TEMPLATE = (
    "Autonomous submission by the {role} neighbor of {collective_name}.\n"
    "Dada cycle {cycle}, {rounds} round(s) of "
    "{candidates_per_round} candidates."
)
DADA_CANDIDATES_PER_ROUND = 10
DADA_MIN_ROUNDS = 1
DADA_MAX_ROUNDS = 5
DADA_ROLE_MAX_CHARS = 64
DADA_ROLE_PATTERN = (
    rf"^[A-Za-z0-9][A-Za-z0-9._ -]{{0,{DADA_ROLE_MAX_CHARS - 1}}}$"
)

ALLOWED_EVENT_ACTIONS = frozenset({
    "opened", "reopened", "synchronize", "ready_for_review",
})
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
API_REPOSITORY_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})/"
    r"[A-Za-z0-9_.-]{1,100}$"
)
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ROLE_RE = re.compile(DADA_ROLE_PATTERN)
MAX_API_BYTES = 4 * 1024 * 1024
API_PAGE_SIZE = 100
# GitHub documents a 3,000-file ceiling for the pull-request files endpoint.
MAX_CHANGED_FILES = 3000
MAX_PROTECTED_COMMITS = 1
TAKEDOWN_RESULT_PREFIX = "takedown:"


class AttestationError(Exception):
    """Raised when a reviewed PNG lacks trusted PR provenance."""


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key '{key}'")
        result[key] = value
    return result


def _reject_json_constant(value):
    raise ValueError(f"non-finite JSON number '{value}'")


def _decode_json(payload, label):
    try:
        return json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AttestationError(f"{label} is not strict JSON ({exc})") from exc


def _load_json(path, label):
    if not path:
        raise AttestationError(f"{label} path was not provided")
    try:
        before = os.lstat(path)
        if not stat.S_ISREG(before.st_mode):
            raise AttestationError(f"{label} must be a regular file")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            after = os.fstat(descriptor)
            if (
                not stat.S_ISREG(after.st_mode)
                or (before.st_dev, before.st_ino)
                != (after.st_dev, after.st_ino)
            ):
                raise AttestationError(f"{label} changed while opening")
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                payload = handle.read(MAX_API_BYTES + 1)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except AttestationError:
        raise
    except OSError as exc:
        raise AttestationError(f"cannot read {label} ({exc})") from exc
    if len(payload) > MAX_API_BYTES:
        raise AttestationError(
            f"{label} exceeds the {MAX_API_BYTES}-byte input limit"
        )
    return _decode_json(payload, label)


def _mapping(value, label):
    if not isinstance(value, dict):
        raise AttestationError(f"{label} must be an object")
    return value


def _list(value, label):
    if not isinstance(value, list):
        raise AttestationError(f"{label} must be an array")
    return value


def _text(value, label, max_chars=500):
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > max_chars
        or any(ord(char) < 0x20 for char in value)
    ):
        raise AttestationError(
            f"{label} must be a clean non-empty string of at most "
            f"{max_chars} characters"
        )
    return value


def _integer(value, label, minimum=0, maximum=1_000_000):
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise AttestationError(
            f"{label} must be an integer from {minimum} to {maximum}"
        )
    return value


def _production_controller_contract():
    return {
        "schema": CONTROLLER_CONTRACT_SCHEMA,
        "version": CONTROLLER_CONTRACT_VERSION,
        "identity": {
            "trusted_repository": TRUSTED_REPOSITORY,
            "trusted_owner": TRUSTED_OWNER,
            "trusted_contributor": TRUSTED_CONTRIBUTOR,
            "base_branch": TRUSTED_BASE_BRANCH,
            "author_association": TRUSTED_AUTHOR_ASSOCIATION,
            "collective_name": DADA_COLLECTIVE_NAME,
        },
        "branches": {
            "publication_prefix": DADA_BRANCH_PREFIX,
            "takedown_prefix": TAKEDOWN_BRANCH_PREFIX,
        },
        "commit": {
            "required_count": MAX_PROTECTED_COMMITS,
            "author": {
                "name": DADA_COMMIT_AUTHOR_NAME,
                "email": DADA_COMMIT_AUTHOR_EMAIL,
            },
            "committer": {
                "name": DADA_COMMITTER_NAME,
                "email": DADA_COMMITTER_EMAIL,
            },
            "subject_template": DADA_COMMIT_SUBJECT_TEMPLATE,
            "body_template": DADA_COMMIT_BODY_TEMPLATE,
        },
        "title": {
            "max_chars": build_index.REVIEWED_PNG_TITLE_MAX_CHARS,
            "pull_request_must_equal_commit_subject": True,
        },
        "role": {
            "pattern": DADA_ROLE_PATTERN,
            "max_chars": DADA_ROLE_MAX_CHARS,
        },
        "cycle": {
            "candidates_per_round": DADA_CANDIDATES_PER_ROUND,
            "min_rounds": DADA_MIN_ROUNDS,
            "max_rounds": DADA_MAX_ROUNDS,
        },
    }


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _require_controller_contract():
    contract = _mapping(
        _load_json(
            CONTROLLER_CONTRACT_PATH,
            "trusted Dada controller contract fixture",
        ),
        "trusted Dada controller contract fixture",
    )
    expected = _production_controller_contract()
    if _canonical_json(contract) != _canonical_json(expected):
        raise AttestationError(
            "trusted Dada controller contract fixture does not exactly match "
            "protected production constants"
        )
    return contract


def _sha(value, label):
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise AttestationError(f"{label} must be a lowercase 40-character SHA")
    return value


def _same_login(actual, expected):
    return isinstance(actual, str) and actual.casefold() == expected.casefold()


def _require_login(user, expected, label):
    user = _mapping(user, label)
    if not _same_login(user.get("login"), expected):
        raise AttestationError(f"{label}.login must be '{expected}'")
    if user.get("type") != "User":
        raise AttestationError(f"{label}.type must be 'User'")


def _repo_name(repo, label):
    repo = _mapping(repo, label)
    name = _text(repo.get("full_name"), f"{label}.full_name", 200)
    return name


def _require_trusted_base(repo, label):
    name = _repo_name(repo, label)
    if name.casefold() != TRUSTED_REPOSITORY.casefold():
        raise AttestationError(
            f"{label}.full_name must be '{TRUSTED_REPOSITORY}'"
        )


def _safe_repo_path(value, label):
    value = _text(value, label, 500)
    if (
        value.startswith("/")
        or "\\" in value
        or "//" in value
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise AttestationError(f"{label} is not a safe repository path")
    return value


def _changed_file_count(pr, label):
    count = _integer(
        _mapping(pr, label).get("changed_files"),
        f"{label}.changed_files",
    )
    if count > MAX_CHANGED_FILES:
        raise AttestationError(
            f"PR reports {count} changed files; GitHub's pull-request files "
            f"API exposes at most {MAX_CHANGED_FILES}"
        )
    return count


class GitHubApi:
    """Small bounded GitHub JSON client used only when no fixture is injected."""

    def __init__(self, base_url, token):
        self.base_url = str(base_url or "https://api.github.com").rstrip("/")
        if not token:
            raise AttestationError(
                "GITHUB_TOKEN is required when --api-fixture is not supplied"
            )
        self.token = token

    def get(self, path):
        request = urllib.request.Request(
            self.base_url + path,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "public-art-reviewed-png-gate/1",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read(MAX_API_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise AttestationError(
                f"GitHub API request failed with HTTP {exc.code}"
            ) from exc
        except urllib.error.URLError as exc:
            raise AttestationError(
                f"GitHub API request failed ({exc.reason})"
            ) from exc
        except TimeoutError as exc:
            raise AttestationError("GitHub API request timed out") from exc
        if len(payload) > MAX_API_BYTES:
            raise AttestationError("GitHub API response exceeded the input limit")
        return _decode_json(payload, "GitHub API response")

    def pages(self, path, expected_count, max_items, label):
        if expected_count > max_items:
            raise AttestationError(
                f"{label} count {expected_count} exceeds the bounded "
                f"{max_items}-item API limit"
            )
        if expected_count == 0:
            return []

        combined = []
        page_count = (expected_count + API_PAGE_SIZE - 1) // API_PAGE_SIZE
        for page in range(1, page_count + 1):
            separator = "&" if "?" in path else "?"
            value = self.get(
                f"{path}{separator}per_page={API_PAGE_SIZE}&page={page}"
            )
            rows = _list(value, "GitHub API page")
            if len(rows) > API_PAGE_SIZE:
                raise AttestationError(
                    f"GitHub API returned more than {API_PAGE_SIZE} "
                    f"{label} records on one page"
                )
            combined.extend(rows)
            if len(combined) > max_items:
                raise AttestationError(
                    f"GitHub API returned more than the bounded "
                    f"{max_items} {label} records"
                )
            if len(rows) < API_PAGE_SIZE:
                break
        return combined


def fetch_api_evidence(
    event,
    candidate_root,
    base_root,
    base_url=None,
    token=None,
):
    event_pr = _mapping(event.get("pull_request"), "event.pull_request")
    number = _integer(
        event.get("number", event_pr.get("number")),
        "event.number",
        1,
    )
    client = GitHubApi(base_url, token)
    prefix = f"/repos/{TRUSTED_REPOSITORY}/pulls/{number}"
    pull_request = _mapping(client.get(prefix), "api.pull_request")
    changed_file_count = _changed_file_count(
        pull_request, "api.pull_request"
    )
    files = client.pages(
        prefix + "/files",
        changed_file_count,
        MAX_CHANGED_FILES,
        "changed-file",
    )
    pull_request_after_files = _mapping(
        client.get(prefix), "api.pull_request_after_files"
    )
    _same_pr_value(
        _pr_fingerprint(pull_request, "api.pull_request"),
        _pr_fingerprint(
            pull_request_after_files,
            "api.pull_request_after_files",
        ),
        "current PR snapshot",
    )
    if len(files) != changed_file_count:
        raise AttestationError(
            "GitHub API changed-file evidence is incomplete: "
            f"PR reports {changed_file_count}, API returned {len(files)}"
        )

    candidate_root = _require_real_root(candidate_root, "candidate root")
    base_root = _require_real_root(base_root, "trusted base root")
    records = _changed_file_records(files)
    png_slugs = _png_submission_slugs(records, candidate_root, base_root)

    commits = None
    head_commit = None
    pull_request_after = pull_request_after_files
    if png_slugs:
        commit_count = _integer(
            pull_request.get("commits"),
            "api.pull_request.commits",
        )
        if commit_count != MAX_PROTECTED_COMMITS:
            raise AttestationError(
                "reviewed PNG PR must contain exactly one commit"
            )
        commits = client.pages(
            prefix + "/commits",
            commit_count,
            MAX_PROTECTED_COMMITS,
            "protected commit",
        )
        api_head = _mapping(
            pull_request.get("head"), "api.pull_request.head"
        )
        head_sha = _sha(
            api_head.get("sha"), "api.pull_request.head.sha"
        )
        head_repo = _repo_name(
            api_head.get("repo"), "api.pull_request.head.repo"
        )
        if not API_REPOSITORY_RE.fullmatch(head_repo):
            raise AttestationError(
                "api.pull_request.head.repo.full_name is not a safe GitHub "
                "owner/repository name"
            )
        encoded_head_repo = "/".join(
            quote(segment, safe="") for segment in head_repo.split("/")
        )
        head_commit = client.get(
            f"/repos/{encoded_head_repo}/commits/{head_sha}"
        )
        pull_request_after = client.get(prefix)

    return {
        "pull_request": pull_request,
        "commits": commits,
        "files": files,
        "head_commit": head_commit,
        # Re-read after every other endpoint so a head/base change during the
        # evidence collection window cannot inherit a success from stale data.
        "pull_request_after": pull_request_after,
    }


def _same_pr_value(event_value, api_value, label):
    if event_value != api_value:
        raise AttestationError(
            f"stale PR evidence: event/API {label} values differ"
        )


def _pr_fingerprint(pr, label):
    pr = _mapping(pr, label)
    base = _mapping(pr.get("base"), f"{label}.base")
    head = _mapping(pr.get("head"), f"{label}.head")
    return {
        "number": pr.get("number"),
        "state": pr.get("state"),
        "draft": pr.get("draft"),
        "title": pr.get("title"),
        "commits": pr.get("commits"),
        "changed_files": pr.get("changed_files"),
        "author_association": pr.get("author_association"),
        "user": _mapping(pr.get("user"), f"{label}.user").get("login"),
        "base_ref": base.get("ref"),
        "base_sha": base.get("sha"),
        "base_repo": _repo_name(base.get("repo"), f"{label}.base.repo"),
        "head_ref": head.get("ref"),
        "head_sha": head.get("sha"),
        "head_repo": _repo_name(head.get("repo"), f"{label}.head.repo"),
    }


def _validate_pr_snapshot(event, evidence):
    if event.get("action") not in ALLOWED_EVENT_ACTIONS:
        raise AttestationError("event action is not attested by this workflow")
    _require_trusted_base(event.get("repository"), "event.repository")

    event_pr = _mapping(event.get("pull_request"), "event.pull_request")
    api_pr = _mapping(evidence.get("pull_request"), "api.pull_request")
    api_pr_after = _mapping(
        evidence.get("pull_request_after"),
        "api.pull_request_after",
    )
    _same_pr_value(
        _pr_fingerprint(api_pr, "api.pull_request"),
        _pr_fingerprint(api_pr_after, "api.pull_request_after"),
        "current PR snapshot",
    )
    event_number = _integer(
        event.get("number", event_pr.get("number")),
        "event.number",
        1,
    )
    _same_pr_value(event_number, api_pr.get("number"), "PR number")
    if event_pr.get("state") != "open" or api_pr.get("state") != "open":
        raise AttestationError("the pull request must still be open")
    if event_pr.get("draft") is True or api_pr.get("draft") is True:
        raise AttestationError("draft pull requests are not attested")

    event_base = _mapping(event_pr.get("base"), "event.pull_request.base")
    api_base = _mapping(api_pr.get("base"), "api.pull_request.base")
    _require_trusted_base(event_base.get("repo"), "event.pull_request.base.repo")
    _require_trusted_base(api_base.get("repo"), "api.pull_request.base.repo")
    if (
        event_base.get("ref") != TRUSTED_BASE_BRANCH
        or api_base.get("ref") != TRUSTED_BASE_BRANCH
    ):
        raise AttestationError(
            f"PR base branch must be '{TRUSTED_BASE_BRANCH}'"
        )
    event_base_sha = _sha(
        event_base.get("sha"), "event.pull_request.base.sha"
    )
    api_base_sha = _sha(api_base.get("sha"), "api.pull_request.base.sha")
    _same_pr_value(event_base_sha, api_base_sha, "base SHA")

    event_head = _mapping(event_pr.get("head"), "event.pull_request.head")
    api_head = _mapping(api_pr.get("head"), "api.pull_request.head")
    event_head_sha = _sha(
        event_head.get("sha"), "event.pull_request.head.sha"
    )
    api_head_sha = _sha(api_head.get("sha"), "api.pull_request.head.sha")
    _same_pr_value(event_head_sha, api_head_sha, "head SHA")
    _same_pr_value(event_head.get("ref"), api_head.get("ref"), "head ref")
    _same_pr_value(
        _repo_name(event_head.get("repo"), "event.pull_request.head.repo"),
        _repo_name(api_head.get("repo"), "api.pull_request.head.repo"),
        "head repository",
    )
    event_user = _mapping(event_pr.get("user"), "event.pull_request.user")
    api_user = _mapping(api_pr.get("user"), "api.pull_request.user")
    _same_pr_value(event_user.get("login"), api_user.get("login"), "PR author")
    _same_pr_value(
        event_pr.get("author_association"),
        api_pr.get("author_association"),
        "author association",
    )
    _same_pr_value(event_pr.get("title"), api_pr.get("title"), "PR title")

    files = _list(evidence.get("files"), "api.files")
    api_commit_count = _integer(
        api_pr.get("commits"), "api.pull_request.commits"
    )
    event_commit_count = _integer(
        event_pr.get("commits"), "event.pull_request.commits"
    )
    _same_pr_value(
        event_commit_count, api_commit_count, "event commit count"
    )
    api_changed_file_count = _changed_file_count(
        api_pr, "api.pull_request"
    )
    event_changed_file_count = _changed_file_count(
        event_pr, "event.pull_request"
    )
    _same_pr_value(
        event_changed_file_count,
        api_changed_file_count,
        "event changed-file count",
    )
    if len(files) != api_changed_file_count:
        raise AttestationError(
            "GitHub API changed-file evidence is incomplete: "
            f"PR reports {api_changed_file_count}, API returned {len(files)}"
        )

    return {
        "event_pr": event_pr,
        "api_pr": api_pr,
        "event_head": event_head,
        "api_head": api_head,
        "base_sha": event_base_sha,
        "head_sha": event_head_sha,
        "commit_count": api_commit_count,
        "commits": evidence.get("commits"),
        "files": files,
        "head_commit": evidence.get("head_commit"),
    }


def _changed_file_records(files):
    records = {}
    for index, value in enumerate(files):
        record = _mapping(value, f"api.files[{index}]")
        filename = _safe_repo_path(
            record.get("filename"), f"api.files[{index}].filename"
        )
        if filename in records:
            raise AttestationError(
                f"GitHub API returned duplicate changed path '{filename}'"
            )
        status = _text(
            record.get("status"), f"api.files[{index}].status", 20
        )
        if status not in {"added", "modified", "removed", "renamed", "copied"}:
            raise AttestationError(
                f"api.files[{index}].status '{status}' is unsupported"
            )
        previous = record.get("previous_filename")
        if previous is not None:
            _safe_repo_path(
                previous, f"api.files[{index}].previous_filename"
            )
        records[filename] = record
    return records


def _require_real_root(root, label):
    root = os.path.abspath(root)
    try:
        mode = os.lstat(root).st_mode
    except OSError as exc:
        raise AttestationError(f"cannot inspect {label} ({exc})") from exc
    if not stat.S_ISDIR(mode):
        raise AttestationError(f"{label} must be a real directory")
    return root


def _validate_exact_submission(root, slug, label, license_value):
    """Validate one exact submissions/<slug>/ tree without touching siblings."""
    submissions = os.path.join(root, "submissions")
    try:
        return build_index.validate_submission(
            slug,
            license_value,
            submissions,
        )
    except build_index.ValidationError as exc:
        raise AttestationError(
            f"{label} failed trusted structural validation: {exc}"
        ) from exc


def _path_submission_slug(path):
    parts = path.split("/")
    if len(parts) >= 3 and parts[0] == "submissions":
        slug = parts[1]
        if SLUG_RE.fullmatch(slug):
            return slug
    return None


def _png_submission_slugs(records, candidate_root, base_root):
    """Return PNG-affecting slugs based only on the touched paths themselves."""
    slugs = set()
    for filename, record in records.items():
        paths = [filename]
        if record.get("previous_filename") is not None:
            paths.append(record["previous_filename"])
        for path in paths:
            slug = _path_submission_slug(path)
            if not slug:
                continue
            if path.endswith("/piece.png"):
                slugs.add(slug)
                continue
            base_piece = os.path.join(
                base_root, "submissions", slug, "piece.png"
            )
            candidate_piece = os.path.join(
                candidate_root, "submissions", slug, "piece.png"
            )
            if os.path.lexists(base_piece) or os.path.lexists(candidate_piece):
                slugs.add(slug)
    return slugs


def _load_candidate_meta(candidate_root, slug):
    path = os.path.join(candidate_root, "submissions", slug, "meta.json")
    try:
        return build_index._load_json(
            path, strict=True, no_follow=True
        )
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise AttestationError(
            f"{slug}: cannot re-read candidate meta.json ({exc})"
        ) from exc


def _git_blob_sha1(path):
    try:
        with build_index._open_regular_no_follow(path, binary=True) as handle:
            payload = handle.read(build_index.PNG_MAX_FILE_BYTES + 1)
    except OSError as exc:
        raise AttestationError(
            f"cannot hash repository file '{path}' ({exc})"
        ) from exc
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def _require_owner_origin(context):
    event_pr = context["event_pr"]
    api_pr = context["api_pr"]
    event_head = context["event_head"]
    api_head = context["api_head"]

    for head, label in (
        (event_head, "event.pull_request.head"),
        (api_head, "api.pull_request.head"),
    ):
        repo = _mapping(head.get("repo"), f"{label}.repo")
        if _repo_name(repo, f"{label}.repo").casefold() != (
            TRUSTED_REPOSITORY.casefold()
        ):
            raise AttestationError(
                "reviewed PNG PRs must originate in the pinned owner repository"
            )
        if repo.get("fork") is not False:
            raise AttestationError(
                "reviewed PNG PR head repository must not be a fork"
            )
        _require_login(repo.get("owner"), TRUSTED_OWNER, f"{label}.repo.owner")

    for pr, label in (
        (event_pr, "event.pull_request"),
        (api_pr, "api.pull_request"),
    ):
        _require_login(pr.get("user"), TRUSTED_OWNER, f"{label}.user")
        if pr.get("author_association") != TRUSTED_AUTHOR_ASSOCIATION:
            raise AttestationError(
                f"{label}.author_association must be "
                f"'{TRUSTED_AUTHOR_ASSOCIATION}'"
            )


def _require_operation_branch(context, branch_prefix, slug):
    event_head = context["event_head"]
    branch_pattern = re.compile(
        rf"^{re.escape(branch_prefix)}/{re.escape(slug)}-[0-9a-f]{{8}}$"
    )
    if not branch_pattern.fullmatch(event_head.get("ref", "")):
        raise AttestationError(
            f"reviewed PNG head branch must match "
            f"'{branch_prefix}/{slug}-<8 lowercase hex>'"
        )


def _require_owner_png_pr(context, records, candidate_root, slug, contributor):
    _require_owner_origin(context)
    _require_operation_branch(context, DADA_BRANCH_PREFIX, slug)

    expected_paths = {
        f"submissions/{slug}/meta.json",
        f"submissions/{slug}/piece.png",
    }
    if set(records) != expected_paths:
        raise AttestationError(
            "reviewed PNG PR must add exactly meta.json and piece.png for "
            f"'{slug}'"
        )
    for path in sorted(expected_paths):
        record = records[path]
        if record.get("status") != "added":
            raise AttestationError(
                f"reviewed PNG path '{path}' must have status 'added'"
            )
        api_blob = _sha(record.get("sha"), f"api file blob SHA for {path}")
        checkout_path = os.path.join(candidate_root, *path.split("/"))
        if _git_blob_sha1(checkout_path) != api_blob:
            raise AttestationError(
                f"stale PR evidence: API blob SHA for '{path}' does not "
                "match the checked-out head"
            )

    if contributor != TRUSTED_CONTRIBUTOR:
        raise AttestationError(
            f"{slug}: reviewed PNG contributor must be "
            f"'{TRUSTED_CONTRIBUTOR}'"
        )


def _require_owner_png_takedown(
    context,
    records,
    candidate_root,
    base_root,
    slug,
    license_value,
):
    _require_owner_origin(context)
    _require_operation_branch(context, TAKEDOWN_BRANCH_PREFIX, slug)

    candidate_slug = os.path.join(candidate_root, "submissions", slug)
    if os.path.lexists(candidate_slug):
        raise AttestationError(
            f"reviewed PNG takedown must leave '{candidate_slug}' absent"
        )

    expected_paths = {
        f"submissions/{slug}/meta.json",
        f"submissions/{slug}/piece.png",
    }
    if set(records) != expected_paths:
        raise AttestationError(
            "reviewed PNG takedown must remove exactly meta.json and "
            f"piece.png for '{slug}'"
        )

    base_entry = _validate_exact_submission(
        base_root,
        slug,
        "trusted base submission tree",
        license_value,
    )
    if (
        base_entry.get("kind") != "png"
        or base_entry.get("contributor") != TRUSTED_CONTRIBUTOR
        or base_entry.get("meta_path")
        != f"submissions/{slug}/meta.json"
        or base_entry.get("piece_path")
        != f"submissions/{slug}/piece.png"
    ):
        raise AttestationError(
            f"{slug}: trusted base is not a valid reviewed PNG submission"
        )

    for path in sorted(expected_paths):
        record = records[path]
        if record.get("status") != "removed":
            raise AttestationError(
                f"reviewed PNG takedown path '{path}' must have status "
                "'removed'"
            )
        if record.get("previous_filename") is not None:
            raise AttestationError(
                "reviewed PNG takedown does not permit renames or copies"
            )
        api_blob = _sha(
            record.get("sha"), f"api base blob SHA for {path}"
        )
        base_path = os.path.join(base_root, *path.split("/"))
        if _git_blob_sha1(base_path) != api_blob:
            raise AttestationError(
                f"stale PR evidence: API base blob SHA for '{path}' does "
                "not match the trusted base"
            )


def _require_protected_commit_evidence(context, operation):
    if context["commit_count"] != MAX_PROTECTED_COMMITS:
        raise AttestationError(
            f"{operation} must contain exactly one commit"
        )
    commits = _list(context["commits"], "api.commits")
    if len(commits) != MAX_PROTECTED_COMMITS:
        raise AttestationError(
            f"{operation} exact-one-commit evidence is incomplete"
        )
    head_commit = _mapping(context["head_commit"], "api.head_commit")
    return commits[0], head_commit


def _validate_commit_envelope(record, context, label, operation):
    record = _mapping(record, label)
    if _sha(record.get("sha"), f"{label}.sha") != context["head_sha"]:
        raise AttestationError(f"{label} is not the exact PR head commit")
    parents = _list(record.get("parents"), f"{label}.parents")
    if len(parents) != 1:
        raise AttestationError(
            f"{operation} PR must have exactly one parent"
        )
    parent = _mapping(parents[0], f"{label}.parents[0]")
    if _sha(parent.get("sha"), f"{label}.parents[0].sha") != context["base_sha"]:
        raise AttestationError(
            f"stale PR provenance: {operation} commit parent is not the "
            "current base SHA"
        )

    commit = _mapping(record.get("commit"), f"{label}.commit")
    verification = _mapping(
        commit.get("verification"), f"{label}.commit.verification"
    )
    verified = verification.get("verified")
    reason = verification.get("reason")
    if verified is not True and not (verified is False and reason == "unsigned"):
        raise AttestationError(
            "head commit has a failed or indeterminate GitHub signature status"
        )
    return record, commit


def _validate_commit_record(record, context, expected_message, label):
    record, commit = _validate_commit_envelope(
        record, context, label, "Dada controller"
    )
    _require_login(record.get("author"), TRUSTED_OWNER, f"{label}.author")
    _require_login(record.get("committer"), TRUSTED_OWNER, f"{label}.committer")
    author = _mapping(commit.get("author"), f"{label}.commit.author")
    committer = _mapping(commit.get("committer"), f"{label}.commit.committer")
    for identity, identity_label, expected_identity in (
        (
            author,
            f"{label}.commit.author",
            {
                "name": DADA_COMMIT_AUTHOR_NAME,
                "email": DADA_COMMIT_AUTHOR_EMAIL,
            },
        ),
        (
            committer,
            f"{label}.commit.committer",
            {
                "name": DADA_COMMITTER_NAME,
                "email": DADA_COMMITTER_EMAIL,
            },
        ),
    ):
        for field, expected in expected_identity.items():
            if identity.get(field) != expected:
                raise AttestationError(
                    f"{identity_label}.{field} must be {expected!r}"
                )
        _text(identity.get("date"), f"{identity_label}.date", 64)
    if author.get("date") != committer.get("date"):
        raise AttestationError(
            "Dada controller author and committer dates must be identical"
        )
    if _canonical_commit_message(commit.get("message")) != expected_message:
        raise AttestationError(
            "Dada controller commit message does not match submission evidence"
        )


def _validate_takedown_commit_record(record, context, label):
    record, commit = _validate_commit_envelope(
        record, context, label, "reviewed PNG takedown"
    )
    _require_login(record.get("author"), TRUSTED_OWNER, f"{label}.author")
    _require_login(record.get("committer"), TRUSTED_OWNER, f"{label}.committer")
    if _canonical_commit_message(commit.get("message")) is None:
        raise AttestationError(
            "reviewed PNG takedown commit message is not bounded canonical text"
        )


def _expected_controller_message(title, meta, slug):
    cycle_data = _mapping(meta.get("_dada_cycle"), f"{slug}: _dada_cycle")
    cycle = _integer(
        cycle_data.get("cycle"), f"{slug}: _dada_cycle.cycle", 1
    )
    rounds = _list(
        cycle_data.get("rounds"), f"{slug}: _dada_cycle.rounds"
    )
    if not DADA_MIN_ROUNDS <= len(rounds) <= DADA_MAX_ROUNDS:
        raise AttestationError(
            f"{slug}: _dada_cycle.rounds must contain "
            f"{DADA_MIN_ROUNDS}-{DADA_MAX_ROUNDS} rounds"
        )
    subject = DADA_COMMIT_SUBJECT_TEMPLATE.format(title=title, slug=slug)
    body = DADA_COMMIT_BODY_TEMPLATE.format(
        role="{role}",
        collective_name=DADA_COLLECTIVE_NAME,
        cycle=cycle,
        rounds=len(rounds),
        candidates_per_round=DADA_CANDIDATES_PER_ROUND,
    )
    return f"{subject}\n\n{body}"


def _canonical_commit_message(value):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2000
        or "\r" in value
        or value.endswith("\n\n")
    ):
        return None
    return value[:-1] if value.endswith("\n") else value


def _match_controller_message(actual, template):
    actual = _canonical_commit_message(actual)
    if actual is None:
        return None
    prefix, suffix = template.split("{role}", 1)
    if not actual.startswith(prefix):
        return None
    remainder = actual[len(prefix):]
    if not remainder.endswith(suffix):
        return None
    role = remainder[:len(remainder) - len(suffix)]
    if not ROLE_RE.fullmatch(role):
        return None
    return template.replace("{role}", role)


def _require_current_trusted_base(context, trusted_base_sha):
    checkout_sha = _sha(
        trusted_base_sha, "trusted protected-main checkout SHA"
    )
    if checkout_sha != context["base_sha"]:
        raise AttestationError(
            "stale trusted base evidence: protected-main checkout SHA does "
            "not match the current PR base SHA"
        )


def verify(
    event,
    evidence,
    candidate_root,
    base_root,
    trusted_base_sha=None,
):
    """Return a submission slug, takedown marker, or None for a non-PNG PR."""
    _require_controller_contract()
    candidate_root = _require_real_root(candidate_root, "candidate root")
    base_root = _require_real_root(base_root, "trusted base root")
    context = _validate_pr_snapshot(event, evidence)
    records = _changed_file_records(context["files"])
    png_slugs = _png_submission_slugs(records, candidate_root, base_root)
    if not png_slugs:
        return None
    if len(png_slugs) != 1:
        raise AttestationError(
            "a reviewed PNG PR must affect exactly one PNG slug"
        )

    slug = next(iter(png_slugs))
    _require_current_trusted_base(context, trusted_base_sha)
    license_value = build_index.accepted_license(
        os.path.join(base_root, "neighborhood.json")
    )
    candidate_slug = os.path.join(candidate_root, "submissions", slug)
    if not os.path.lexists(candidate_slug):
        _require_owner_png_takedown(
            context,
            records,
            candidate_root,
            base_root,
            slug,
            license_value,
        )
        commit_record, head_commit = _require_protected_commit_evidence(
            context, "reviewed PNG takedown PR"
        )
        _validate_takedown_commit_record(
            commit_record,
            context,
            "api.commits[0]",
        )
        _validate_takedown_commit_record(
            head_commit,
            context,
            "api.head_commit",
        )
        return TAKEDOWN_RESULT_PREFIX + slug

    entry = _validate_exact_submission(
        candidate_root,
        slug,
        "candidate submission tree",
        license_value,
    )
    if entry.get("kind") != "png":
        raise AttestationError(
            f"{slug}: changed PNG does not form a valid PNG submission"
        )
    meta = _load_candidate_meta(candidate_root, slug)
    _require_owner_png_pr(
        context,
        records,
        candidate_root,
        slug,
        entry.get("contributor"),
    )

    commit_record, head_commit = _require_protected_commit_evidence(
        context, "Dada controller PNG PR"
    )
    message_template = _expected_controller_message(
        entry["title"],
        meta,
        slug,
    )
    commit_message = _mapping(
        commit_record.get("commit"), "api.commits[0].commit"
    ).get("message")
    expected_message = _match_controller_message(
        commit_message, message_template
    )
    if expected_message is None:
        raise AttestationError(
            "Dada controller commit message has the wrong exact provenance form"
        )
    if context["api_pr"].get("title") != expected_message.splitlines()[0]:
        raise AttestationError(
            "Dada controller PR title must equal the commit subject"
        )
    _validate_commit_record(
        commit_record,
        context,
        expected_message,
        "api.commits[0]",
    )
    _validate_commit_record(
        head_commit,
        context,
        expected_message,
        "api.head_commit",
    )
    return slug


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--event-path",
        default=os.environ.get("GITHUB_EVENT_PATH"),
        help="pull_request_target event JSON (defaults to GITHUB_EVENT_PATH)",
    )
    parser.add_argument(
        "--api-fixture",
        help=(
            "offline JSON containing pull_request, commits, files, "
            "head_commit, and pull_request_after"
        ),
    )
    parser.add_argument(
        "--candidate-root",
        default=build_index.REPO_ROOT,
        help="PR head checkout root, treated only as untrusted data",
    )
    parser.add_argument(
        "--base-root",
        default=build_index.REPO_ROOT,
        help="trusted base checkout root",
    )
    parser.add_argument(
        "--trusted-base-sha",
        default=os.environ.get("TRUSTED_BASE_SHA"),
        help=(
            "HEAD SHA of the trusted protected-main checkout; required when "
            "a reviewed PNG is changed"
        ),
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
        help="GitHub API base URL",
    )
    args = parser.parse_args(argv)

    try:
        event = _mapping(
            _load_json(args.event_path, "GitHub event"),
            "GitHub event",
        )
        if args.api_fixture:
            evidence = _mapping(
                _load_json(args.api_fixture, "GitHub API fixture"),
                "GitHub API fixture",
            )
        else:
            evidence = fetch_api_evidence(
                event,
                args.candidate_root,
                args.base_root,
                base_url=args.api_url,
                token=os.environ.get("GITHUB_TOKEN"),
            )
        result = verify(
            event,
            evidence,
            args.candidate_root,
            args.base_root,
            args.trusted_base_sha,
        )
    except AttestationError as exc:
        print(f"error: reviewed PNG provenance rejected: {exc}", file=sys.stderr)
        return 1

    if result is None:
        print("no reviewed PNG change; provenance check not applicable")
    elif result.startswith(TAKEDOWN_RESULT_PREFIX):
        slug = result[len(TAKEDOWN_RESULT_PREFIX):]
        print(
            f"reviewed PNG takedown authorized for '{slug}' at "
            f"{event['pull_request']['head']['sha']}"
        )
    else:
        print(
            f"reviewed PNG provenance attested for '{result}' at "
            f"{event['pull_request']['head']['sha']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
