#!/usr/bin/env python3
"""test_build_index.py — self-tests for tools/build_index.py.

Stdlib-only (unittest + tempfile). Builds small fixture submissions/ trees in a
temp directory per test so the real repo's submissions/ is never touched.

Run:
  python3 -m unittest tools.test_build_index -v
  python3 tools/test_build_index.py
"""
import json
import hashlib
import os
import re
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
import contextlib
import io

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_index  # noqa: E402


FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


VALID_META = {
    "schema": "rapp-art-submission/1.0",
    "title": "Sample Piece",
    "slug": "sample-piece",
    "contributor": "tester",
    "kind": "svg",
    "submitted_at": "2026-01-01T00:00:00Z",
    "remix_of": None,
    "license": "CC0-1.0",
}

TEST_NEIGHBORHOOD_RAPPID = (
    "rappid:@example/public-art-collective:"
    "0123456789abcdef0123456789abcdef"
)
TEST_MIGRATED_FROM = {
    "neighborhood_rappid": "01234567-89ab-cdef-0123-456789abcdef",
}


def png_chunk(chunk_type, data):
    crc = zlib.crc32(chunk_type)
    crc = zlib.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def png_ihdr(width=2, height=2, bit_depth=8, color_type=6,
             compression=0, filter_method=0, interlace=0):
    return struct.pack(
        ">IIBBBBB",
        width,
        height,
        bit_depth,
        color_type,
        compression,
        filter_method,
        interlace,
    )


def make_png(width=2, height=2, bit_depth=8, color_type=6, interlace=0,
             raw_scanlines=None, idat_payload=None, filters=None,
             before_idat=(), after_idat=(), trailing=b""):
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type, 4)
    if raw_scanlines is None:
        filters = filters if filters is not None else [0] * height
        pixel_row = bytes([37]) * (width * channels)
        raw_scanlines = b"".join(
            bytes([filters[row]]) + pixel_row for row in range(height)
        )
    if idat_payload is None:
        idat_payload = zlib.compress(raw_scanlines)
    chunks = [
        png_chunk(b"IHDR", png_ihdr(
            width=width,
            height=height,
            bit_depth=bit_depth,
            color_type=color_type,
            interlace=interlace,
        )),
        *before_idat,
        png_chunk(b"IDAT", idat_payload),
        *after_idat,
        png_chunk(b"IEND", b""),
    ]
    return build_index.PNG_SIGNATURE + b"".join(chunks) + trailing


def image_generation_receipt(payload, width=2, height=2):
    return {
        "schema": "rapp-image-generation/1.0",
        "profile": "azure-reviewed-png",
        "provider": "azure-openai",
        "deployment": "gpt-image-2",
        "attempts": 1,
        "image_sha256": hashlib.sha256(payload).hexdigest(),
        "image": {
            "width": width,
            "height": height,
        },
        "review": {
            "schema": "rapp-image-review/1.0",
            "model": "gpt-5.4",
            "score": 9,
            "minimum_score": 8,
            "publish": True,
            "failures": [],
            "strengths": [
                "clear focal hierarchy",
                "finished composition",
            ],
        },
    }


def write_submission(submissions_dir, slug, meta_overrides=None, piece_ext="svg",
                      piece_content="<svg/>", skip_meta=False, skip_piece=False):
    d = os.path.join(submissions_dir, slug)
    os.makedirs(d, exist_ok=True)
    if not skip_meta:
        meta = dict(VALID_META)
        meta["slug"] = slug
        meta["title"] = slug.replace("-", " ").title()
        if meta_overrides:
            meta.update(meta_overrides)
        with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f)
    if not skip_piece:
        piece_path = os.path.join(d, f"piece.{piece_ext}")
        if isinstance(piece_content, bytes):
            with open(piece_path, "wb") as f:
                f.write(piece_content)
        else:
            with open(piece_path, "w", encoding="utf-8") as f:
                f.write(piece_content)
    return d


def write_png_submission(submissions_dir, slug, payload=None, width=2, height=2,
                         include_receipt=True, receipt=None, meta_extras=None):
    payload = payload if payload is not None else make_png(width=width, height=height)
    meta_overrides = {
        "kind": "png",
        "contributor": build_index.REVIEWED_PNG_TRUSTED_CONTRIBUTOR,
    }
    if meta_extras:
        meta_overrides.update(meta_extras)
    if include_receipt:
        meta_overrides["_image_generation"] = (
            receipt if receipt is not None
            else image_generation_receipt(payload, width=width, height=height)
        )
    return write_submission(
        submissions_dir,
        slug,
        meta_overrides=meta_overrides,
        piece_ext="png",
        piece_content=payload,
    )


class BuildIndexTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pac-index-test-")
        self.submissions_dir = os.path.join(self.tmp, "submissions")
        os.makedirs(self.submissions_dir, exist_ok=True)
        self._slug_counter = 0
        self.write_neighborhood()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def index_path(self):
        return os.path.join(self.submissions_dir, "index.json")

    def neighborhood_path(self):
        return os.path.join(self.tmp, "neighborhood.json")

    def fresh_slug(self, prefix):
        self._slug_counter += 1
        return f"{prefix}-{self._slug_counter}"

    def write_neighborhood(
        self,
        neighborhood_rappid=TEST_NEIGHBORHOOD_RAPPID,
        migrated_from=TEST_MIGRATED_FROM,
        license_text="CC0-1.0 — submissions are dedicated to the public domain",
    ):
        doc = {
            "schema": "rapp-neighborhood/1.0",
            "neighborhood_rappid": neighborhood_rappid,
            "contribution_policy": {
                "license": license_text,
            },
        }
        if migrated_from is not None:
            doc["_migrated_from"] = migrated_from
        with open(self.neighborhood_path(), "w", encoding="utf-8") as f:
            json.dump(doc, f)
        return doc

    def read_index_text(self):
        with open(self.index_path(), encoding="utf-8") as f:
            return f.read()


