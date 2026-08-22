#!/usr/bin/env python3
"""build_index.py — deterministic builder/validator for submissions/index.json.

Scans every submissions/<slug>/ directory, validates each meta.json against the
rapp-art-submission/1.0 protocol (specs/SUBMISSION_PROTOCOL.md), and produces a
submissions/index.json that deterministically includes every valid submission —
regardless of merge order, filesystem listing order, or how many submissions
landed since the index was last regenerated.

No third-party dependencies: stdlib only (json, os, re, argparse).

Usage:
  python3 tools/build_index.py              # validate + check index is current (default)
  python3 tools/build_index.py --check      # same as above, explicit
  python3 tools/build_index.py --validate   # validate every submission only; index staleness is NOT an error
  python3 tools/build_index.py --write      # validate, then write index.json if it changed

--validate vs --check: a submission PR that only adds submissions/<new-slug>/
is *expected* to leave submissions/index.json stale until CI regenerates it
after merge — that's the whole point of this tool. --validate is the
fail-closed mode CI uses on both pull_request and push: every submission must
still validate, but staleness of index.json is not itself a failure, so
validate never deadlocks against the regenerate-on-push job that depends on
it. --check additionally asserts the index is byte-identical to what a fresh
build would produce; it's for operators/tests/local runs that want to catch
"someone hand-edited index.json and it drifted."

Exit codes:
  0  every submission validates (and, in --check mode, index.json is current)
  1  a submission failed validation, or (in --check mode only) index.json is stale/missing
"""
import argparse
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUBMISSIONS_DIR = os.path.join(REPO_ROOT, "submissions")
INDEX_PATH = os.path.join(SUBMISSIONS_DIR, "index.json")
NEIGHBORHOOD_PATH = os.path.join(REPO_ROOT, "neighborhood.json")

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# kind -> required piece extension, per specs/SUBMISSION_PROTOCOL.md.
KIND_EXTENSIONS = {
    "md": "md",
    "txt": "txt",
    "text": "md",
    "ascii": "txt",
    "svg": "svg",
    "prompt": "md",
    "json": "json",
    "png": "png",
}

REQUIRED_META_FIELDS = (
    "schema", "title", "slug", "contributor", "kind", "submitted_at", "remix_of", "license",
)
EXPECTED_META_SCHEMA = "rapp-art-submission/1.0"
DEFAULT_INDEX_SCHEMA = "rapp-art-submissions-index/1.0"
DEFAULT_LICENSE = "CC0-1.0"

# Top-level index.json fields that are configuration/identity, not derived from
# submissions. These are always carried over verbatim from the existing file so
# regeneration never clobbers neighborhood/rappid metadata.
PRESERVED_TOP_LEVEL_ORDER = ("schema", "neighborhood_rappid", "_migrated_from")


class ValidationError(Exception):
    """Raised when one or more submissions/<slug>/ directories fail validation."""


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def accepted_license():
    """Read the accepted license from neighborhood.json::contribution_policy.license.

    Falls back to DEFAULT_LICENSE if the file/field is missing or unparsable, so
    the tool keeps working even in a minimal checkout (e.g. isolated test fixtures).
    """
    try:
        policy = (_load_json(NEIGHBORHOOD_PATH).get("contribution_policy") or {})
        raw = (policy.get("license") or "").strip()
        token = raw.split()[0] if raw else ""
        return token or DEFAULT_LICENSE
    except (FileNotFoundError, ValueError, OSError, IndexError):
        return DEFAULT_LICENSE


def discover_submission_dirs(submissions_dir=SUBMISSIONS_DIR):
    """Return every directory name directly under submissions/, sorted for determinism.

    Non-directories (e.g. index.json) and dotfiles are skipped.
    """
    if not os.path.isdir(submissions_dir):
        return []
    slugs = [
        entry for entry in os.listdir(submissions_dir)
        if not entry.startswith(".") and os.path.isdir(os.path.join(submissions_dir, entry))
    ]
    return sorted(slugs)


def validate_submission(slug, license_value, submissions_dir=SUBMISSIONS_DIR):
    """Validate one submissions/<slug>/ directory and return its index entry.

    Raises ValidationError with a human-readable message on the first failure.
    """
    dir_path = os.path.join(submissions_dir, slug)

    if not SLUG_RE.match(slug):
        raise ValidationError(
            f"{slug}: directory name is not a valid slug (lowercase alphanumeric + hyphens)"
        )

    meta_path = os.path.join(dir_path, "meta.json")
    if not os.path.isfile(meta_path):
        raise ValidationError(f"{slug}: missing meta.json")

    try:
        meta = _load_json(meta_path)
    except ValueError as e:
        raise ValidationError(f"{slug}: meta.json is not valid JSON ({e})")

    if not isinstance(meta, dict):
        raise ValidationError(f"{slug}: meta.json must be a JSON object")

    for field in REQUIRED_META_FIELDS:
        if field not in meta:
            raise ValidationError(f"{slug}: meta.json missing required field '{field}'")

    if meta["schema"] != EXPECTED_META_SCHEMA:
        raise ValidationError(
            f"{slug}: unsupported schema '{meta['schema']}' (expected '{EXPECTED_META_SCHEMA}')"
        )

    # slug/path match: the folder name IS the identity; meta.slug must agree.
    if meta["slug"] != slug:
        raise ValidationError(
            f"{slug}: meta.json slug '{meta['slug']}' does not match directory name"
        )

    kind = meta["kind"]
    if kind not in KIND_EXTENSIONS:
        raise ValidationError(
            f"{slug}: unsupported kind '{kind}' (expected one of {sorted(KIND_EXTENSIONS)})"
        )

    ext = KIND_EXTENSIONS[kind]
    piece_name = f"piece.{ext}"
    piece_path = os.path.join(dir_path, piece_name)
    if not os.path.isfile(piece_path):
        raise ValidationError(
            f"{slug}: missing required piece file '{piece_name}' for kind '{kind}'"
        )

    if meta["license"] != license_value:
        raise ValidationError(
            f"{slug}: license '{meta['license']}' does not match accepted license '{license_value}'"
        )

    if not isinstance(meta.get("title"), str) or not meta["title"].strip():
        raise ValidationError(f"{slug}: title must be a non-empty string")
    if not isinstance(meta.get("contributor"), str) or not meta["contributor"].strip():
        raise ValidationError(f"{slug}: contributor must be a non-empty string")
    if not isinstance(meta.get("submitted_at"), str) or not meta["submitted_at"].strip():
        raise ValidationError(f"{slug}: submitted_at must be a non-empty string")

    return {
        "slug": slug,
        "title": meta["title"],
        "contributor": meta["contributor"],
        "kind": kind,
        "submitted_at": meta["submitted_at"],
        "license": meta["license"],
        "meta_path": f"submissions/{slug}/meta.json",
        "piece_path": f"submissions/{slug}/{piece_name}",
    }


