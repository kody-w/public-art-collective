#!/usr/bin/env python3
"""Offline tests for the protected reviewed-PNG provenance gate."""
import contextlib
import copy
import hashlib
import io
import json
import os
import re
import shutil
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_png_attestation as attestation  # noqa: E402
from test_build_index import (  # noqa: E402
    BuildIndexTestCase,
    FIXTURES_DIR,
    make_png,
    write_png_submission,
    write_submission,
)


ROOT = Path(__file__).resolve().parents[1]
BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40
COMMIT_DATE = "2026-08-23T01:02:03Z"


def git_blob_sha(path):
    payload = Path(path).read_bytes()
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def user(login):
    return {"login": login, "type": "User"}


def repository(full_name, fork=False):
    return {
        "full_name": full_name,
        "fork": fork,
        "owner": user(full_name.split("/", 1)[0]),
    }


class TestPngAttestation(BuildIndexTestCase):
    def setUp(self):
        super().setUp()
        self.trusted_base_sha = BASE_SHA
        self.base_root = os.path.join(self.tmp, "trusted-base")
        os.mkdir(self.base_root)
        os.mkdir(os.path.join(self.base_root, "submissions"))
        self.candidate_workflow_dir = (
            Path(self.tmp) / ".github" / "workflows"
        )
        self.candidate_workflow_dir.mkdir(parents=True)
        for relative in attestation.REQUIRED_CANDIDATE_WORKFLOWS:
            source = ROOT / relative
            shutil.copy2(source, self.candidate_workflow_dir / source.name)
        shutil.copy2(
            self.neighborhood_path(),
            os.path.join(self.base_root, "neighborhood.json"),
        )
        self.slug = "controller-piece"
        self.payload = make_png(width=512, height=512)
        with open(
            os.path.join(FIXTURES_DIR, "dada-controller-receipt.json"),
            encoding="utf-8",
        ) as handle:
            receipt = json.load(handle)
        write_png_submission(
            self.submissions_dir,
            self.slug,
            payload=self.payload,
            receipt=receipt,
            meta_extras={
                "contributor": attestation.TRUSTED_OWNER,
                "_dada_cycle": {
                    "cycle": 7,
                    "rounds": [{"winner": "a"}, {"winner": "b"}],
                },
            },
        )
        self.event, self.evidence = self.make_evidence(
            self.slug, "piece.png"
        )

    def make_evidence(
        self,
        slug,
        piece_name,
        author=attestation.TRUSTED_OWNER,
        head_repo=attestation.TRUSTED_REPOSITORY,
        fork=False,
        branch=None,
    ):
        meta_path = os.path.join(
            self.submissions_dir, slug, "meta.json"
        )
        with open(meta_path, encoding="utf-8") as handle:
            meta = json.load(handle)
        title = meta["title"]
        rounds = meta.get("_dada_cycle", {}).get("rounds", [{}])
        cycle = meta.get("_dada_cycle", {}).get("cycle", 1)
        subject = f"art: {title} ({slug})"
        message = (
            subject
            + "\n\n"
            + "Autonomous submission by the openrappter neighbor of "
              "Dada Collective.\n"
            + f"Dada cycle {cycle}, {len(rounds)} round(s) of 10 candidates.\n"
        )
        head_repo_data = repository(head_repo, fork=fork)
        base_repo_data = repository(attestation.TRUSTED_REPOSITORY)
        branch = branch or f"art/dada/{slug}-deadbeef"
        pull_request = {
            "number": 42,
            "state": "open",
            "draft": False,
            "title": subject,
            "commits": 1,
            "changed_files": 2,
            "author_association": (
                "OWNER" if author == attestation.TRUSTED_OWNER else "NONE"
            ),
            "user": user(author),
            "base": {
                "ref": attestation.TRUSTED_BASE_BRANCH,
                "sha": BASE_SHA,
                "repo": base_repo_data,
            },
            "head": {
                "ref": branch,
                "sha": HEAD_SHA,
                "repo": head_repo_data,
            },
        }
        event = {
            "action": "opened",
            "number": 42,
            "repository": base_repo_data,
            "pull_request": copy.deepcopy(pull_request),
        }
        commit = {
            "sha": HEAD_SHA,
            "parents": [{"sha": BASE_SHA}],
            "author": user(attestation.TRUSTED_OWNER),
            "committer": user(attestation.TRUSTED_OWNER),
            "commit": {
                "author": {
                    "name": attestation.DADA_COMMIT_AUTHOR_NAME,
                    "email": attestation.DADA_COMMIT_AUTHOR_EMAIL,
                    "date": COMMIT_DATE,
                },
                "committer": {
                    "name": attestation.DADA_COMMITTER_NAME,
                    "email": attestation.DADA_COMMITTER_EMAIL,
                    "date": COMMIT_DATE,
                },
                "message": message,
                "verification": {
                    "verified": False,
                    "reason": "unsigned",
                    "signature": None,
                    "payload": None,
                },
            },
        }
        piece_path = os.path.join(
            self.submissions_dir, slug, piece_name
        )
        files = [
            {
                "filename": f"submissions/{slug}/meta.json",
                "status": "added",
                "sha": git_blob_sha(meta_path),
            },
            {
                "filename": f"submissions/{slug}/{piece_name}",
                "status": "added",
                "sha": git_blob_sha(piece_path),
            },
        ]
        evidence = {
            "pull_request": copy.deepcopy(pull_request),
            "commits": [commit],
            "files": files,
            "head_commit": copy.deepcopy(commit),
            "pull_request_after": copy.deepcopy(pull_request),
        }
        return event, evidence

    def verify(self):
        return attestation.verify(
            self.event,
            self.evidence,
            self.tmp,
            self.base_root,
            self.trusted_base_sha,
        )

    def update_both_prs(self, mutator):
        mutator(self.event["pull_request"])
        mutator(self.evidence["pull_request"])
        mutator(self.evidence["pull_request_after"])

    def refresh_meta_blob(self):
        path = f"submissions/{self.slug}/meta.json"
        full_path = os.path.join(
            self.submissions_dir, self.slug, "meta.json"
        )
        for record in self.evidence["files"]:
            if record["filename"] == path:
                record["sha"] = git_blob_sha(full_path)

    def configure_takedown(self):
        source = os.path.join(self.submissions_dir, self.slug)
        destination = os.path.join(
            self.base_root, "submissions", self.slug
        )
        shutil.copytree(source, destination)
        shutil.rmtree(source)
        self.update_both_prs(
            lambda pr: pr["head"].update(
                ref=f"art/takedown/{self.slug}-deadbeef"
            )
        )
        for record in self.evidence["files"]:
            record["status"] = "removed"

    def candidate_workflow_path(self, name):
        return self.candidate_workflow_dir / name

    def write_candidate_workflow(self, name, content):
        path = self.candidate_workflow_path(name)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    def configure_non_png(self, slug="outside-svg"):
        shutil.rmtree(os.path.join(self.submissions_dir, self.slug))
        write_submission(
            self.submissions_dir,
            slug,
            meta_overrides={"contributor": "outside-user"},
        )
        self.event, self.evidence = self.make_evidence(
            slug,
            "piece.svg",
            author="outside-user",
            head_repo="outside-user/public-art-collective",
            fork=True,
            branch=f"art/{slug}",
        )

    def add_workflow_file_evidence(self, path, status="added"):
        relative = str(path.relative_to(self.tmp))
        self.evidence["files"].append({
            "filename": relative,
            "status": status,
            "sha": git_blob_sha(path),
        })
        self.update_both_prs(
            lambda pr: pr.update(
                changed_files=len(self.evidence["files"])
            )
        )

    def test_valid_controller_fixture_is_attested(self):
        self.assertEqual(self.slug, self.verify())

    def test_unrelated_pr_with_unchanged_safe_workflows_passes(self):
        self.evidence["files"] = [{
            "filename": "README.md",
            "status": "modified",
            "sha": "3" * 40,
        }]
        self.update_both_prs(lambda pr: pr.update(changed_files=1))
        self.evidence["commits"] = None
        self.evidence["head_commit"] = None
        self.assertIsNone(self.verify())

    def test_candidate_workflow_policy_accepts_safe_yaml_without_execution(self):
        self.configure_non_png()
        sentinel = Path(self.tmp) / "candidate-workflow-executed"
        workflow = self.write_candidate_workflow(
            "safe-unrelated.yaml",
            (
                "name: Safe unrelated workflow\n"
                "on:\n"
                "  pull_request:\n"
                "permissions:\n"
                "  contents: read\n"
                "jobs:\n"
                "  safe:\n"
                "    name: Safe unrelated check\n"
                "    runs-on: ubuntu-latest\n"
                "    permissions:\n"
                "      contents: read\n"
                "    steps:\n"
                "      - name: Candidate script remains data\n"
                "        run: |\n"
                f"          touch {sentinel}\n"
            ),
        )
        self.add_workflow_file_evidence(workflow)

        self.assertIsNone(self.verify())
        self.assertFalse(sentinel.exists())

    def test_candidate_workflow_policy_accepts_current_required_workflows(self):
        attestation._validate_candidate_workflow_policy(self.tmp)

    def test_candidate_workflow_policy_rejects_rogue_checks_write(self):
        self.configure_non_png()
        workflow = self.write_candidate_workflow(
            "rogue.yaml",
            (
                "name: Rogue check writer\n"
                "on: pull_request\n"
                "jobs:\n"
                "  rogue:\n"
                "    name: Rogue\n"
                "    runs-on: ubuntu-latest\n"
                "    permissions:\n"
                "      checks: write\n"
                "      contents: read\n"
                "    steps:\n"
                "      - run: echo no\n"
            ),
        )
        self.add_workflow_file_evidence(workflow)

        with self.assertRaisesRegex(
            attestation.AttestationError,
            r"semantic 'checks: write' is allowed only.*rogue\.yaml.*rogue",
        ):
            self.verify()

    def test_candidate_workflow_policy_rejects_top_level_checks_write(self):
        self.write_candidate_workflow(
            "top-level.yml",
            (
                "name: Top-level check writer\n"
                "on: pull_request\n"
                "permissions:\n"
                "  checks: write\n"
                "jobs:\n"
                "  harmless:\n"
                "    name: Harmless\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - run: echo no\n"
            ),
        )
        with self.assertRaisesRegex(
            attestation.AttestationError,
            r"top-level semantic 'checks: write' is forbidden.*top-level\.yml",
        ):
            attestation._validate_candidate_workflow_policy(self.tmp)

    def test_candidate_workflow_policy_recognizes_quoted_checks_write(self):
        self.write_candidate_workflow(
            "quoted.yml",
            (
                "name: Quoted check writer\n"
                "on: pull_request\n"
                "jobs:\n"
                "  quoted:\n"
                "    name: Quoted\n"
                "    runs-on: ubuntu-latest\n"
                "    permissions:\n"
                "      \"checks\": 'write' # still semantic write\n"
                "    steps:\n"
                "      - run: echo no\n"
            ),
        )
        with self.assertRaisesRegex(
            attestation.AttestationError,
            r"semantic 'checks: write' is allowed only.*quoted\.yml",
        ):
            attestation._validate_candidate_workflow_policy(self.tmp)

    def test_candidate_workflow_policy_rejects_plain_scalar_name_continuation(
        self,
    ):
        self.write_candidate_workflow(
            "duplicate-context.yml",
            (
                "name: Duplicate context\n"
                "on: pull_request\n"
                "jobs:\n"
                "  duplicate:\n"
                "    name: Verify\n"
                "      controller provenance\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - run: echo no\n"
            ),
        )
        with self.assertRaisesRegex(
            attestation.AttestationError,
            r"duplicate-context\.yml.*plain scalar or continuation "
            r"outside a block scalar",
        ):
            attestation._validate_candidate_workflow_policy(self.tmp)

    def test_candidate_workflow_policy_rejects_split_plain_scalar_name(
        self,
    ):
        self.write_candidate_workflow(
            "duplicate-context-two.yml",
            (
                "name: Duplicate context two\n"
                "on: pull_request\n"
                "jobs:\n"
                "  duplicate:\n"
                "    name: Verify controller\n"
                "      provenance\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - run: echo no\n"
            ),
        )
        with self.assertRaisesRegex(
            attestation.AttestationError,
            r"duplicate-context-two\.yml.*plain scalar or continuation "
            r"outside a block scalar",
        ):
            attestation._validate_candidate_workflow_policy(self.tmp)

    def test_candidate_workflow_policy_rejects_noncanonical_display_name(self):
        self.write_candidate_workflow(
            "display-name-whitespace.yml",
            (
                "name: Duplicate context spacing\n"
                "on: pull_request\n"
                "jobs:\n"
                "  duplicate:\n"
                "    name: 'Verify  controller provenance'\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - run: echo no\n"
            ),
        )
        with self.assertRaisesRegex(
            attestation.AttestationError,
            r"display-name-whitespace\.yml.*non-canonical display name",
        ):
            attestation._validate_candidate_workflow_policy(self.tmp)

    def test_split_workflow_mapping_handles_doubled_single_quotes(self):
        with self.assertRaisesRegex(
            attestation.AttestationError,
            r"quoted-key\.yml.*unsupported mapping key \"name's\"",
        ):
            attestation._split_workflow_mapping(
                "'name''s': value",
                "quoted-key.yml",
                7,
            )

    def test_candidate_workflow_policy_rejects_inline_permissions(self):
        self.write_candidate_workflow(
            "inline.yml",
            (
                "name: Inline permissions\n"
                "on: pull_request\n"
                "permissions: { checks: write }\n"
                "jobs:\n"
                "  inline:\n"
                "    name: Inline\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - run: echo no\n"
            ),
        )
        with self.assertRaisesRegex(
            attestation.AttestationError,
            r"inline permissions form.*top level",
        ):
            attestation._validate_candidate_workflow_policy(self.tmp)

    def test_candidate_workflow_policy_rejects_write_all(self):
        self.write_candidate_workflow(
            "write-all.yml",
            (
                "name: Implicit check writer\n"
                "on: pull_request\n"
                "jobs:\n"
                "  implicit:\n"
                "    name: Implicit\n"
                "    runs-on: ubuntu-latest\n"
                "    permissions: 'write-all'\n"
                "    steps:\n"
                "      - run: echo no\n"
            ),
        )
        with self.assertRaisesRegex(
            attestation.AttestationError,
            r"forbidden permissions value 'write-all'.*job 'implicit'",
        ):
            attestation._validate_candidate_workflow_policy(self.tmp)

    def test_candidate_workflow_policy_rejects_anchors_and_aliases(self):
        for name, permissions in (
            (
                "anchor.yml",
                "permissions: &danger\n  checks: write\n",
            ),
            (
                "alias.yml",
                "permissions: *danger\n",
            ),
        ):
            with self.subTest(name=name):
                path = self.write_candidate_workflow(
                    name,
                    (
                        "name: YAML indirection\n"
                        "on: pull_request\n"
                        + permissions
                        + "jobs:\n"
                        "  indirection:\n"
                        "    name: Indirection\n"
                        "    runs-on: ubuntu-latest\n"
                        "    steps:\n"
                        "      - run: echo no\n"
                    ),
                )
                with self.assertRaisesRegex(
                    attestation.AttestationError,
                    r"YAML anchor or alias",
                ):
                    attestation._validate_candidate_workflow_policy(self.tmp)
                path.unlink()

    def test_candidate_workflow_policy_rejects_duplicate_context_producer(self):
        self.write_candidate_workflow(
            "duplicate-context.yml",
            (
                "name: Duplicate context\n"
                "on: pull_request\n"
                "permissions:\n"
                "  contents: read\n"
                "jobs:\n"
                "  duplicate:\n"
                "    name: \"Verify controller provenance\" # reserved\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - run: echo no\n"
            ),
        )
        with self.assertRaisesRegex(
            attestation.AttestationError,
            r"job display name 'Verify controller provenance' is reserved"
            r".*duplicate-context\.yml.*duplicate",
        ):
            attestation._validate_candidate_workflow_policy(self.tmp)

    def test_candidate_workflow_policy_rejects_renamed_required_job(self):
        path = self.candidate_workflow_path(
            "reviewed-png-attestation.yml"
        )
        workflow = path.read_text(encoding="utf-8")
        old = "    name: Verify controller provenance\n"
        self.assertIn(old, workflow)
        path.write_text(
            workflow.replace(
                old,
                "    name: Renamed controller provenance\n",
                1,
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            attestation.AttestationError,
            r"must declare display name exactly 'Verify controller provenance'",
        ):
            attestation._validate_candidate_workflow_policy(self.tmp)

    def test_candidate_workflow_policy_rejects_renamed_required_job_id(self):
        path = self.candidate_workflow_path(
            "reviewed-png-attestation.yml"
        )
        workflow = path.read_text(encoding="utf-8")
        old = "  verify-controller-provenance:\n"
        self.assertIn(old, workflow)
        path.write_text(
            workflow.replace(
                old,
                "  renamed-controller-provenance:\n",
                1,
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            attestation.AttestationError,
            r"display name 'Verify controller provenance' is reserved",
        ):
            attestation._validate_candidate_workflow_policy(self.tmp)

    def test_candidate_workflow_policy_rejects_deleted_required_workflow(self):
        for relative in sorted(attestation.REQUIRED_CANDIDATE_WORKFLOWS):
            with self.subTest(relative=relative):
                path = Path(self.tmp) / relative
                payload = path.read_bytes()
                path.unlink()
                with self.assertRaisesRegex(
                    attestation.AttestationError,
                    rf"required workflow '{re.escape(relative)}' is missing",
                ):
                    attestation._validate_candidate_workflow_policy(self.tmp)
                path.write_bytes(payload)

    def test_candidate_workflow_policy_rejects_invalid_utf8(self):
        self.write_candidate_workflow(
            "invalid-encoding.yaml",
            b"name: invalid\njobs:\n  invalid:\n    name: \xff\n",
        )
        with self.assertRaisesRegex(
            attestation.AttestationError,
            r"invalid-encoding\.yaml.*not valid UTF-8",
        ):
            attestation._validate_candidate_workflow_policy(self.tmp)

    def test_candidate_workflow_policy_rejects_oversized_file(self):
        self.write_candidate_workflow(
            "oversized.yml",
            b"#" * (attestation.MAX_CANDIDATE_WORKFLOW_FILE_BYTES + 1),
        )
        with self.assertRaisesRegex(
            attestation.AttestationError,
            r"oversized\.yml.*exceeds the .*byte file limit",
        ):
            attestation._validate_candidate_workflow_policy(self.tmp)

    def test_candidate_workflow_policy_rejects_oversized_file_count(self):
        additional = attestation.MAX_CANDIDATE_WORKFLOW_FILES - 1
        for index in range(additional):
            self.write_candidate_workflow(
                f"count-{index:03d}.yml",
                (
                    f"name: Count {index}\n"
                    "jobs:\n"
                    f"  count_{index}:\n"
                    f"    name: Count {index}\n"
                    "    runs-on: ubuntu-latest\n"
                ),
            )
        with self.assertRaisesRegex(
            attestation.AttestationError,
            rf"contains more than "
            rf"{attestation.MAX_CANDIDATE_WORKFLOW_FILES} entries",
        ):
            attestation._validate_candidate_workflow_policy(self.tmp)

    def test_candidate_workflow_policy_rejects_symlink(self):
        path = self.candidate_workflow_path("linked.yml")
        os.symlink("submissions-index.yml", path)
        with self.assertRaisesRegex(
            attestation.AttestationError,
            r"linked\.yml.*regular file, not symlink",
        ):
            attestation._validate_candidate_workflow_policy(self.tmp)

    def test_candidate_workflow_policy_rejects_special_file(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFO creation is unavailable")
        path = self.candidate_workflow_path("special.yml")
        os.mkfifo(path)
        with self.assertRaisesRegex(
            attestation.AttestationError,
            r"special\.yml.*regular file, not special file",
        ):
            attestation._validate_candidate_workflow_policy(self.tmp)

    def test_candidate_workflow_policy_rejects_nested_workflow_directory(self):
        nested = self.candidate_workflow_path("nested")
        nested.mkdir()
        (nested / "escape.yml").write_text(
            "jobs: {}\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(
            attestation.AttestationError,
            r"workflow entry .*nested.*regular file, not directory",
        ):
            attestation._validate_candidate_workflow_policy(self.tmp)

    def test_candidate_workflow_policy_rejects_unpinned_required_checkout(self):
        path = self.candidate_workflow_path(
            "reviewed-png-attestation.yml"
        )
        workflow = path.read_text(encoding="utf-8")
        pinned = "actions/checkout@" + attestation.PINNED_CHECKOUT_ACTION_SHA
        self.assertIn(pinned, workflow)
        path.write_text(
            workflow.replace(pinned, "actions/checkout@v4", 1),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            attestation.AttestationError,
            r"must pin actions/checkout to '[0-9a-f]{40}'",
        ):
            attestation._validate_candidate_workflow_policy(self.tmp)

    def test_controller_contract_fixture_matches_production_constants(self):
        contract_path = (
            ROOT / "tools" / "fixtures" / "dada-controller-contract.json"
        )
        with contract_path.open(encoding="utf-8") as handle:
            fixture = json.load(handle)
        self.assertEqual(
            attestation._production_controller_contract(),
            fixture,
        )
        self.assertEqual(fixture, attestation._require_controller_contract())

    def test_runtime_rejects_one_sided_controller_constant_drift(self):
        with mock.patch.object(
            attestation,
            "DADA_MAX_ROUNDS",
            attestation.DADA_MAX_ROUNDS + 1,
        ):
            with self.assertRaisesRegex(
                attestation.AttestationError,
                "contract fixture does not exactly match",
            ):
                self.verify()

    def test_valid_owner_takedown_is_authorized(self):
        self.configure_takedown()
        self.assertFalse(
            os.path.lexists(
                os.path.join(self.submissions_dir, self.slug)
            )
        )
        self.assertEqual(
            attestation.TAKEDOWN_RESULT_PREFIX + self.slug,
            self.verify(),
        )

    def test_takedown_from_fork_is_rejected(self):
        self.configure_takedown()

        def make_fork(pr):
            pr["head"]["repo"] = repository(
                "outside-user/public-art-collective", fork=True
            )

        self.update_both_prs(make_fork)
        with self.assertRaisesRegex(
            attestation.AttestationError, "pinned owner repository"
        ):
            self.verify()

    def test_takedown_wrong_owner_or_association_is_rejected(self):
        self.configure_takedown()

        def change_author(pr):
            pr["user"] = user("outside-user")
            pr["author_association"] = "NONE"

        self.update_both_prs(change_author)
        with self.assertRaisesRegex(
            attestation.AttestationError, r"user\.login"
        ):
            self.verify()

    def test_takedown_partial_removal_is_rejected(self):
        self.configure_takedown()
        self.evidence["files"] = self.evidence["files"][:1]
        self.update_both_prs(lambda pr: pr.update(changed_files=1))
        with self.assertRaisesRegex(
            attestation.AttestationError, "remove exactly"
        ):
            self.verify()

    def test_takedown_extra_file_is_rejected(self):
        self.configure_takedown()
        self.evidence["files"].append({
            "filename": "README.md",
            "status": "modified",
            "sha": "3" * 40,
        })
        self.update_both_prs(lambda pr: pr.update(changed_files=3))
        with self.assertRaisesRegex(
            attestation.AttestationError, "remove exactly"
        ):
            self.verify()

    def test_takedown_rename_is_rejected(self):
        self.configure_takedown()
        self.evidence["files"][0].update(
            status="renamed",
            previous_filename=(
                f"submissions/{self.slug}/old-meta.json"
            ),
        )
        with self.assertRaisesRegex(
            attestation.AttestationError, "status 'removed'"
        ):
            self.verify()

    def test_takedown_ordinary_branch_is_rejected(self):
        self.configure_takedown()
        self.update_both_prs(
            lambda pr: pr["head"].update(ref="emergency/remove-art")
        )
        with self.assertRaisesRegex(
            attestation.AttestationError, "art/takedown"
        ):
            self.verify()

    def test_takedown_invalid_base_receipt_is_rejected(self):
        self.configure_takedown()
        meta_path = os.path.join(
            self.base_root,
            "submissions",
            self.slug,
            "meta.json",
        )
        with open(meta_path, encoding="utf-8") as handle:
            meta = json.load(handle)
        meta["_image_generation"]["image_sha256"] = "0" * 64
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump(meta, handle)
        with self.assertRaisesRegex(
            attestation.AttestationError,
            "trusted base submission tree.*structural validation",
        ):
            self.verify()

    def test_takedown_ignores_unrelated_invalid_base_submission(self):
        self.configure_takedown()
        unrelated_slug = "unrelated-invalid"
        write_submission(
            self.submissions_dir,
            unrelated_slug,
            skip_piece=True,
        )
        write_submission(
            os.path.join(self.base_root, "submissions"),
            unrelated_slug,
            skip_piece=True,
        )
        self.assertEqual(
            attestation.TAKEDOWN_RESULT_PREFIX + self.slug,
            self.verify(),
        )

        meta_path = os.path.join(
            self.base_root,
            "submissions",
            self.slug,
            "meta.json",
        )
        with open(meta_path, encoding="utf-8") as handle:
            meta = json.load(handle)
        meta["_image_generation"]["image_sha256"] = "0" * 64
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump(meta, handle)
        with self.assertRaisesRegex(
            attestation.AttestationError,
            "trusted base submission tree.*structural validation",
        ):
            self.verify()

    def test_takedown_mixed_with_submission_is_rejected(self):
        self.configure_takedown()
        slug = "mixed-svg"
        write_submission(self.submissions_dir, slug)
        for name in ("meta.json", "piece.svg"):
            path = os.path.join(self.submissions_dir, slug, name)
            self.evidence["files"].append({
                "filename": f"submissions/{slug}/{name}",
                "status": "added",
                "sha": git_blob_sha(path),
            })
        self.update_both_prs(lambda pr: pr.update(changed_files=4))
        with self.assertRaisesRegex(
            attestation.AttestationError, "remove exactly"
        ):
            self.verify()

    def test_takedown_stale_trusted_base_checkout_is_rejected(self):
        self.configure_takedown()
        self.trusted_base_sha = "9" * 40
        with self.assertRaisesRegex(
            attestation.AttestationError, "stale trusted base evidence"
        ):
            self.verify()

    def test_fork_png_receipt_is_rejected(self):
        def make_fork(pr):
            pr["head"]["repo"] = repository(
                "outside-user/public-art-collective", fork=True
            )

        self.update_both_prs(make_fork)
        with self.assertRaisesRegex(
            attestation.AttestationError, "pinned owner repository"
        ):
            self.verify()

    def test_non_owner_pr_author_is_rejected(self):
        def change_author(pr):
            pr["user"] = user("outside-user")
            pr["author_association"] = "NONE"

        self.update_both_prs(change_author)
        with self.assertRaisesRegex(
            attestation.AttestationError, r"user\.login"
        ):
            self.verify()

    def test_direct_non_dada_branch_is_rejected(self):
        self.update_both_prs(
            lambda pr: pr["head"].update(ref="feature/direct-upload")
        )
        with self.assertRaisesRegex(
            attestation.AttestationError, "art/dada"
        ):
            self.verify()

    def test_branch_must_bind_the_submission_slug(self):
        self.update_both_prs(
            lambda pr: pr["head"].update(
                ref="art/dada/different-piece-deadbeef"
            )
        )
        with self.assertRaisesRegex(
            attestation.AttestationError, self.slug
        ):
            self.verify()

    def test_forged_digest_bound_receipt_is_rejected(self):
        meta_path = os.path.join(
            self.submissions_dir, self.slug, "meta.json"
        )
        with open(meta_path, encoding="utf-8") as handle:
            meta = json.load(handle)
        meta["_image_generation"]["image_sha256"] = "0" * 64
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump(meta, handle)
        self.refresh_meta_blob()
        with self.assertRaisesRegex(
            attestation.AttestationError, "structural validation"
        ):
            self.verify()

    def test_structural_validation_rejects_whitespace_reviewed_png_title(self):
        meta_path = os.path.join(
            self.submissions_dir, self.slug, "meta.json"
        )
        with open(meta_path, encoding="utf-8") as handle:
            meta = json.load(handle)
        meta["title"] = f"  {meta['title']}  "
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump(meta, handle)
        self.refresh_meta_blob()
        with self.assertRaisesRegex(
            attestation.AttestationError,
            "structural validation: .*title must be a clean non-empty string",
        ):
            self.verify()

    def test_structural_validation_rejects_wrong_reviewed_png_contributor(self):
        meta_path = os.path.join(
            self.submissions_dir, self.slug, "meta.json"
        )
        with open(meta_path, encoding="utf-8") as handle:
            meta = json.load(handle)
        meta["contributor"] = "outside-user"
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump(meta, handle)
        self.refresh_meta_blob()
        with self.assertRaisesRegex(
            attestation.AttestationError,
            r"structural validation: .*contributor must be 'kody-w'",
        ):
            self.verify()

    def test_sparse_candidate_uses_non_default_trusted_base_license(self):
        trusted_neighborhood = os.path.join(
            self.base_root, "neighborhood.json"
        )
        with open(trusted_neighborhood, encoding="utf-8") as handle:
            neighborhood = json.load(handle)
        neighborhood["contribution_policy"]["license"] = (
            "MIT — accepted by the trusted base for this test"
        )
        with open(trusted_neighborhood, "w", encoding="utf-8") as handle:
            json.dump(neighborhood, handle)

        meta_path = os.path.join(
            self.submissions_dir, self.slug, "meta.json"
        )
        with open(meta_path, encoding="utf-8") as handle:
            meta = json.load(handle)
        meta["license"] = "MIT"
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump(meta, handle)
        self.refresh_meta_blob()
        os.remove(self.neighborhood_path())

        with mock.patch.object(
            attestation.build_index,
            "accepted_license",
            wraps=attestation.build_index.accepted_license,
        ) as accepted_license:
            self.assertEqual(self.slug, self.verify())
        accepted_license.assert_called_once_with(trusted_neighborhood)

    def test_sparse_candidate_rejects_stale_default_license(self):
        trusted_neighborhood = os.path.join(
            self.base_root, "neighborhood.json"
        )
        with open(trusted_neighborhood, encoding="utf-8") as handle:
            neighborhood = json.load(handle)
        neighborhood["contribution_policy"]["license"] = (
            "MIT — accepted by the trusted base for this test"
        )
        with open(trusted_neighborhood, "w", encoding="utf-8") as handle:
            json.dump(neighborhood, handle)
        os.remove(self.neighborhood_path())

        with self.assertRaisesRegex(
            attestation.AttestationError,
            r"structural validation: .*license 'CC0-1.0'.*'MIT'",
        ):
            self.verify()

    def test_pr_scope_must_be_exactly_the_controller_two_files(self):
        self.evidence["files"].append({
            "filename": ".github/workflows/reviewed-png-attestation.yml",
            "status": "modified",
            "sha": "3" * 40,
        })
        self.evidence["pull_request"]["changed_files"] = 3
        self.evidence["pull_request_after"]["changed_files"] = 3
        self.event["pull_request"]["changed_files"] = 3
        with self.assertRaisesRegex(
            attestation.AttestationError, "exactly meta.json and piece.png"
        ):
            self.verify()

    def test_legitimate_png_plus_second_valid_png_slug_is_rejected(self):
        second_slug = "second-controller-piece"
        write_png_submission(
            self.submissions_dir,
            second_slug,
            payload=self.payload,
            width=512,
            height=512,
            meta_extras={
                "_dada_cycle": {
                    "cycle": 8,
                    "rounds": [{"winner": "c"}],
                },
            },
        )
        attestation.build_index.validate_submission(
            second_slug,
            "CC0-1.0",
            self.submissions_dir,
        )
        for name in ("meta.json", "piece.png"):
            path = os.path.join(self.submissions_dir, second_slug, name)
            self.evidence["files"].append({
                "filename": f"submissions/{second_slug}/{name}",
                "status": "added",
                "sha": git_blob_sha(path),
            })
        self.update_both_prs(lambda pr: pr.update(changed_files=4))

        with self.assertRaises(attestation.AttestationError) as raised:
            self.verify()
        self.assertEqual(
            "a reviewed PNG PR must affect exactly one PNG slug",
            str(raised.exception),
        )

    def test_controller_commit_identity_is_exact(self):
        for commit in (
            self.evidence["commits"][0],
            self.evidence["head_commit"],
        ):
            commit["commit"]["author"]["name"] = "Contributor"
        with self.assertRaisesRegex(
            attestation.AttestationError, "Dada Collective"
        ):
            self.verify()

    def test_failed_signature_status_is_rejected(self):
        for commit in (
            self.evidence["commits"][0],
            self.evidence["head_commit"],
        ):
            commit["commit"]["verification"] = {
                "verified": False,
                "reason": "bad_email",
            }
        with self.assertRaisesRegex(
            attestation.AttestationError, "signature status"
        ):
            self.verify()

    def test_verified_github_signature_status_is_accepted(self):
        for commit in (
            self.evidence["commits"][0],
            self.evidence["head_commit"],
        ):
            commit["commit"]["verification"] = {
                "verified": True,
                "reason": "valid",
            }
        self.assertEqual(self.slug, self.verify())

    def test_stale_event_head_is_rejected_against_current_api(self):
        self.evidence["pull_request"]["head"]["sha"] = "4" * 40
        self.evidence["pull_request_after"]["head"]["sha"] = "4" * 40
        with self.assertRaisesRegex(
            attestation.AttestationError, "stale PR evidence.*head SHA"
        ):
            self.verify()

    def test_api_reread_detects_update_during_evidence_collection(self):
        self.evidence["pull_request_after"]["head"]["sha"] = "8" * 40
        with self.assertRaisesRegex(
            attestation.AttestationError, "current PR snapshot"
        ):
            self.verify()

    def test_stale_controller_parent_is_rejected(self):
        for commit in (
            self.evidence["commits"][0],
            self.evidence["head_commit"],
        ):
            commit["parents"][0]["sha"] = "5" * 40
        with self.assertRaisesRegex(
            attestation.AttestationError, "current base SHA"
        ):
            self.verify()

    def test_api_file_digest_must_match_checked_out_head(self):
        self.evidence["files"][0]["sha"] = "6" * 40
        with self.assertRaisesRegex(
            attestation.AttestationError, "API blob SHA"
        ):
            self.verify()

    def test_multiple_commits_are_rejected(self):
        self.evidence["commits"].append(
            copy.deepcopy(self.evidence["commits"][0])
        )
        self.evidence["pull_request"]["commits"] = 2
        self.evidence["pull_request_after"]["commits"] = 2
        self.event["pull_request"]["commits"] = 2
        with self.assertRaisesRegex(
            attestation.AttestationError, "exactly one commit"
        ):
            self.verify()

    def test_non_png_fork_submission_skips_png_provenance(self):
        shutil.rmtree(os.path.join(self.submissions_dir, self.slug))
        slug = "outside-svg"
        write_submission(
            self.submissions_dir,
            slug,
            meta_overrides={"contributor": "outside-user"},
        )
        self.event, self.evidence = self.make_evidence(
            slug,
            "piece.svg",
            author="outside-user",
            head_repo="outside-user/public-art-collective",
            fork=True,
            branch="art/outside-svg",
        )
        self.assertIsNone(self.verify())

    def test_non_png_300_commit_pr_does_not_need_commit_evidence(self):
        shutil.rmtree(os.path.join(self.submissions_dir, self.slug))
        slug = "long-running-svg"
        write_submission(self.submissions_dir, slug)
        self.event, self.evidence = self.make_evidence(
            slug,
            "piece.svg",
            branch="feature/long-running-svg",
        )
        self.update_both_prs(lambda pr: pr.update(commits=300))
        self.evidence["commits"] = None
        self.evidence["head_commit"] = None
        self.assertIsNone(self.verify())

    def test_oversized_changed_file_count_has_bounded_error(self):
        self.update_both_prs(
            lambda pr: pr.update(
                changed_files=attestation.MAX_CHANGED_FILES + 1
            )
        )
        self.evidence["files"] = []
        with self.assertRaisesRegex(
            attestation.AttestationError,
            r"reports 3001 changed files.*at most 3000",
        ):
            self.verify()

    def test_live_evidence_reads_head_commit_from_head_repository(self):
        event = copy.deepcopy(self.event)
        event["pull_request"]["head"]["repo"] = repository(
            "outside-user/public-art-collective", fork=True
        )
        current_pr = copy.deepcopy(self.evidence["pull_request"])
        current_pr["head"]["repo"] = repository(
            "outside-user/public-art-collective", fork=True
        )
        client = mock.Mock()
        client.get.side_effect = [
            copy.deepcopy(current_pr),
            copy.deepcopy(current_pr),
            copy.deepcopy(self.evidence["head_commit"]),
            copy.deepcopy(current_pr),
        ]
        client.pages.side_effect = [
            copy.deepcopy(self.evidence["files"]),
            copy.deepcopy(self.evidence["commits"]),
        ]
        with mock.patch.object(attestation, "GitHubApi", return_value=client):
            result = attestation.fetch_api_evidence(
                event,
                self.tmp,
                self.base_root,
                token="injected-test-token",
            )
        self.assertIn("pull_request_after", result)
        self.assertTrue(
            client.pages.call_args_list[0].args[0].endswith("/files")
        )
        self.assertTrue(
            client.pages.call_args_list[1].args[0].endswith("/commits")
        )
        self.assertEqual(
            (
                "/repos/outside-user/public-art-collective/commits/"
                + HEAD_SHA
            ),
            client.get.call_args_list[2].args[0],
        )

    def test_live_non_png_evidence_skips_commit_endpoints(self):
        shutil.rmtree(os.path.join(self.submissions_dir, self.slug))
        slug = "long-running-svg"
        write_submission(self.submissions_dir, slug)
        event, evidence = self.make_evidence(
            slug,
            "piece.svg",
            branch="feature/long-running-svg",
        )
        for pr in (
            event["pull_request"],
            evidence["pull_request"],
            evidence["pull_request_after"],
        ):
            pr["commits"] = 300
        client = mock.Mock()
        client.get.side_effect = [
            copy.deepcopy(evidence["pull_request"]),
            copy.deepcopy(evidence["pull_request_after"]),
        ]
        client.pages.return_value = copy.deepcopy(evidence["files"])
        with mock.patch.object(attestation, "GitHubApi", return_value=client):
            result = attestation.fetch_api_evidence(
                event,
                self.tmp,
                self.base_root,
                token="injected-test-token",
            )
        self.assertIsNone(result["commits"])
        self.assertIsNone(result["head_commit"])
        self.assertEqual(1, client.pages.call_count)
        self.assertTrue(client.pages.call_args.args[0].endswith("/files"))
        self.assertEqual(2, client.get.call_count)

    def test_live_oversized_pr_rejects_before_file_paging(self):
        event = copy.deepcopy(self.event)
        current_pr = copy.deepcopy(self.evidence["pull_request"])
        current_pr["changed_files"] = attestation.MAX_CHANGED_FILES + 1
        client = mock.Mock()
        client.get.return_value = current_pr
        with mock.patch.object(attestation, "GitHubApi", return_value=client):
            with self.assertRaisesRegex(
                attestation.AttestationError,
                r"reports 3001 changed files.*at most 3000",
            ):
                attestation.fetch_api_evidence(
                    event,
                    self.tmp,
                    self.base_root,
                    token="injected-test-token",
                )
        client.pages.assert_not_called()
        self.assertEqual(1, client.get.call_count)

    def test_documented_file_page_ceiling_accepts_exactly_3000(self):
        client = attestation.GitHubApi(
            "https://api.github.invalid", "injected-test-token"
        )
        with mock.patch.object(
            client,
            "get",
            side_effect=[[{"filename": "x"}] * 100] * 30,
        ) as get:
            records = client.pages(
                "/repos/kody-w/public-art-collective/pulls/42/files",
                attestation.MAX_CHANGED_FILES,
                attestation.MAX_CHANGED_FILES,
                "changed-file",
            )
        self.assertEqual(attestation.MAX_CHANGED_FILES, len(records))
        self.assertEqual(30, get.call_count)

    def write_cli_inputs(self):
        event_path = os.path.join(self.tmp, "event.json")
        api_path = os.path.join(self.tmp, "api.json")
        with open(event_path, "w", encoding="utf-8") as handle:
            json.dump(self.event, handle)
        with open(api_path, "w", encoding="utf-8") as handle:
            json.dump(self.evidence, handle)
        return event_path, api_path

    def run_cli(self):
        event_path, api_path = self.write_cli_inputs()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(
            attestation.urllib.request,
            "urlopen",
            side_effect=AssertionError("offline fixture attempted network"),
        ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = attestation.main([
                "--event-path", event_path,
                "--api-fixture", api_path,
                "--candidate-root", self.tmp,
                "--base-root", self.base_root,
                "--trusted-base-sha", self.trusted_base_sha,
            ])
        return rc, stdout.getvalue(), stderr.getvalue()

    def test_cli_uses_injected_event_and_api_without_network(self):
        rc, stdout, stderr = self.run_cli()
        self.assertEqual(0, rc, stderr)
        self.assertIn("provenance attested", stdout)

    def test_cli_reports_owner_takedown(self):
        self.configure_takedown()
        rc, stdout, stderr = self.run_cli()
        self.assertEqual(0, rc, stderr)
        self.assertIn("takedown authorized", stdout)

    def test_cli_non_png_reports_provenance_not_applicable(self):
        shutil.rmtree(os.path.join(self.submissions_dir, self.slug))
        slug = "outside-svg"
        write_submission(self.submissions_dir, slug)
        self.event, self.evidence = self.make_evidence(
            slug,
            "piece.svg",
            branch="feature/outside-svg",
        )
        rc, stdout, stderr = self.run_cli()
        self.assertEqual(0, rc, stderr)
        self.assertEqual(
            "candidate workflow policy valid; no reviewed PNG change; "
            "PNG provenance check not applicable\n",
            stdout,
        )
        self.assertNotIn("structural validation", stdout)

    def test_cli_rejects_stale_pr_snapshot(self):
        self.evidence["pull_request"]["head"]["sha"] = "7" * 40
        self.evidence["pull_request_after"]["head"]["sha"] = "7" * 40
        rc, stdout, stderr = self.run_cli()
        self.assertEqual(1, rc)
        self.assertEqual("", stdout)
        self.assertIn("stale PR evidence", stderr)


class TestAttestationWorkflowSource(unittest.TestCase):
    def setUp(self):
        self.path = (
            ROOT / ".github" / "workflows" / "reviewed-png-attestation.yml"
        )
        self.workflow = self.path.read_text(encoding="utf-8")

    def test_all_prs_trigger_protected_base_workflow(self):
        self.assertRegex(
            self.workflow, r"(?m)^  pull_request_target:$"
        )
        self.assertNotRegex(self.workflow, r"(?m)^  pull_request:$")
        self.assertNotRegex(self.workflow, r"(?m)^    paths(?:-ignore)?:")
        self.assertIn("Intentionally no paths filter", self.workflow)
        self.assertIn(
            "python3 trusted/tools/verify_png_attestation.py",
            self.workflow,
        )

    def test_trusted_checkout_uses_current_main_tip_not_pr_base_sha(self):
        checkout = (
            "actions/checkout@"
            "11bd71901bbe5b1630ceea73d27597364c9af683"
        )
        self.assertEqual(2, self.workflow.count(checkout))
        self.assertIn(
            "Checkout trusted validator from protected main tip",
            self.workflow,
        )
        self.assertIn(
            "ref: main",
            self.workflow,
        )
        self.assertNotIn("github.event.pull_request.base.sha", self.workflow)
        self.assertNotIn("github.event.pull_request.base.ref", self.workflow)
        self.assertIn("path: trusted", self.workflow)
        self.assertIn(
            '--trusted-base-sha "$(git -C trusted rev-parse HEAD)"',
            self.workflow,
        )

    def test_candidate_checkout_remains_data_only(self):
        self.assertIn(
            "Checkout untrusted candidate data",
            self.workflow,
        )
        self.assertIn(
            "ref: ${{ github.event.pull_request.head.sha }}",
            self.workflow,
        )
        self.assertIn("path: candidate", self.workflow)
        self.assertIn(
            "sparse-checkout: |\n"
            "            submissions\n"
            "            .github/workflows\n",
            self.workflow,
        )
        self.assertNotIn("python3 candidate/", self.workflow)
        self.assertNotIn("git -C candidate", self.workflow)
        self.assertEqual(2, self.workflow.count("persist-credentials: false"))

    def test_workflow_is_read_only_and_executes_no_candidate_code(self):
        self.assertIn("contents: read", self.workflow)
        self.assertIn("pull-requests: read", self.workflow)
        self.assertNotIn("contents: write", self.workflow)
        self.assertNotIn("id-token: write", self.workflow)
        self.assertIn(
            "sparse-checkout: |\n"
            "            submissions\n"
            "            .github/workflows\n",
            self.workflow,
        )
        self.assertNotRegex(
            self.workflow,
            re.compile(r"run:.*(?:candidate/tools|candidate/\\.github)"),
        )

    def test_ordinary_ci_exercises_attestation_source_changes(self):
        validation_workflow = (
            ROOT / ".github" / "workflows" / "submissions-index.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '- ".github/workflows/**"',
            validation_workflow,
        )
        self.assertIn('-p "test_*.py"', validation_workflow)


if __name__ == "__main__":
    unittest.main()