class TestDiscoverAndValidate(BuildIndexTestCase):
    def test_discovers_every_submission_directory(self):
        write_submission(self.submissions_dir, "alpha")
        write_submission(self.submissions_dir, "beta")
        write_submission(self.submissions_dir, "gamma")
        slugs = build_index.discover_submission_dirs(self.submissions_dir)
        self.assertEqual(slugs, ["alpha", "beta", "gamma"])

    def test_allows_only_regular_index_json_beside_submissions(self):
        write_submission(self.submissions_dir, "alpha")
        with open(os.path.join(self.submissions_dir, "index.json"), "w") as f:
            f.write("{}")
        slugs = build_index.discover_submission_dirs(self.submissions_dir)
        self.assertEqual(slugs, ["alpha"])

    def test_rejects_direct_regular_file(self):
        write_submission(self.submissions_dir, "alpha")
        with open(os.path.join(self.submissions_dir, "notes.txt"), "w") as f:
            f.write("unexpected")
        with self.assertRaisesRegex(build_index.ValidationError, "notes.txt"):
            build_index.discover_submission_dirs(self.submissions_dir)

    def test_rejects_direct_dotfile_and_dot_directory(self):
        write_submission(self.submissions_dir, "alpha")
        for name, make_entry in (
            (".DS_Store", lambda path: open(path, "w").close()),
            (".hidden", os.mkdir),
        ):
            with self.subTest(name=name):
                path = os.path.join(self.submissions_dir, name)
                make_entry(path)
                try:
                    with self.assertRaisesRegex(
                        build_index.ValidationError, re.escape(name)
                    ):
                        build_index.discover_submission_dirs(
                            self.submissions_dir
                        )
                finally:
                    if os.path.isdir(path):
                        os.rmdir(path)
                    else:
                        os.unlink(path)

    def test_rejects_submission_directory_symlink(self):
        write_submission(self.submissions_dir, "alpha")
        os.symlink(
            os.path.join(self.submissions_dir, "alpha"),
            os.path.join(self.submissions_dir, "linked-alpha"),
        )
        with self.assertRaisesRegex(build_index.ValidationError, "symlink"):
            build_index.discover_submission_dirs(self.submissions_dir)

    def test_rejects_index_json_symlink(self):
        target = os.path.join(self.tmp, "outside-index.json")
        with open(target, "w") as f:
            f.write("{}")
        os.symlink(target, os.path.join(self.submissions_dir, "index.json"))
        with self.assertRaisesRegex(build_index.ValidationError, "index.json"):
            build_index.discover_submission_dirs(self.submissions_dir)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO unsupported")
    def test_rejects_direct_special_entry(self):
        os.mkfifo(os.path.join(self.submissions_dir, "queue"))
        with self.assertRaisesRegex(build_index.ValidationError, "special file"):
            build_index.discover_submission_dirs(self.submissions_dir)

    def test_rejects_unexpected_directory_name(self):
        os.mkdir(os.path.join(self.submissions_dir, "Not-A-Slug"))
        with self.assertRaisesRegex(build_index.ValidationError, "Not-A-Slug"):
            build_index.discover_submission_dirs(self.submissions_dir)

    def test_rejects_symlinked_submissions_root(self):
        real_root = os.path.join(self.tmp, "real-submissions")
        os.mkdir(real_root)
        linked_root = os.path.join(self.tmp, "linked-submissions")
        os.symlink(real_root, linked_root)
        with self.assertRaisesRegex(build_index.ValidationError, "real directory"):
            build_index.discover_submission_dirs(linked_root)

    def test_valid_submission_produces_expected_entry(self):
        write_submission(self.submissions_dir, "alpha")
        entry = build_index.validate_submission("alpha", "CC0-1.0", self.submissions_dir)
        self.assertEqual(entry["slug"], "alpha")
        self.assertEqual(entry["meta_path"], "submissions/alpha/meta.json")
        self.assertEqual(entry["piece_path"], "submissions/alpha/piece.svg")

    def test_missing_meta_json_fails(self):
        write_submission(self.submissions_dir, "alpha", skip_meta=True)
        with self.assertRaises(build_index.ValidationError):
            build_index.validate_submission("alpha", "CC0-1.0", self.submissions_dir)

    def test_missing_piece_file_fails(self):
        write_submission(self.submissions_dir, "alpha", skip_piece=True)
        with self.assertRaises(build_index.ValidationError):
            build_index.validate_submission("alpha", "CC0-1.0", self.submissions_dir)

    def test_slug_path_mismatch_fails(self):
        write_submission(self.submissions_dir, "alpha", meta_overrides={"slug": "not-alpha"})
        with self.assertRaises(build_index.ValidationError):
            build_index.validate_submission("alpha", "CC0-1.0", self.submissions_dir)

    def test_unsupported_kind_fails(self):
        write_submission(self.submissions_dir, "alpha", meta_overrides={"kind": "video"})
        with self.assertRaises(build_index.ValidationError):
            build_index.validate_submission("alpha", "CC0-1.0", self.submissions_dir)

    def test_non_string_kind_fails_closed(self):
        write_submission(self.submissions_dir, "alpha", meta_overrides={"kind": ["png"]})
        with self.assertRaises(build_index.ValidationError):
            build_index.validate_submission("alpha", "CC0-1.0", self.submissions_dir)

    def test_kind_extension_mismatch_fails(self):
        # meta says svg but only piece.md exists on disk.
        write_submission(self.submissions_dir, "alpha", piece_ext="md")
        with self.assertRaises(build_index.ValidationError):
            build_index.validate_submission("alpha", "CC0-1.0", self.submissions_dir)

    def test_non_cc0_license_fails(self):
        write_submission(self.submissions_dir, "alpha", meta_overrides={"license": "MIT"})
        with self.assertRaises(build_index.ValidationError):
            build_index.validate_submission("alpha", "CC0-1.0", self.submissions_dir)

    def test_wrong_schema_fails(self):
        write_submission(self.submissions_dir, "alpha", meta_overrides={"schema": "rapp-art-submission/0.9"})
        with self.assertRaises(build_index.ValidationError):
            build_index.validate_submission("alpha", "CC0-1.0", self.submissions_dir)

    def test_invalid_json_fails(self):
        d = os.path.join(self.submissions_dir, "alpha")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "meta.json"), "w") as f:
            f.write("{not json")
        with open(os.path.join(d, "piece.svg"), "w") as f:
            f.write("<svg/>")
        with self.assertRaises(build_index.ValidationError):
            build_index.validate_submission("alpha", "CC0-1.0", self.submissions_dir)

    def test_invalid_slug_directory_name_fails(self):
        write_submission(self.submissions_dir, "Alpha_Bad")
        with self.assertRaises(build_index.ValidationError):
            build_index.validate_submission("Alpha_Bad", "CC0-1.0", self.submissions_dir)


