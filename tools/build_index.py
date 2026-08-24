#!/usr/bin/env python3
"""build_index.py — deterministic builder/validator for submissions/index.json.

Scans every submissions/<slug>/ directory, validates each meta.json against the
rapp-art-submission/1.0 protocol (specs/SUBMISSION_PROTOCOL.md), and produces a
submissions/index.json that deterministically includes every valid submission —
regardless of merge order, filesystem listing order, or how many submissions
landed since the index was last regenerated.

No third-party dependencies: stdlib only.

Usage:
  python3 tools/build_index.py              # validate + check index is current (default)
  python3 tools/build_index.py --check      # same as above, explicit
  python3 tools/build_index.py --validate   # validate every submission only; index staleness is NOT an error
  python3 tools/build_index.py --write      # validate, then write index.json if it changed

Missing submissions/index.json may be generated. A malformed, unreadable, or
identity-drifted existing submissions/index.json fails closed instead of being
silently overwritten.

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
import hashlib
import json
import os
import re
import stat
import struct
import sys
import zlib

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
RAPPID_RE = re.compile(
    r"^rappid:@[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*:"
    r"[0-9a-f]{32}(?:[0-9a-f]{32})?$"
)

# PNG acceptance is deliberately narrower than the full PNG specification.
# These bounds keep both parsing and decompression finite while covering the
# reviewed 1536x1024 images produced by the Dada controller.
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_MAX_FILE_BYTES = 32 * 1024 * 1024
PNG_MAX_CHUNK_BYTES = PNG_MAX_FILE_BYTES
PNG_MAX_CHUNKS = 10_000
PNG_MAX_WIDTH = 4096
PNG_MAX_HEIGHT = 4096
PNG_MAX_PIXELS = 16_000_000
PNG_SUPPORTED_COLOR_TYPES = {2: 3, 6: 4}  # 8-bit RGB and RGBA.
PNG_KNOWN_CRITICAL_CHUNKS = {b"IHDR", b"PLTE", b"IDAT", b"IEND"}
REVIEWED_PNG_TITLE_MAX_CHARS = 200
REVIEWED_PNG_TRUSTED_CONTRIBUTOR = "kody-w"

IMAGE_GENERATION_SCHEMA = "rapp-image-generation/1.0"
IMAGE_GENERATION_PROFILE = "azure-reviewed-png"
IMAGE_REVIEW_SCHEMA = "rapp-image-review/1.0"
IMAGE_PROVIDER = "azure-openai"
IMAGE_MAX_ATTEMPTS = 5
IMAGE_MAX_IDENTIFIER_CHARS = 100
IMAGE_MAX_STRENGTHS = 8
IMAGE_MAX_STRENGTH_CHARS = 240
IMAGE_GENERATION_FIELDS = frozenset({
    "schema", "profile", "provider", "deployment", "attempts",
    "image_sha256", "image", "review",
})
IMAGE_FIELDS = frozenset({"width", "height"})
IMAGE_REVIEW_FIELDS = frozenset({
    "schema", "model", "score", "minimum_score", "publish",
    "failures", "strengths",
})
IMAGE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
RAW_CREDENTIAL_RE = re.compile(
    r"(?i)(?:"
    r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}|"
    r"\b(?:gh[pousr]_|github_pat_|sk-)[A-Za-z0-9_-]{8,}|"
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|"
    r"\b(?:api[ _-]?key|access[ _-]?token|client[ _-]?secret|password)"
    r"\s*[:=]\s*\S+|"
    r"[?&](?:sig|token|key)=[^&\s]+"
    r")"
)
CREDENTIAL_KEY_NAMES = frozenset({
    "apikey", "accesstoken", "refreshtoken", "token", "credential",
    "credentials", "password", "secret", "clientsecret", "authorization",
})

# Top-level index.json fields that are configuration/identity, not derived from
# submissions. These are always carried over verbatim from the existing file so
# regeneration never clobbers neighborhood/rappid metadata.
INDEX_IDENTITY_FIELDS = ("neighborhood_rappid", "_migrated_from")
PRESERVED_TOP_LEVEL_ORDER = ("schema",) + INDEX_IDENTITY_FIELDS


class ValidationError(Exception):
    """Raised when one or more submissions/<slug>/ directories fail validation."""


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key '{key}'")
        result[key] = value
    return result


def _reject_json_constant(value):
    raise ValueError(f"non-finite JSON number '{value}'")


def _open_regular_no_follow(path, binary=False):
    """Open one already-validated regular file without traversing symlinks."""
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode):
        raise OSError(f"not a regular file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        after = os.fstat(fd)
        if (
            not stat.S_ISREG(after.st_mode)
            or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
        ):
            raise OSError(f"file changed while opening: {path}")
        if binary:
            return os.fdopen(fd, "rb")
        return os.fdopen(fd, "r", encoding="utf-8")
    except Exception:
        os.close(fd)
        raise


def _load_json(path, strict=False, no_follow=False):
    opener = _open_regular_no_follow if no_follow else (
        lambda target: open(target, "r", encoding="utf-8")
    )
    with opener(path) as f:
        if strict:
            return json.load(
                f,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_json_constant,
            )
        return json.load(f)


def neighborhood_path_for_submissions(submissions_dir):
    return os.path.join(
        os.path.dirname(os.path.abspath(submissions_dir)),
        "neighborhood.json",
    )


def accepted_license(neighborhood_path=NEIGHBORHOOD_PATH):
    """Read the accepted license from neighborhood.json::contribution_policy.license.

    Falls back to DEFAULT_LICENSE if the file/field is missing or unparsable, so
    the tool keeps working even in a minimal checkout (e.g. isolated test fixtures).
    """
    try:
        policy = (_load_json(neighborhood_path).get("contribution_policy") or {})
        raw = (policy.get("license") or "").strip()
        token = raw.split()[0] if raw else ""
        return token or DEFAULT_LICENSE
    except (FileNotFoundError, ValueError, OSError, IndexError):
        return DEFAULT_LICENSE


def _entry_type(mode):
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISREG(mode):
        return "regular file"
    if stat.S_ISDIR(mode):
        return "directory"
    return "special file"


def _display_index_path(index_path, submissions_dir):
    if os.path.abspath(os.path.dirname(index_path)) == os.path.abspath(submissions_dir):
        return "submissions/index.json"
    return index_path


def _display_neighborhood_path(neighborhood_path):
    if os.path.basename(neighborhood_path) == "neighborhood.json":
        return "neighborhood.json"
    return neighborhood_path


def _validate_neighborhood_rappid(value, source_label):
    if not isinstance(value, str) or not RAPPID_RE.fullmatch(value):
        raise ValidationError(
            f"{source_label} neighborhood_rappid must be a canonical rappid string"
        )
    return value


def _validate_migrated_from(value, source_label):
    if not isinstance(value, dict):
        raise ValidationError(f"{source_label} _migrated_from must be a JSON object")
    migrated = value.get("neighborhood_rappid")
    if not isinstance(migrated, str) or not migrated.strip():
        raise ValidationError(
            f"{source_label} _migrated_from.neighborhood_rappid must be a non-empty string"
        )
    return value


def _load_canonical_index_identity(submissions_dir):
    neighborhood_path = neighborhood_path_for_submissions(submissions_dir)
    neighborhood_label = _display_neighborhood_path(neighborhood_path)
    try:
        neighborhood = _load_json(
            neighborhood_path,
            strict=True,
            no_follow=True,
        )
    except FileNotFoundError:
        return None
    except ValueError as e:
        raise ValidationError(f"{neighborhood_label} is not valid JSON ({e})")
    except OSError as e:
        raise ValidationError(f"cannot read {neighborhood_label} ({e})")

    if not isinstance(neighborhood, dict):
        raise ValidationError(f"{neighborhood_label} must be a JSON object")

    identity = {}
    if "neighborhood_rappid" in neighborhood:
        identity["neighborhood_rappid"] = _validate_neighborhood_rappid(
            neighborhood["neighborhood_rappid"],
            neighborhood_label,
        )
    if "_migrated_from" in neighborhood:
        identity["_migrated_from"] = _validate_migrated_from(
            neighborhood["_migrated_from"],
            neighborhood_label,
        )
    return identity


def _validate_existing_index_identity(
    existing,
    canonical_identity,
    index_path,
    submissions_dir,
):
    index_label = _display_index_path(index_path, submissions_dir)
    if "neighborhood_rappid" in existing:
        _validate_neighborhood_rappid(
            existing["neighborhood_rappid"],
            index_label,
        )
    if "_migrated_from" in existing:
        _validate_migrated_from(existing["_migrated_from"], index_label)

    if canonical_identity is None:
        return

    sentinel = object()
    for key in INDEX_IDENTITY_FIELDS:
        canonical_value = canonical_identity.get(key, sentinel)
        has_existing = key in existing
        if canonical_value is sentinel:
            if has_existing:
                raise ValidationError(
                    f"{index_label} preserved identity field '{key}' must match neighborhood.json"
                )
            continue
        if not has_existing:
            raise ValidationError(
                f"{index_label} missing preserved identity field '{key}' from neighborhood.json"
            )
        if existing[key] != canonical_value:
            raise ValidationError(
                f"{index_label} preserved identity field '{key}' must match neighborhood.json"
            )


def _load_existing_index_document(index_path, submissions_dir):
    index_label = _display_index_path(index_path, submissions_dir)
    canonical_identity = _load_canonical_index_identity(submissions_dir)
    try:
        os.lstat(index_path)
    except FileNotFoundError:
        return dict(canonical_identity or {})
    except OSError as e:
        raise ValidationError(f"cannot inspect {index_label} ({e})")

    try:
        existing = _load_json(index_path, strict=True, no_follow=True)
    except ValueError as e:
        raise ValidationError(f"{index_label} is not valid JSON ({e})")
    except OSError as e:
        raise ValidationError(f"cannot read {index_label} ({e})")

    if not isinstance(existing, dict):
        raise ValidationError(f"{index_label} must be a JSON object")

    _validate_existing_index_identity(
        existing,
        canonical_identity,
        index_path,
        submissions_dir,
    )
    return existing


def _read_current_index_text(index_path, submissions_dir):
    index_label = _display_index_path(index_path, submissions_dir)
    try:
        with _open_regular_no_follow(index_path) as f:
            return f.read()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise ValidationError(f"cannot read {index_label} ({e})")


def discover_submission_dirs(submissions_dir=SUBMISSIONS_DIR):
    """Return validly named real directories directly under submissions/.

    The root is fail-closed: the only other permitted direct entry is a regular
    index.json. Nothing is silently ignored, including dotfiles and symlinks.
    """
    try:
        root_mode = os.lstat(submissions_dir).st_mode
    except FileNotFoundError:
        return []
    except OSError as e:
        raise ValidationError(
            f"cannot inspect submissions directory '{submissions_dir}' ({e})"
        )
    if not stat.S_ISDIR(root_mode):
        raise ValidationError(
            f"submissions path '{submissions_dir}' must be a real directory"
        )

    try:
        with os.scandir(submissions_dir) as entries:
            slugs = []
            unexpected = []
            for entry in entries:
                entry_kind = _entry_type(
                    entry.stat(follow_symlinks=False).st_mode
                )
                if entry.name == "index.json" and entry_kind == "regular file":
                    continue
                if (
                    entry_kind == "directory"
                    and not entry.name.startswith(".")
                    and SLUG_RE.fullmatch(entry.name)
                ):
                    slugs.append(entry.name)
                    continue
                unexpected.append((entry.name, entry_kind))
    except OSError as e:
        raise ValidationError(
            f"cannot scan submissions directory '{submissions_dir}' ({e})"
        )

    if unexpected:
        details = ", ".join(
            f"{name!r} ({entry_kind})"
            for name, entry_kind in sorted(unexpected)
        )
        raise ValidationError(
            "submissions/: unexpected direct "
            + details
            + "; only regular 'index.json' and valid submission directories "
              "are allowed"
        )
    return sorted(slugs)


def _submission_entry_types(dir_path, slug):
    try:
        if not stat.S_ISDIR(os.lstat(dir_path).st_mode):
            raise ValidationError(f"{slug}: submission path must be a real directory")
        with os.scandir(dir_path) as entries:
            result = {}
            for entry in entries:
                if entry.is_symlink():
                    kind = "symlink"
                elif entry.is_file(follow_symlinks=False):
                    kind = "regular file"
                elif entry.is_dir(follow_symlinks=False):
                    kind = "directory"
                else:
                    kind = "special file"
                result[entry.name] = kind
            return result
    except ValidationError:
        raise
    except OSError as e:
        raise ValidationError(f"{slug}: cannot inspect submission directory ({e})")


def _require_exact_submission_files(slug, entry_types, piece_name):
    expected = {"meta.json", piece_name}
    actual = set(entry_types)
    unexpected = sorted(actual - expected)
    missing = sorted(expected - actual)

    problems = []
    if missing:
        problems.append("missing " + ", ".join(repr(name) for name in missing))
    if unexpected:
        details = ", ".join(
            f"{name!r} ({entry_types[name]})" for name in unexpected
        )
        problems.append(f"unexpected {details}")
    if problems:
        expected_text = ", ".join(sorted(expected))
        raise ValidationError(
            f"{slug}: submission directory must contain exactly {expected_text}; "
            + "; ".join(problems)
        )

    for name in sorted(expected):
        if entry_types[name] != "regular file":
            raise ValidationError(
                f"{slug}: '{name}' must be a regular file, not "
                f"{entry_types[name]} (symlinks are not allowed)"
            )


def _png_error(slug, message):
    raise ValidationError(f"{slug}: piece.png {message}")


def _validate_png_bytes(payload, slug):
    """Validate the supported bounded PNG profile and return (width, height)."""
    if len(payload) > PNG_MAX_FILE_BYTES:
        _png_error(
            slug,
            f"exceeds the {PNG_MAX_FILE_BYTES}-byte file limit",
        )
    if not payload.startswith(PNG_SIGNATURE):
        _png_error(slug, "has an invalid PNG signature")

    offset = len(PNG_SIGNATURE)
    chunk_count = 0
    seen_ihdr = False
    seen_plte = False
    seen_idat = False
    idat_closed = False
    seen_iend = False
    idat_parts = []
    idat_bytes = 0
    width = height = channels = None

    while offset < len(payload):
        chunk_count += 1
        if chunk_count > PNG_MAX_CHUNKS:
            _png_error(slug, f"contains more than {PNG_MAX_CHUNKS} chunks")
        if len(payload) - offset < 12:
            _png_error(slug, "has truncated chunk framing")

        length = struct.unpack(">I", payload[offset:offset + 4])[0]
        if length > PNG_MAX_CHUNK_BYTES:
            _png_error(
                slug,
                f"chunk length {length} exceeds the "
                f"{PNG_MAX_CHUNK_BYTES}-byte limit",
            )
        chunk_end = offset + 12 + length
        if chunk_end > len(payload):
            _png_error(slug, "has a truncated chunk payload or CRC")

        chunk_type = payload[offset + 4:offset + 8]
        chunk_data = payload[offset + 8:offset + 8 + length]
        expected_crc = struct.unpack(
            ">I", payload[offset + 8 + length:chunk_end]
        )[0]

        if not all(
            ord("A") <= value <= ord("Z") or ord("a") <= value <= ord("z")
            for value in chunk_type
        ):
            _png_error(slug, "has a non-alphabetic chunk type")
        if not ord("A") <= chunk_type[2] <= ord("Z"):
            _png_error(slug, "uses an invalid lowercase reserved chunk bit")

        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(chunk_data, actual_crc) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            name = chunk_type.decode("ascii", errors="replace")
            _png_error(slug, f"has a CRC mismatch in {name}")

        if chunk_count == 1 and chunk_type != b"IHDR":
            _png_error(slug, "does not have IHDR as its first chunk")

        if chunk_type == b"IHDR":
            if seen_ihdr or chunk_count != 1:
                _png_error(slug, "contains a duplicate or misplaced IHDR")
            if length != 13:
                _png_error(slug, "IHDR must contain exactly 13 bytes")
            (
                width,
                height,
                bit_depth,
                color_type,
                compression_method,
                filter_method,
                interlace_method,
            ) = struct.unpack(">IIBBBBB", chunk_data)
            if width == 0 or height == 0:
                _png_error(slug, "must have positive pixel dimensions")
            if width > PNG_MAX_WIDTH or height > PNG_MAX_HEIGHT:
                _png_error(
                    slug,
                    f"dimensions {width}x{height} exceed the "
                    f"{PNG_MAX_WIDTH}x{PNG_MAX_HEIGHT} limits",
                )
            if width * height > PNG_MAX_PIXELS:
                _png_error(
                    slug,
                    f"contains {width * height} pixels, exceeding the "
                    f"{PNG_MAX_PIXELS}-pixel limit",
                )
            if bit_depth != 8 or color_type not in PNG_SUPPORTED_COLOR_TYPES:
                _png_error(
                    slug,
                    "must use 8-bit RGB (color type 2) or RGBA (color type 6)",
                )
            if compression_method != 0 or filter_method != 0:
                _png_error(slug, "uses an unsupported compression or filter method")
            if interlace_method != 0:
                _png_error(slug, "must be non-interlaced")
            channels = PNG_SUPPORTED_COLOR_TYPES[color_type]
            seen_ihdr = True
        elif not seen_ihdr:
            _png_error(slug, "contains data before IHDR")
        elif chunk_type == b"PLTE":
            if seen_plte or seen_idat:
                _png_error(slug, "contains a duplicate or misplaced PLTE")
            if length == 0 or length > 768 or length % 3:
                _png_error(slug, "contains an invalid PLTE length")
            seen_plte = True
        elif chunk_type == b"IDAT":
            if idat_closed:
                _png_error(slug, "contains non-consecutive IDAT chunks")
            seen_idat = True
            idat_bytes += length
            if idat_bytes > PNG_MAX_FILE_BYTES:
                _png_error(slug, "contains too much compressed IDAT data")
            idat_parts.append(chunk_data)
        elif chunk_type == b"IEND":
            if length != 0:
                _png_error(slug, "IEND must have zero length")
            if not seen_idat:
                _png_error(slug, "does not contain an IDAT chunk")
            seen_iend = True
            offset = chunk_end
            if offset != len(payload):
                _png_error(slug, "contains trailing bytes after IEND")
            break
        else:
            if chunk_type[0] & 0x20 == 0:
                name = chunk_type.decode("ascii", errors="replace")
                if chunk_type not in PNG_KNOWN_CRITICAL_CHUNKS:
                    _png_error(slug, f"contains unsupported critical chunk {name}")
            if seen_idat:
                idat_closed = True

        offset = chunk_end

    if not seen_iend:
        _png_error(slug, "is missing its final IEND chunk")

    row_bytes = width * channels
    expected_size = height * (row_bytes + 1)
    compressed = b"".join(idat_parts)
    inflater = zlib.decompressobj()
    try:
        scanlines = inflater.decompress(compressed, expected_size + 1)
        if len(scanlines) > expected_size or inflater.unconsumed_tail:
            _png_error(slug, "decompresses beyond the expected scanline size")
        scanlines += inflater.flush(expected_size + 1 - len(scanlines))
    except zlib.error as e:
        _png_error(slug, f"contains invalid zlib-compressed IDAT data ({e})")

    if not inflater.eof:
        _png_error(slug, "contains a truncated zlib stream")
    if inflater.unused_data:
        _png_error(slug, "contains bytes after the zlib stream")
    if len(scanlines) != expected_size:
        _png_error(
            slug,
            f"decompresses to {len(scanlines)} bytes; expected exactly "
            f"{expected_size}",
        )

    scanline_size = row_bytes + 1
    for row in range(height):
        filter_type = scanlines[row * scanline_size]
        if filter_type > 4:
            _png_error(
                slug,
                f"uses invalid filter type {filter_type} on scanline {row}",
            )

    return width, height


def _expect_exact_fields(value, expected, slug, label):
    if not isinstance(value, dict):
        raise ValidationError(f"{slug}: {label} must be a JSON object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise ValidationError(
            f"{slug}: {label} has the wrong fields ({'; '.join(details)})"
        )


def _is_json_integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _bounded_clean_text(value, slug, label, max_chars):
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > max_chars
        or any(ord(char) < 0x20 for char in value)
    ):
        raise ValidationError(
            f"{slug}: {label} must be a clean non-empty string of at most "
            f"{max_chars} characters"
        )
    return value


def _bounded_receipt_text(value, slug, label, max_chars, identifier=False):
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > max_chars
    ):
        raise ValidationError(
            f"{slug}: {label} must be a non-empty string of at most "
            f"{max_chars} characters"
        )
    if any(ord(char) < 0x20 for char in value):
        raise ValidationError(f"{slug}: {label} contains control characters")
    if identifier and not IMAGE_IDENTIFIER_RE.fullmatch(value):
        raise ValidationError(f"{slug}: {label} is not a bounded identifier")
    if RAW_CREDENTIAL_RE.search(value):
        raise ValidationError(f"{slug}: {label} appears to contain a credential")
    return value


def _reject_credential_material(value, slug, path="meta"):
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            child_path = f"{path}.{key}"
            if any(
                normalized == name or normalized.endswith(name)
                for name in CREDENTIAL_KEY_NAMES
            ):
                raise ValidationError(
                    f"{slug}: {child_path} is a forbidden credential field"
                )
            _reject_credential_material(child, slug, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_credential_material(child, slug, f"{path}[{index}]")
    elif isinstance(value, str) and RAW_CREDENTIAL_RE.search(value):
        raise ValidationError(
            f"{slug}: {path} appears to contain a raw credential or token"
        )


def validate_reviewed_png_title(value, slug, label="title"):
    return _bounded_clean_text(
        value,
        slug,
        label,
        REVIEWED_PNG_TITLE_MAX_CHARS,
    )


def validate_reviewed_png_contributor(value, slug, label="contributor"):
    if value != REVIEWED_PNG_TRUSTED_CONTRIBUTOR:
        raise ValidationError(
            f"{slug}: {label} must be '{REVIEWED_PNG_TRUSTED_CONTRIBUTOR}'"
        )
    return value


def _validate_image_generation_receipt(meta, payload, dimensions, slug):
    receipt = meta.get("_image_generation")
    _expect_exact_fields(
        receipt, IMAGE_GENERATION_FIELDS, slug, "_image_generation"
    )

    if receipt["schema"] != IMAGE_GENERATION_SCHEMA:
        raise ValidationError(
            f"{slug}: _image_generation.schema must be "
            f"'{IMAGE_GENERATION_SCHEMA}'"
        )
    if receipt["profile"] != IMAGE_GENERATION_PROFILE:
        raise ValidationError(
            f"{slug}: _image_generation.profile must be "
            f"'{IMAGE_GENERATION_PROFILE}'"
        )
    if receipt["provider"] != IMAGE_PROVIDER:
        raise ValidationError(
            f"{slug}: _image_generation.provider must be '{IMAGE_PROVIDER}'"
        )
    _bounded_receipt_text(
        receipt["provider"], slug, "_image_generation.provider", 64
    )
    _bounded_receipt_text(
        receipt["deployment"],
        slug,
        "_image_generation.deployment",
        IMAGE_MAX_IDENTIFIER_CHARS,
        identifier=True,
    )

    attempts = receipt["attempts"]
    if (
        not _is_json_integer(attempts)
        or attempts < 1
        or attempts > IMAGE_MAX_ATTEMPTS
    ):
        raise ValidationError(
            f"{slug}: _image_generation.attempts must be an integer from "
            f"1 to {IMAGE_MAX_ATTEMPTS}"
        )

    image_sha256 = receipt["image_sha256"]
    if (
        not isinstance(image_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", image_sha256)
        or image_sha256 != hashlib.sha256(payload).hexdigest()
    ):
        raise ValidationError(
            f"{slug}: _image_generation.image_sha256 does not match piece.png"
        )

    image = receipt["image"]
    _expect_exact_fields(
        image, IMAGE_FIELDS, slug, "_image_generation.image"
    )
    width, height = dimensions
    if (
        not _is_json_integer(image["width"])
        or not _is_json_integer(image["height"])
        or (image["width"], image["height"]) != (width, height)
    ):
        raise ValidationError(
            f"{slug}: _image_generation dimensions do not match PNG IHDR "
            f"{width}x{height}"
        )

    review = receipt["review"]
    _expect_exact_fields(
        review, IMAGE_REVIEW_FIELDS, slug, "_image_generation.review"
    )
    if review["schema"] != IMAGE_REVIEW_SCHEMA:
        raise ValidationError(
            f"{slug}: _image_generation.review.schema must be "
            f"'{IMAGE_REVIEW_SCHEMA}'"
        )
    _bounded_receipt_text(
        review["model"],
        slug,
        "_image_generation.review.model",
        IMAGE_MAX_IDENTIFIER_CHARS,
        identifier=True,
    )

    score = review["score"]
    minimum_score = review["minimum_score"]
    if (
        not _is_json_integer(score)
        or not _is_json_integer(minimum_score)
        or minimum_score < 8
        or minimum_score > 10
        or score < minimum_score
        or score > 10
    ):
        raise ValidationError(
            f"{slug}: review score must be an integer from minimum_score "
            "through 10, and minimum_score must be an integer from 8 through 10"
        )
    if review["publish"] is not True:
        raise ValidationError(
            f"{slug}: _image_generation.review.publish must be true"
        )
    if review["failures"] != []:
        raise ValidationError(
            f"{slug}: _image_generation.review.failures must be exactly []"
        )

    strengths = review["strengths"]
    if not isinstance(strengths, list) or len(strengths) > IMAGE_MAX_STRENGTHS:
        raise ValidationError(
            f"{slug}: _image_generation.review.strengths must contain at most "
            f"{IMAGE_MAX_STRENGTHS} strings"
        )
    for index, strength in enumerate(strengths):
        _bounded_receipt_text(
            strength,
            slug,
            f"_image_generation.review.strengths[{index}]",
            IMAGE_MAX_STRENGTH_CHARS,
        )


def validate_submission(slug, license_value, submissions_dir=SUBMISSIONS_DIR):
    """Validate one submissions/<slug>/ directory and return its index entry.

    Raises ValidationError with a human-readable message on the first failure.
    """
    dir_path = os.path.join(submissions_dir, slug)

    if not SLUG_RE.match(slug):
        raise ValidationError(
            f"{slug}: directory name is not a valid slug (lowercase alphanumeric + hyphens)"
        )

    entry_types = _submission_entry_types(dir_path, slug)
    if "meta.json" not in entry_types:
        raise ValidationError(f"{slug}: missing meta.json")
    if entry_types["meta.json"] != "regular file":
        raise ValidationError(
            f"{slug}: 'meta.json' must be a regular file, not "
            f"{entry_types['meta.json']} (symlinks are not allowed)"
        )

    meta_path = os.path.join(dir_path, "meta.json")
    try:
        meta = _load_json(meta_path, strict=True, no_follow=True)
    except (ValueError, UnicodeDecodeError) as e:
        raise ValidationError(f"{slug}: meta.json is not valid JSON ({e})")
    except OSError as e:
        raise ValidationError(f"{slug}: cannot read meta.json ({e})")

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
    if not isinstance(kind, str) or kind not in KIND_EXTENSIONS:
        raise ValidationError(
            f"{slug}: unsupported kind '{kind}' (expected one of {sorted(KIND_EXTENSIONS)})"
        )

    ext = KIND_EXTENSIONS[kind]
    piece_name = f"piece.{ext}"
    _require_exact_submission_files(slug, entry_types, piece_name)

    piece_path = os.path.join(dir_path, piece_name)

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

    if kind == "png":
        validate_reviewed_png_title(meta.get("title"), slug)
        validate_reviewed_png_contributor(meta.get("contributor"), slug)
        try:
            with _open_regular_no_follow(piece_path, binary=True) as f:
                piece_size = os.fstat(f.fileno()).st_size
                if piece_size > PNG_MAX_FILE_BYTES:
                    _png_error(
                        slug,
                        f"exceeds the {PNG_MAX_FILE_BYTES}-byte file limit",
                    )
                payload = f.read(PNG_MAX_FILE_BYTES + 1)
        except OSError as e:
            raise ValidationError(f"{slug}: cannot read piece.png ({e})")
        dimensions = _validate_png_bytes(payload, slug)
        _validate_image_generation_receipt(
            meta, payload, dimensions, slug
        )
        _reject_credential_material(meta, slug)

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
    license_value = (
        license_value
        if license_value is not None
        else accepted_license(neighborhood_path_for_submissions(submissions_dir))
    )
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


def build_index_document(entries, index_path=INDEX_PATH, submissions_dir=None):
    """Merge freshly validated entries into the existing index document.

    Every non-derived top-level field (schema, neighborhood_rappid,
    _migrated_from, note, and any future field) is preserved verbatim from a
    valid existing file; only `submissions` is replaced. A missing file is
    reseeded from canonical neighborhood identity when available, but malformed
    or identity-drifted existing files fail closed.
    """
    submissions_dir = submissions_dir or os.path.dirname(os.path.abspath(index_path))
    existing = _load_existing_index_document(index_path, submissions_dir)

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
        if args.validate:
            # Fail-closed on submissions only. Deliberately does not look at
            # index.json at all — a submission-only PR is expected to leave it
            # stale, and that must never be a failure here (see module docstring).
            print(f"all submissions valid ({len(entries)} submissions)")
            return 0

        doc = build_index_document(
            entries,
            index_path=index_path,
            submissions_dir=submissions_dir,
        )
        rendered = render(doc)
        current = _read_current_index_text(index_path, submissions_dir)
    except ValidationError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.write:
        if current == rendered:
            print(f"submissions/index.json already up to date ({len(entries)} submissions)")
            return 0
        try:
            with open(index_path, "w", encoding="utf-8") as f:
                f.write(rendered)
        except OSError as e:
            print(
                f"error: cannot write {_display_index_path(index_path, submissions_dir)} ({e})",
                file=sys.stderr,
            )
            return 1
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