def build_entries(submissions_dir=SUBMISSIONS_DIR, license_value=None):
    """Validate every submission directory; return deterministically ordered index entries.

    Order: submitted_at ascending, slug ascending as a tiebreak — independent of
    filesystem listing order or merge order, so repeated runs on the same tree
    always produce byte-identical output.

    Collects every validation failure (missing piece, bad license, duplicate
    slug, etc.) before raising, so a single ValidationError reports everything
    wrong with the tree in one pass.
    """
    license_value = license_value if license_value is not None else accepted_license()
    slugs = discover_submission_dirs(submissions_dir)

    seen_slugs = set()
    entries = []
    errors = []
    for slug in slugs:
        try:
            entry = validate_submission(slug, license_value, submissions_dir)
        except ValidationError as e:
            errors.append(str(e))
            continue
        if entry["slug"] in seen_slugs:
            errors.append(f"{slug}: duplicate slug")
            continue
        seen_slugs.add(entry["slug"])
        entries.append(entry)

    if errors:
        raise ValidationError("; ".join(errors))

    entries.sort(key=lambda e: (e["submitted_at"], e["slug"]))
    return entries


def build_index_document(entries, index_path=INDEX_PATH):
    """Merge freshly validated entries into the existing index document.

    Every non-derived top-level field (schema, neighborhood_rappid,
    _migrated_from, note, and any future field) is preserved verbatim from the
    existing file; only `submissions` is replaced.
    """
    existing = {}
    if os.path.isfile(index_path):
        existing = _load_json(index_path)

    doc = dict(existing)
    doc.setdefault("schema", DEFAULT_INDEX_SCHEMA)

    ordered = {}
    for key in PRESERVED_TOP_LEVEL_ORDER:
        if key in doc:
            ordered[key] = doc[key]
    for key, value in doc.items():
        if key not in ordered and key != "submissions" and key != "note":
            ordered[key] = value
    ordered["submissions"] = entries
    if "note" in doc:
        ordered["note"] = doc["note"]
    else:
        ordered["note"] = (
            "This index is generated from submissions/<slug>/meta.json files by "
            "tools/build_index.py. Do not hand-edit; regenerate instead."
        )
    return ordered


def render(doc):
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true",
        help="Validate + require index.json to be current; exit 1 if invalid OR stale/missing (default)",
    )
    mode.add_argument(
        "--validate", action="store_true",
        help="Validate every submission only; exit 1 if invalid, but a stale/missing index.json is NOT an error",
    )
    mode.add_argument(
        "--write", action="store_true",
        help="Validate, then write submissions/index.json if regeneration would change it",
    )
    parser.add_argument(
        "--submissions-dir", default=SUBMISSIONS_DIR,
        help="Override submissions/ directory (mainly for tests)",
    )
    parser.add_argument(
        "--index-path", default=None,
        help="Override submissions/index.json path (mainly for tests)",
    )
    args = parser.parse_args(argv)

    submissions_dir = args.submissions_dir
    index_path = args.index_path or os.path.join(submissions_dir, "index.json")

    try:
        entries = build_entries(submissions_dir)
    except ValidationError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.validate:
        # Fail-closed on submissions only. Deliberately does not look at
        # index.json at all — a submission-only PR is expected to leave it
        # stale, and that must never be a failure here (see module docstring).
        print(f"all submissions valid ({len(entries)} submissions)")
        return 0

    doc = build_index_document(entries, index_path)
    rendered = render(doc)

    current = None
    if os.path.isfile(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            current = f.read()

    if args.write:
        if current == rendered:
            print(f"submissions/index.json already up to date ({len(entries)} submissions)")
            return 0
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(rendered)
        print(f"submissions/index.json regenerated ({len(entries)} submissions)")
        return 0

    # --check (default): validate only, never write.
    if current != rendered:
        print(
            "submissions/index.json is stale or missing relative to submissions/*/meta.json. "
            "Run `python3 tools/build_index.py --write` to regenerate.",
            file=sys.stderr,
        )
        return 1
    print(f"submissions/index.json is valid and up to date ({len(entries)} submissions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