class TestExactSubmissionFiles(BuildIndexTestCase):
    def test_unexpected_regular_file_fails(self):
        directory = write_submission(self.submissions_dir, "alpha")
        with open(os.path.join(directory, "notes.txt"), "w", encoding="utf-8") as f:
            f.write("not part of the submission")
        with self.assertRaisesRegex(build_index.ValidationError, "unexpected"):
            build_index.validate_submission("alpha", "CC0-1.0", self.submissions_dir)

    def test_hidden_regular_file_fails(self):
        directory = write_submission(self.submissions_dir, "alpha")
        with open(os.path.join(directory, ".DS_Store"), "w", encoding="utf-8") as f:
            f.write("finder metadata")
        with self.assertRaisesRegex(build_index.ValidationError, r"\.DS_Store"):
            build_index.validate_submission("alpha", "CC0-1.0", self.submissions_dir)

    def test_unexpected_directory_fails(self):
        directory = write_submission(self.submissions_dir, "alpha")
        os.mkdir(os.path.join(directory, "review"))
        with self.assertRaisesRegex(build_index.ValidationError, "directory"):
            build_index.validate_submission("alpha", "CC0-1.0", self.submissions_dir)

    def test_unexpected_symlink_fails_without_following_it(self):
        directory = write_submission(self.submissions_dir, "alpha")
        os.symlink("piece.svg", os.path.join(directory, "preview.svg"))
        with self.assertRaisesRegex(build_index.ValidationError, "symlink"):
            build_index.validate_submission("alpha", "CC0-1.0", self.submissions_dir)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO unsupported")
    def test_unexpected_special_entry_fails(self):
        directory = write_submission(self.submissions_dir, "alpha")
        os.mkfifo(os.path.join(directory, "review-queue"))
        with self.assertRaisesRegex(build_index.ValidationError, "special file"):
            build_index.validate_submission(
                "alpha", "CC0-1.0", self.submissions_dir
            )

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO unsupported")
    def test_required_piece_must_not_be_a_special_entry(self):
        directory = write_submission(self.submissions_dir, "alpha")
        piece_path = os.path.join(directory, "piece.svg")
        os.unlink(piece_path)
        os.mkfifo(piece_path)
        with self.assertRaisesRegex(build_index.ValidationError, "special file"):
            build_index.validate_submission(
                "alpha", "CC0-1.0", self.submissions_dir
            )

    def test_meta_json_symlink_fails_without_following_it(self):
        directory = write_submission(self.submissions_dir, "alpha")
        target = os.path.join(self.tmp, "outside-meta.json")
        shutil.move(os.path.join(directory, "meta.json"), target)
        os.symlink(target, os.path.join(directory, "meta.json"))
        with self.assertRaisesRegex(build_index.ValidationError, "symlinks are not allowed"):
            build_index.validate_submission("alpha", "CC0-1.0", self.submissions_dir)

    def test_piece_symlink_fails_without_following_it(self):
        directory = write_submission(self.submissions_dir, "alpha")
        target = os.path.join(self.tmp, "outside-piece.svg")
        shutil.move(os.path.join(directory, "piece.svg"), target)
        os.symlink(target, os.path.join(directory, "piece.svg"))
        with self.assertRaisesRegex(build_index.ValidationError, "symlinks are not allowed"):
            build_index.validate_submission("alpha", "CC0-1.0", self.submissions_dir)

    def test_exact_two_regular_files_remain_valid(self):
        write_submission(self.submissions_dir, "alpha")
        entry = build_index.validate_submission(
            "alpha", "CC0-1.0", self.submissions_dir
        )
        self.assertEqual("submissions/alpha/piece.svg", entry["piece_path"])


