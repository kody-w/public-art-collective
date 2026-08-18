#!/usr/bin/env python3
"""test_build_index.py — self-tests for tools/build_index.py.

Stdlib-only (unittest + tempfile). Builds small fixture submissions/ trees in a
temp directory per test so the real repo's submissions/ is never touched.

Run:
  python3 -m unittest tools.test_build_index -v
  python3 tools/test_build_index.py
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_index  # noqa: E402


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
        with open(os.path.join(d, f"piece.{piece_ext}"), "w", encoding="utf-8") as f:
            f.write(piece_content)
    return d


class BuildIndexTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pac-index-test-")
        self.submissions_dir = os.path.join(self.tmp, "submissions")
        os.makedirs(self.submissions_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def index_path(self):
        return os.path.join(self.submissions_dir, "index.json")


class TestDiscoverAndValidate(BuildIndexTestCase):
    def test_discovers_every_submission_directory(self):
        write_submission(self.submissions_dir, "alpha")
        write_submission(self.submissions_dir, "beta")
        write_submission(self.submissions_dir, "gamma")
        slugs = build_index.discover_submission_dirs(self.submissions_dir)
        self.assertEqual(slugs, ["alpha", "beta", "gamma"])

    def test_ignores_non_directories_and_dotfiles(self):
        write_submission(self.submissions_dir, "alpha")
        with open(os.path.join(self.submissions_dir, "index.json"), "w") as f:
            f.write("{}")
        os.makedirs(os.path.join(self.submissions_dir, ".hidden"), exist_ok=True)
        slugs = build_index.discover_submission_dirs(self.submissions_dir)
        self.assertEqual(slugs, ["alpha"])

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


class TestBuildEntries(BuildIndexTestCase):
    def test_all_kind_extensions_supported(self):
        write_submission(self.submissions_dir, "a-text", meta_overrides={"kind": "text"}, piece_ext="md")
        write_submission(self.submissions_dir, "a-ascii", meta_overrides={"kind": "ascii"}, piece_ext="txt")
        write_submission(self.submissions_dir, "a-svg", meta_overrides={"kind": "svg"}, piece_ext="svg")
        write_submission(self.submissions_dir, "a-prompt", meta_overrides={"kind": "prompt"}, piece_ext="md")
        write_submission(self.submissions_dir, "a-json", meta_overrides={"kind": "json"}, piece_ext="json",
                          piece_content="{}")
        entries = build_index.build_entries(self.submissions_dir, "CC0-1.0")
        self.assertEqual(len(entries), 5)

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
            "neighborhood_rappid": "rappid:@kody-w/public-art-collective:abc123",
            "_migrated_from": {"neighborhood_rappid": "abc-123"},
            "submissions": [],
            "note": "custom note preserved",
        }
        with open(self.index_path(), "w", encoding="utf-8") as f:
            json.dump(existing, f)

        write_submission(self.submissions_dir, "alpha")
        entries = build_index.build_entries(self.submissions_dir, "CC0-1.0")
        doc = build_index.build_index_document(entries, self.index_path())

        self.assertEqual(doc["neighborhood_rappid"], existing["neighborhood_rappid"])
        self.assertEqual(doc["_migrated_from"], existing["_migrated_from"])
        self.assertEqual(doc["note"], "custom note preserved")
        self.assertEqual([e["slug"] for e in doc["submissions"]], ["alpha"])

    def test_key_order_matches_existing_convention(self):
        existing = {
            "schema": "rapp-art-submissions-index/1.0",
            "neighborhood_rappid": "rappid:@kody-w/public-art-collective:abc123",
            "_migrated_from": {"neighborhood_rappid": "abc-123"},
            "submissions": [],
            "note": "note",
        }
        with open(self.index_path(), "w", encoding="utf-8") as f:
            json.dump(existing, f)
        entries = build_index.build_entries(self.submissions_dir, "CC0-1.0")
        doc = build_index.build_index_document(entries, self.index_path())
        self.assertEqual(
            list(doc.keys()),
            ["schema", "neighborhood_rappid", "_migrated_from", "submissions", "note"],
        )

    def test_render_is_deterministic_and_newline_terminated(self):
        write_submission(self.submissions_dir, "alpha")
        entries = build_index.build_entries(self.submissions_dir, "CC0-1.0")
        doc = build_index.build_index_document(entries, self.index_path())
        rendered_a = build_index.render(doc)
        rendered_b = build_index.render(doc)
        self.assertEqual(rendered_a, rendered_b)
        self.assertTrue(rendered_a.endswith("\n"))
        self.assertFalse(rendered_a.endswith("\n\n"))


class TestMainCLI(BuildIndexTestCase):
    def run_main(self, *args):
        return build_index.main([
            "--submissions-dir", self.submissions_dir,
            "--index-path", self.index_path(),
            *args,
        ])

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

    def test_real_repo_submissions_all_validate_and_index_is_current(self):
        repo_submissions = build_index.SUBMISSIONS_DIR
        if not os.path.isdir(repo_submissions):
            self.skipTest("no submissions/ directory in this checkout")
        rc = build_index.main(["--check"])
        self.assertEqual(rc, 0, "real repo submissions/index.json should validate + be current")


if __name__ == "__main__":
    unittest.main()