class TestPngValidation(BuildIndexTestCase):
    def assert_invalid_png(self, payload, width=2, height=2, pattern=None):
        slug = self.fresh_slug("bad-png")
        write_png_submission(
            self.submissions_dir,
            slug,
            payload=payload,
            width=width,
            height=height,
        )
        context = (
            self.assertRaisesRegex(build_index.ValidationError, pattern)
            if pattern
            else self.assertRaises(build_index.ValidationError)
        )
        with context:
            build_index.validate_submission(
                slug, "CC0-1.0", self.submissions_dir
            )

    def test_accepts_generated_rgb_and_rgba_pngs(self):
        write_png_submission(
            self.submissions_dir,
            "rgb-piece",
            payload=make_png(color_type=2),
        )
        write_png_submission(self.submissions_dir, "rgba-piece")
        entries = build_index.build_entries(self.submissions_dir, "CC0-1.0")
        self.assertEqual(
            {"rgb-piece", "rgba-piece"},
            {entry["slug"] for entry in entries},
        )

    def test_rejects_bad_signature(self):
        payload = b"not-png!" + make_png()[8:]
        self.assert_invalid_png(payload, pattern="signature")

    def test_rejects_truncated_chunk_framing(self):
        self.assert_invalid_png(make_png()[:-2], pattern="truncated")

    def test_rejects_declared_truncated_chunk_payload(self):
        payload = build_index.PNG_SIGNATURE + struct.pack(
            ">I", 13
        ) + b"IHDR" + b"\0" * 5
        self.assert_invalid_png(payload, pattern="truncated")

    def test_rejects_crc_bad_png(self):
        payload = bytearray(make_png())
        idat_type = payload.index(b"IDAT")
        idat_length = struct.unpack(">I", payload[idat_type - 4:idat_type])[0]
        crc_offset = idat_type + 4 + idat_length
        payload[crc_offset] ^= 0x01
        self.assert_invalid_png(bytes(payload), pattern="CRC mismatch")

    def test_rejects_ihdr_that_is_not_first(self):
        payload = (
            build_index.PNG_SIGNATURE
            + png_chunk(b"tEXt", b"before header")
            + png_chunk(b"IHDR", png_ihdr())
            + png_chunk(b"IDAT", zlib.compress(b"\0" + b"\0" * 8) * 2)
            + png_chunk(b"IEND", b"")
        )
        self.assert_invalid_png(payload, pattern="IHDR as its first")

    def test_rejects_wrong_ihdr_length(self):
        payload = (
            build_index.PNG_SIGNATURE
            + png_chunk(b"IHDR", png_ihdr()[:-1])
            + png_chunk(b"IEND", b"")
        )
        self.assert_invalid_png(payload, pattern="exactly 13")

    def test_rejects_header_only_png(self):
        payload = (
            build_index.PNG_SIGNATURE
            + png_chunk(b"IHDR", png_ihdr())
            + png_chunk(b"IEND", b"")
        )
        self.assert_invalid_png(payload, pattern="IDAT")

    def test_rejects_decompression_bad_png(self):
        self.assert_invalid_png(
            make_png(idat_payload=b"not a zlib stream"),
            pattern="invalid zlib",
        )

    def test_rejects_truncated_zlib_stream(self):
        compressed = zlib.compress(b"\0" + b"\0" * 8 + b"\0" + b"\0" * 8)
        self.assert_invalid_png(
            make_png(idat_payload=compressed[:-2]),
            pattern="truncated zlib",
        )

    def test_rejects_wrong_decompressed_scanline_length(self):
        for raw in (
            b"\0" + b"\0" * 8,
            b"\0" + b"\0" * 8 + b"\0" + b"\0" * 8 + b"x",
        ):
            with self.subTest(length=len(raw)):
                self.assert_invalid_png(
                    make_png(raw_scanlines=raw),
                    pattern="decompress",
                )

    def test_rejects_invalid_scanline_filter(self):
        self.assert_invalid_png(make_png(filters=[0, 5]), pattern="filter type 5")

    def test_rejects_unsupported_bit_depth_color_and_interlace(self):
        cases = (
            ("bit depth", make_png(bit_depth=16), "8-bit RGB"),
            ("grayscale", make_png(color_type=0), "8-bit RGB"),
            ("interlaced", make_png(interlace=1), "non-interlaced"),
        )
        for name, payload, pattern in cases:
            with self.subTest(name=name):
                self.assert_invalid_png(payload, pattern=pattern)

    def test_rejects_zero_dimensions(self):
        self.assert_invalid_png(
            make_png(width=0, raw_scanlines=b"\0\0"),
            width=0,
            pattern="positive pixel dimensions",
        )

    def test_rejects_oversized_width_height_and_pixel_count(self):
        cases = (
            (
                build_index.PNG_MAX_WIDTH + 1,
                1,
                "dimensions",
            ),
            (
                1,
                build_index.PNG_MAX_HEIGHT + 1,
                "dimensions",
            ),
            (
                build_index.PNG_MAX_WIDTH,
                build_index.PNG_MAX_HEIGHT,
                "pixel limit",
            ),
        )
        for width, height, pattern in cases:
            with self.subTest(width=width, height=height):
                payload = make_png(
                    width=width,
                    height=height,
                    raw_scanlines=b"\0",
                )
                self.assert_invalid_png(
                    payload,
                    width=width,
                    height=height,
                    pattern=pattern,
                )

    def test_rejects_oversized_chunk_length_before_allocation(self):
        payload = (
            build_index.PNG_SIGNATURE
            + struct.pack(">I", build_index.PNG_MAX_CHUNK_BYTES + 1)
            + b"IHDR"
            + b"\0" * 4
        )
        self.assert_invalid_png(payload, pattern="chunk length")

    def test_rejects_oversized_file_before_reading_it(self):
        directory = write_png_submission(
            self.submissions_dir,
            "oversized-file",
        )
        with open(os.path.join(directory, "piece.png"), "ab") as f:
            f.truncate(build_index.PNG_MAX_FILE_BYTES + 1)
        with self.assertRaisesRegex(build_index.ValidationError, "file limit"):
            build_index.validate_submission(
                "oversized-file", "CC0-1.0", self.submissions_dir
            )

    def test_rejects_nonzero_iend(self):
        valid = make_png()
        iend_start = valid.rindex(b"IEND") - 4
        payload = valid[:iend_start] + png_chunk(b"IEND", b"x")
        self.assert_invalid_png(payload, pattern="IEND must have zero length")

    def test_rejects_missing_iend(self):
        valid = make_png()
        iend_start = valid.rindex(b"IEND") - 4
        self.assert_invalid_png(valid[:iend_start], pattern="missing.*IEND")

    def test_rejects_polyglot_or_other_trailing_bytes(self):
        self.assert_invalid_png(
            make_png(trailing=b"<script>alert(1)</script>"),
            pattern="trailing bytes",
        )

    def test_rejects_bytes_after_zlib_stream(self):
        raw = b"\0" + b"\0" * 8 + b"\0" + b"\0" * 8
        self.assert_invalid_png(
            make_png(idat_payload=zlib.compress(raw) + b"hidden"),
            pattern="after the zlib stream",
        )

    def test_rejects_nonconsecutive_idat_chunks(self):
        raw = b"\0" + b"\0" * 8 + b"\0" + b"\0" * 8
        compressed = zlib.compress(raw)
        midpoint = len(compressed) // 2
        payload = (
            build_index.PNG_SIGNATURE
            + png_chunk(b"IHDR", png_ihdr())
            + png_chunk(b"IDAT", compressed[:midpoint])
            + png_chunk(b"tEXt", b"gap")
            + png_chunk(b"IDAT", compressed[midpoint:])
            + png_chunk(b"IEND", b"")
        )
        self.assert_invalid_png(payload, pattern="non-consecutive IDAT")

    def test_rejects_unknown_critical_chunk(self):
        payload = make_png(before_idat=(png_chunk(b"ABCD", b""),))
        self.assert_invalid_png(payload, pattern="unsupported critical")


class TestPngReceipt(BuildIndexTestCase):
    def validate_receipt(self, receipt, payload=None):
        payload = payload if payload is not None else make_png()
        slug = self.fresh_slug("receipt-piece")
        write_png_submission(
            self.submissions_dir,
            slug,
            payload=payload,
            receipt=receipt,
        )
        return build_index.validate_submission(
            slug, "CC0-1.0", self.submissions_dir
        )

    def assert_invalid_receipt(self, mutate, pattern=None):
        payload = make_png()
        receipt = image_generation_receipt(payload)
        mutate(receipt)
        context = (
            self.assertRaisesRegex(build_index.ValidationError, pattern)
            if pattern
            else self.assertRaises(build_index.ValidationError)
        )
        with context:
            self.validate_receipt(receipt, payload)

    def test_valid_strict_receipt_passes(self):
        payload = make_png()
        entry = self.validate_receipt(image_generation_receipt(payload), payload)
        self.assertEqual("png", entry["kind"])
        self.assertTrue(entry["piece_path"].endswith("/piece.png"))

    def test_controller_serialized_receipt_fixture_passes(self):
        payload = make_png(width=512, height=512)
        fixture_path = os.path.join(
            FIXTURES_DIR, "dada-controller-receipt.json"
        )
        with open(fixture_path, encoding="utf-8") as f:
            receipt = json.load(f)
        self.assertIs(type(receipt["review"]["score"]), int)
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            receipt["image_sha256"],
        )
        slug = self.fresh_slug("controller-fixture")
        write_png_submission(
            self.submissions_dir,
            slug,
            payload=payload,
            width=512,
            height=512,
            receipt=receipt,
        )
        entry = build_index.validate_submission(
            slug, "CC0-1.0", self.submissions_dir
        )
        self.assertEqual("png", entry["kind"])

    def test_missing_receipt_fails(self):
        write_png_submission(
            self.submissions_dir,
            "missing-receipt",
            include_receipt=False,
        )
        with self.assertRaisesRegex(build_index.ValidationError, "_image_generation"):
            build_index.validate_submission(
                "missing-receipt", "CC0-1.0", self.submissions_dir
            )

    def test_generation_receipt_rejects_missing_and_extra_fields(self):
        self.assert_invalid_receipt(
            lambda receipt: receipt.pop("image_sha256"),
            pattern="missing image_sha256",
        )
        self.assert_invalid_receipt(
            lambda receipt: receipt.__setitem__("api_key", "secret"),
            pattern="unexpected api_key",
        )

    def test_review_rejects_missing_and_extra_fields(self):
        self.assert_invalid_receipt(
            lambda receipt: receipt["review"].pop("minimum_score"),
            pattern="missing minimum_score",
        )
        self.assert_invalid_receipt(
            lambda receipt: receipt["review"].__setitem__("raw", "transcript"),
            pattern="unexpected raw",
        )

    def test_image_dimensions_reject_missing_and_extra_fields(self):
        self.assert_invalid_receipt(
            lambda receipt: receipt["image"].pop("height"),
            pattern="missing height",
        )
        self.assert_invalid_receipt(
            lambda receipt: receipt["image"].__setitem__("channels", 4),
            pattern="unexpected channels",
        )

    def test_rejects_wrong_generation_schema_and_profile(self):
        for field, value in (
            ("schema", "rapp-image-generation/0.9"),
            ("profile", "unreviewed-png"),
        ):
            with self.subTest(field=field):
                self.assert_invalid_receipt(
                    lambda receipt, field=field, value=value:
                    receipt.__setitem__(field, value),
                    pattern=field,
                )

    def test_rejects_forged_hash(self):
        self.assert_invalid_receipt(
            lambda receipt: receipt.__setitem__("image_sha256", "0" * 64),
            pattern="does not match",
        )

    def test_rejects_dimensions_that_do_not_match_ihdr(self):
        self.assert_invalid_receipt(
            lambda receipt: receipt["image"].__setitem__("width", 3),
            pattern="dimensions do not match",
        )
        self.assert_invalid_receipt(
            lambda receipt: receipt["image"].__setitem__("height", True),
            pattern="dimensions do not match",
        )

    def test_rejects_non_publishing_or_failed_review(self):
        self.assert_invalid_receipt(
            lambda receipt: receipt["review"].__setitem__("publish", False),
            pattern="publish must be true",
        )
        self.assert_invalid_receipt(
            lambda receipt: receipt["review"].__setitem__(
                "failures", ["visible defect"]
            ),
            pattern=r"exactly \[\]",
        )

    def test_rejects_invalid_score_or_minimum_score(self):
        cases = (
            ("score", 8.5),
            ("score", 9.0),
            ("score", True),
            ("score", 7),
            ("score", 11),
            ("minimum_score", 8.0),
            ("minimum_score", 7),
            ("minimum_score", 11),
            ("minimum_score", True),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                self.assert_invalid_receipt(
                    lambda receipt, field=field, value=value:
                    receipt["review"].__setitem__(field, value),
                    pattern="review score",
                )

    def test_rejects_unbounded_attempts(self):
        for value in (0, 1.0, build_index.IMAGE_MAX_ATTEMPTS + 1, True):
            with self.subTest(value=value):
                self.assert_invalid_receipt(
                    lambda receipt, value=value:
                    receipt.__setitem__("attempts", value),
                    pattern="attempts",
                )

    def test_rejects_wrong_provider_or_review_schema(self):
        self.assert_invalid_receipt(
            lambda receipt: receipt.__setitem__("provider", "other-cloud"),
            pattern="provider",
        )
        self.assert_invalid_receipt(
            lambda receipt: receipt["review"].__setitem__(
                "schema", "rapp-image-review/0.9"
            ),
            pattern="review.schema",
        )

    def test_rejects_unbounded_or_non_identifier_deployment_and_model(self):
        cases = (
            ("deployment", ""),
            ("deployment", "x" * (build_index.IMAGE_MAX_IDENTIFIER_CHARS + 1)),
            ("deployment", "deployment/with/path"),
            ("model", ""),
            ("model", "model with spaces"),
        )
        for field, value in cases:
            with self.subTest(field=field):
                def mutate(receipt, field=field, value=value):
                    target = receipt if field == "deployment" else receipt["review"]
                    target[field] = value

                self.assert_invalid_receipt(mutate, pattern=field)

    def test_rejects_raw_tokens_in_receipt_strings(self):
        self.assert_invalid_receipt(
            lambda receipt: receipt.__setitem__(
                "deployment", "sk-" + "a" * 24
            ),
            pattern="credential",
        )
        self.assert_invalid_receipt(
            lambda receipt: receipt["review"]["strengths"].__setitem__(
                0, "Bearer abcdefghijklmnopqrstuvwxyz"
            ),
            pattern="credential",
        )

    def test_rejects_credentials_anywhere_in_png_metadata(self):
        payload = make_png()
        write_png_submission(
            self.submissions_dir,
            "credential-field",
            payload=payload,
            meta_extras={"_azure_api_key": "redacted-but-forbidden"},
        )
        with self.assertRaisesRegex(build_index.ValidationError, "credential field"):
            build_index.validate_submission(
                "credential-field", "CC0-1.0", self.submissions_dir
            )

        write_png_submission(
            self.submissions_dir,
            "raw-token",
            payload=payload,
            meta_extras={
                "_artist_statement":
                    "Bearer abcdefghijklmnopqrstuvwxyz0123456789"
            },
        )
        with self.assertRaisesRegex(build_index.ValidationError, "raw credential"):
            build_index.validate_submission(
                "raw-token", "CC0-1.0", self.submissions_dir
            )

    def test_rejects_unbounded_or_invalid_strengths(self):
        cases = (
            "not-a-list",
            ["ok"] * (build_index.IMAGE_MAX_STRENGTHS + 1),
            [""],
            ["   "],
            ["x" * (build_index.IMAGE_MAX_STRENGTH_CHARS + 1)],
        )
        for strengths in cases:
            with self.subTest(strengths_type=type(strengths).__name__):
                self.assert_invalid_receipt(
                    lambda receipt, strengths=strengths:
                    receipt["review"].__setitem__("strengths", strengths),
                    pattern="strengths",
                )

    def test_duplicate_receipt_json_key_fails(self):
        payload = make_png()
        directory = write_png_submission(
            self.submissions_dir,
            "duplicate-key",
            payload=payload,
        )
        meta_path = os.path.join(directory, "meta.json")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        receipt_text = json.dumps(meta.pop("_image_generation"))
        receipt_text = receipt_text.replace(
            '"attempts": 1',
            '"attempts": 2, "attempts": 1',
        )
        meta_text = json.dumps(meta)
        forged = (
            meta_text[:-1]
            + ', "_image_generation": '
            + receipt_text
            + "}"
        )
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write(forged)
        with self.assertRaisesRegex(build_index.ValidationError, "duplicate JSON key"):
            build_index.validate_submission(
                "duplicate-key", "CC0-1.0", self.submissions_dir
            )


class TestReviewedPngTitleAndContributorContract(BuildIndexTestCase):
    def validate_reviewed_png(
        self,
        *,
        title="Reviewed PNG",
        contributor=build_index.REVIEWED_PNG_TRUSTED_CONTRIBUTOR,
    ):
        slug = self.fresh_slug("reviewed-png")
        write_png_submission(
            self.submissions_dir,
            slug,
            payload=make_png(),
            meta_extras={
                "title": title,
                "contributor": contributor,
            },
        )
        return build_index.validate_submission(
            slug, "CC0-1.0", self.submissions_dir
        )

    def assert_invalid_reviewed_png(self, **kwargs):
        pattern = kwargs.pop("pattern")
        with self.assertRaisesRegex(build_index.ValidationError, pattern):
            self.validate_reviewed_png(**kwargs)

    def test_rejects_reviewed_png_title_with_surrounding_whitespace(self):
        self.assert_invalid_reviewed_png(
            title="  Trim Me  ",
            pattern=r"title must be a clean non-empty string of at most 200 characters",
        )

    def test_rejects_reviewed_png_title_over_200_characters(self):
        self.assert_invalid_reviewed_png(
            title="x" * (build_index.REVIEWED_PNG_TITLE_MAX_CHARS + 1),
            pattern=r"title must be a clean non-empty string of at most 200 characters",
        )

    def test_rejects_reviewed_png_title_with_control_characters(self):
        self.assert_invalid_reviewed_png(
            title="Bad\u001fTitle",
            pattern=r"title must be a clean non-empty string of at most 200 characters",
        )

    def test_rejects_reviewed_png_with_wrong_contributor(self):
        self.assert_invalid_reviewed_png(
            contributor="outside-user",
            pattern=re.escape(
                "contributor must be "
                f"'{build_index.REVIEWED_PNG_TRUSTED_CONTRIBUTOR}'"
            ),
        )

    def test_accepts_reviewed_png_title_at_200_character_boundary(self):
        title = "x" * build_index.REVIEWED_PNG_TITLE_MAX_CHARS
        entry = self.validate_reviewed_png(title=title)
        self.assertEqual(title, entry["title"])
        self.assertEqual(
            build_index.REVIEWED_PNG_TRUSTED_CONTRIBUTOR,
            entry["contributor"],
        )

    def test_non_png_submissions_keep_legacy_title_and_contributor_contract(self):
        title = "  Legacy Title  "
        contributor = "outside-user"
        write_submission(
            self.submissions_dir,
            "legacy-svg",
            meta_overrides={
                "title": title,
                "contributor": contributor,
            },
        )
        entry = build_index.validate_submission(
            "legacy-svg", "CC0-1.0", self.submissions_dir
        )
        self.assertEqual(title, entry["title"])
        self.assertEqual(contributor, entry["contributor"])


class TestBuildEntries(BuildIndexTestCase):
    def test_all_kind_extensions_supported(self):
        write_submission(self.submissions_dir, "a-md", meta_overrides={"kind": "md"}, piece_ext="md")
        write_submission(self.submissions_dir, "a-txt", meta_overrides={"kind": "txt"}, piece_ext="txt")
        write_submission(self.submissions_dir, "a-text", meta_overrides={"kind": "text"}, piece_ext="md")
        write_submission(self.submissions_dir, "a-ascii", meta_overrides={"kind": "ascii"}, piece_ext="txt")
        write_submission(self.submissions_dir, "a-svg", meta_overrides={"kind": "svg"}, piece_ext="svg")
        write_submission(self.submissions_dir, "a-prompt", meta_overrides={"kind": "prompt"}, piece_ext="md")
        write_submission(self.submissions_dir, "a-json", meta_overrides={"kind": "json"}, piece_ext="json",
                          piece_content="{}")
        write_png_submission(self.submissions_dir, "a-png")
        entries = build_index.build_entries(self.submissions_dir, "CC0-1.0")
        self.assertEqual(len(entries), 8)

    def test_deterministic_order_by_submitted_at_then_slug(self):
        write_submission(self.submissions_dir, "zzz-later", meta_overrides={"submitted_at": "2026-02-01T00:00:00Z"})
        write_submission(self.submissions_dir, "aaa-earlier", meta_overrides={"submitted_at": "2026-01-01T00:00:00Z"})
        write_submission(self.submissions_dir, "bbb-tie-2", meta_overrides={"submitted_at": "2026-01-15T00:00:00Z"})
        write_submission(self.submissions_dir, "aaa-tie-1", meta_overrides={"submitted_at": "2026-01-15T00:00:00Z"})
        entries = build_index.build_entries(self.submissions_dir, "CC0-1.0")
        slugs = [e["slug"] for e in entries]
        self.assertEqual(slugs, ["aaa-earlier", "aaa-tie-1", "bbb-tie-2", "zzz-later"])

    def test_order_independent_of_filesystem_listing_order(self):
        # Build the same set twice, in different creation order; output must match.
        write_submission(self.submissions_dir, "third", meta_overrides={"submitted_at": "2026-03-01T00:00:00Z"})
        write_submission(self.submissions_dir, "first", meta_overrides={"submitted_at": "2026-01-01T00:00:00Z"})
        write_submission(self.submissions_dir, "second", meta_overrides={"submitted_at": "2026-02-01T00:00:00Z"})
        entries_a = build_index.build_entries(self.submissions_dir, "CC0-1.0")

        tmp2 = tempfile.mkdtemp(prefix="pac-index-test-b-")
        try:
            sub2 = os.path.join(tmp2, "submissions")
            os.makedirs(sub2, exist_ok=True)
            write_submission(sub2, "second", meta_overrides={"submitted_at": "2026-02-01T00:00:00Z"})
            write_submission(sub2, "third", meta_overrides={"submitted_at": "2026-03-01T00:00:00Z"})
            write_submission(sub2, "first", meta_overrides={"submitted_at": "2026-01-01T00:00:00Z"})
            entries_b = build_index.build_entries(sub2, "CC0-1.0")
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)

        self.assertEqual(entries_a, entries_b)

    def test_duplicate_slug_across_directories_impossible_but_meta_mismatch_caught(self):
        # Two directories cannot share a name on disk; simulate the "would collide"
        # case by asserting mismatched meta.slug is caught instead (see above).
        write_submission(self.submissions_dir, "alpha")
        write_submission(self.submissions_dir, "beta", meta_overrides={"slug": "alpha"})
        with self.assertRaises(build_index.ValidationError) as ctx:
            build_index.build_entries(self.submissions_dir, "CC0-1.0")
        self.assertIn("beta", str(ctx.exception))

    def test_multiple_errors_collected_in_one_pass(self):
        write_submission(self.submissions_dir, "alpha", skip_piece=True)
        write_submission(self.submissions_dir, "beta", meta_overrides={"license": "MIT"})
        with self.assertRaises(build_index.ValidationError) as ctx:
            build_index.build_entries(self.submissions_dir, "CC0-1.0")
        message = str(ctx.exception)
        self.assertIn("alpha", message)
        self.assertIn("beta", message)


class TestBuildIndexDocument(BuildIndexTestCase):
    def test_preserves_existing_top_level_fields(self):
        existing = {
            "schema": "rapp-art-submissions-index/1.0",
            "neighborhood_rappid": TEST_NEIGHBORHOOD_RAPPID,
            "_migrated_from": dict(TEST_MIGRATED_FROM),
            "submissions": [],
            "note": "custom note preserved",
        }
        with open(self.index_path(), "w", encoding="utf-8") as f:
            json.dump(existing, f)

        write_submission(self.submissions_dir, "alpha")
        entries = build_index.build_entries(self.submissions_dir, "CC0-1.0")
        doc = build_index.build_index_document(
            entries,
            self.index_path(),
            self.submissions_dir,
        )

        self.assertEqual(doc["neighborhood_rappid"], existing["neighborhood_rappid"])
        self.assertEqual(doc["_migrated_from"], existing["_migrated_from"])
        self.assertEqual(doc["note"], "custom note preserved")
        self.assertEqual([e["slug"] for e in doc["submissions"]], ["alpha"])

    def test_key_order_matches_existing_convention(self):
        existing = {
            "schema": "rapp-art-submissions-index/1.0",
            "neighborhood_rappid": TEST_NEIGHBORHOOD_RAPPID,
            "_migrated_from": dict(TEST_MIGRATED_FROM),
            "submissions": [],
            "note": "note",
        }
        with open(self.index_path(), "w", encoding="utf-8") as f:
            json.dump(existing, f)
        entries = build_index.build_entries(self.submissions_dir, "CC0-1.0")
        doc = build_index.build_index_document(
            entries,
            self.index_path(),
            self.submissions_dir,
        )
        self.assertEqual(
            list(doc.keys()),
            ["schema", "neighborhood_rappid", "_migrated_from", "submissions", "note"],
        )

    def test_render_is_deterministic_and_newline_terminated(self):
        write_submission(self.submissions_dir, "alpha")
        entries = build_index.build_entries(self.submissions_dir, "CC0-1.0")
        doc = build_index.build_index_document(
            entries,
            self.index_path(),
            self.submissions_dir,
        )
        rendered_a = build_index.render(doc)
        rendered_b = build_index.render(doc)
        self.assertEqual(rendered_a, rendered_b)
        self.assertTrue(rendered_a.endswith("\n"))
        self.assertFalse(rendered_a.endswith("\n\n"))

    def test_missing_index_is_seeded_from_neighborhood_identity(self):
        write_submission(self.submissions_dir, "alpha")
        entries = build_index.build_entries(self.submissions_dir, "CC0-1.0")
        doc = build_index.build_index_document(
            entries,
            self.index_path(),
            self.submissions_dir,
        )
        self.assertEqual(doc["neighborhood_rappid"], TEST_NEIGHBORHOOD_RAPPID)
        self.assertEqual(doc["_migrated_from"], TEST_MIGRATED_FROM)


class TestMainCLI(BuildIndexTestCase):
    def run_main(self, *args):
        return build_index.main([
            "--submissions-dir", self.submissions_dir,
            "--index-path", self.index_path(),
            *args,
        ])

    def run_main_capture(self, *args):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = self.run_main(*args)
        return rc, stdout.getvalue(), stderr.getvalue()

    def assert_cli_failure_preserves_index(self, contents, error_pattern):
        for mode in ("--write", "--check"):
            with self.subTest(mode=mode):
                with open(self.index_path(), "w", encoding="utf-8") as f:
                    f.write(contents)
                before = self.read_index_text()
                rc, stdout, stderr = self.run_main_capture(mode)
                self.assertEqual(rc, 1)
                self.assertEqual(stdout, "")
                self.assertRegex(stderr, error_pattern)
                self.assertNotIn("Traceback", stderr)
                self.assertEqual(self.read_index_text(), before)

    def test_check_fails_when_index_missing(self):
        write_submission(self.submissions_dir, "alpha")
        self.assertEqual(self.run_main("--check"), 1)

    def test_write_then_check_succeeds(self):
        write_submission(self.submissions_dir, "alpha")
        self.assertEqual(self.run_main("--write"), 0)
        self.assertEqual(self.run_main("--check"), 0)

    def test_write_is_idempotent(self):
        write_submission(self.submissions_dir, "alpha")
        self.run_main("--write")
        with open(self.index_path(), encoding="utf-8") as f:
            first = f.read()
        self.run_main("--write")
        with open(self.index_path(), encoding="utf-8") as f:
            second = f.read()
        self.assertEqual(first, second)

    def test_malformed_json_index_fails_cleanly_without_touching_file(self):
        write_submission(self.submissions_dir, "alpha")
        self.assert_cli_failure_preserves_index(
            "definitely not json",
            r"error: submissions/index\.json is not valid JSON",
        )

    def test_non_object_json_index_fails_cleanly_without_touching_file(self):
        write_submission(self.submissions_dir, "alpha")
        self.assert_cli_failure_preserves_index(
            '["array", "not", "object"]',
            r"error: submissions/index\.json must be a JSON object",
        )

    def test_unreadable_index_fails_cleanly_without_touching_file(self):
        write_submission(self.submissions_dir, "alpha")
        with open(self.index_path(), "w", encoding="utf-8") as f:
            f.write("{}")
        before = self.read_index_text()
        os.chmod(self.index_path(), 0)
        try:
            for mode in ("--write", "--check"):
                with self.subTest(mode=mode):
                    rc, stdout, stderr = self.run_main_capture(mode)
                    self.assertEqual(rc, 1)
                    self.assertEqual(stdout, "")
                    self.assertRegex(
                        stderr,
                        r"error: cannot read submissions/index\.json",
                    )
                    self.assertNotIn("Traceback", stderr)
        finally:
            os.chmod(self.index_path(), 0o644)
        self.assertEqual(self.read_index_text(), before)

    def test_identity_mismatch_fails_cleanly_without_touching_file(self):
        write_submission(self.submissions_dir, "alpha")
        with open(self.index_path(), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "schema": "rapp-art-submissions-index/1.0",
                    "neighborhood_rappid": (
                        "rappid:@example/public-art-collective:"
                        "ffffffffffffffffffffffffffffffff"
                    ),
                    "_migrated_from": dict(TEST_MIGRATED_FROM),
                    "submissions": [],
                    "note": "custom note preserved",
                },
                f,
            )
        before = self.read_index_text()
        for mode in ("--write", "--check"):
            with self.subTest(mode=mode):
                rc, stdout, stderr = self.run_main_capture(mode)
                self.assertEqual(rc, 1)
                self.assertEqual(stdout, "")
                self.assertRegex(
                    stderr,
                    r"error: submissions/index\.json preserved identity field "
                    r"'neighborhood_rappid' must match neighborhood\.json",
                )
                self.assertNotIn("Traceback", stderr)
                self.assertEqual(self.read_index_text(), before)

    def test_missing_migrated_from_fails_cleanly_without_touching_file(self):
        write_submission(self.submissions_dir, "alpha")
        with open(self.index_path(), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "schema": "rapp-art-submissions-index/1.0",
                    "neighborhood_rappid": TEST_NEIGHBORHOOD_RAPPID,
                    "submissions": [],
                    "note": "custom note preserved",
                },
                f,
            )
        before = self.read_index_text()
        for mode in ("--write", "--check"):
            with self.subTest(mode=mode):
                rc, stdout, stderr = self.run_main_capture(mode)
                self.assertEqual(rc, 1)
                self.assertEqual(stdout, "")
                self.assertRegex(
                    stderr,
                    r"error: submissions/index\.json missing preserved identity field "
                    r"'_migrated_from' from neighborhood\.json",
                )
                self.assertNotIn("Traceback", stderr)
                self.assertEqual(self.read_index_text(), before)

    def test_check_fails_after_new_submission_added_without_regenerating(self):
        write_submission(self.submissions_dir, "alpha")
        self.run_main("--write")
        write_submission(self.submissions_dir, "beta")
        self.assertEqual(self.run_main("--check"), 1)

    def test_check_succeeds_after_regenerating_for_new_submission(self):
        write_submission(self.submissions_dir, "alpha")
        self.run_main("--write")
        write_submission(self.submissions_dir, "beta")
        self.run_main("--write")
        self.assertEqual(self.run_main("--check"), 0)
        with open(self.index_path(), encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc["neighborhood_rappid"], TEST_NEIGHBORHOOD_RAPPID)
        self.assertEqual(doc["_migrated_from"], TEST_MIGRATED_FROM)
        self.assertEqual({e["slug"] for e in doc["submissions"]}, {"alpha", "beta"})

    def test_validate_passes_new_valid_submission_while_check_reports_stale(self):
        # This is exactly the Dada-PR scenario: a new slug lands with no
        # regeneration of index.json. --validate must pass (every submission
        # is individually valid); --check must still catch the staleness.
        write_submission(self.submissions_dir, "alpha")
        self.assertEqual(self.run_main("--write"), 0)

        write_submission(self.submissions_dir, "dada-new-piece")

        self.assertEqual(
            self.run_main("--validate"), 0,
            "--validate must not fail merely because index.json is stale",
        )
        self.assertEqual(
            self.run_main("--check"), 1,
            "--check must still fail while index.json is stale",
        )
        # --validate must never write the file, regardless of staleness.
        with open(self.index_path(), encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual({e["slug"] for e in doc["submissions"]}, {"alpha"})

    def test_valid_png_stale_index_lifecycle(self):
        write_submission(self.submissions_dir, "alpha")
        self.assertEqual(self.run_main("--write"), 0)

        write_png_submission(self.submissions_dir, "dada-visual-piece")

        self.assertEqual(self.run_main("--validate"), 0)
        self.assertEqual(self.run_main("--check"), 1)
        self.assertEqual(self.run_main("--write"), 0)
        self.assertEqual(self.run_main("--check"), 0)

    def test_validate_passes_even_with_no_index_file_at_all(self):
        write_submission(self.submissions_dir, "alpha")
        self.assertFalse(os.path.isfile(self.index_path()))
        self.assertEqual(self.run_main("--validate"), 0)
        self.assertFalse(os.path.isfile(self.index_path()), "--validate must never create index.json")

    def test_invalid_submission_fails_both_validate_and_check(self):
        write_submission(self.submissions_dir, "alpha")
        self.run_main("--write")
        write_submission(self.submissions_dir, "beta", meta_overrides={"license": "MIT"})

        self.assertEqual(self.run_main("--validate"), 1)
        self.assertEqual(self.run_main("--check"), 1)

    def test_main_exits_nonzero_on_invalid_submission(self):
        write_submission(self.submissions_dir, "alpha", meta_overrides={"license": "MIT"})
        self.assertEqual(self.run_main("--check"), 1)
        self.assertEqual(self.run_main("--write"), 1)
        self.assertEqual(self.run_main("--validate"), 1)

    def test_validate_and_check_are_mutually_exclusive(self):
        write_submission(self.submissions_dir, "alpha")
        with self.assertRaises(SystemExit):
            self.run_main("--validate", "--check")


class TestRealRepoFixture(unittest.TestCase):
    """Sanity-check the real submissions/ tree in this checkout, if present."""

    def test_real_repo_submissions_all_validate(self):
        repo_submissions = build_index.SUBMISSIONS_DIR
        if not os.path.isdir(repo_submissions):
            self.skipTest("no submissions/ directory in this checkout")
        # A submission PR deliberately leaves the generated index stale until
        # the post-merge writer runs. Self-tests must prove every submission
        # is valid without reintroducing that freshness deadlock.
        rc = build_index.main(["--validate"])
        self.assertEqual(rc, 0, "real repo submissions should all validate")


if __name__ == "__main__":
    unittest.main()
