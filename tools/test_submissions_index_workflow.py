#!/usr/bin/env python3
"""Contract and mocked execution tests for the protected index workflow."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "submissions-index.yml"
STEP_NAME = "Regenerate, attest, and update protected main"
CHECKOUT_SHA = "11bd71901bbe5b1630ceea73d27597364c9af683"
REQUIRED_CONTEXT = "Verify controller provenance"
COMPOSITE_CONTEXT = (
    "Reviewed PNG provenance / Verify controller provenance"
)


def extract_run_script(workflow, step_name=STEP_NAME):
    marker = f"      - name: {step_name}\n"
    step_start = workflow.index(marker)
    run_marker = "        run: |\n"
    run_start = workflow.index(run_marker, step_start) + len(run_marker)
    lines = []
    for line in workflow[run_start:].splitlines():
        if line and not line.startswith("          "):
            break
        lines.append(line[10:] if line else "")
    script = "\n".join(lines) + "\n"
    if not script.strip():
        raise AssertionError("workflow run script was empty")
    return script


def workflow_paths():
    return sorted(
        path
        for path in WORKFLOW_DIR.rglob("*")
        if path.suffix in {".yml", ".yaml"}
    )


def workflow_job_blocks(workflow):
    lines = workflow.splitlines()
    try:
        jobs_start = lines.index("jobs:")
    except ValueError as error:
        raise AssertionError("workflow had no jobs mapping") from error

    blocks = {}
    current_name = None
    current_lines = []
    for line in lines[jobs_start + 1:]:
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if match:
            if current_name is not None:
                blocks[current_name] = "\n".join(current_lines)
            current_name = match.group(1)
            current_lines = [line]
        elif current_name is not None:
            current_lines.append(line)
    if current_name is not None:
        blocks[current_name] = "\n".join(current_lines)
    return blocks


def workflow_job_display_name(block):
    matches = re.findall(r"(?m)^    name:\s*(.+?)\s*$", block)
    if len(matches) > 1:
        raise AssertionError("workflow job had duplicate display names")
    if not matches:
        return None
    value = re.sub(r"\s+#.*$", "", matches[0]).strip()
    if value.startswith('"'):
        return json.loads(value)
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


MOCK_GIT = r"""
import json
import os
from pathlib import Path
import sys

state_path = Path(os.environ["MOCK_STATE"])
log_path = Path(os.environ["MOCK_LOG"])
args = sys.argv[1:]


def load():
    return json.loads(state_path.read_text(encoding="utf-8"))


def save(state):
    state_path.write_text(json.dumps(state), encoding="utf-8")


def log(message):
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(message + "\n")


def sha(character):
    return character * 40


state = load()
modes = {
    mode
    for mode in os.environ["MOCK_MODE"].split(",")
    if mode
}


def enabled(mode):
    return mode in modes


log("git:" + " ".join(args))
command = args[0]

if command == "fetch":
    if enabled("post-temp-fetch-fail") and state["temp_pushes"] > 0:
        sys.exit(1)
    sys.exit(0)

if command == "checkout":
    state["attempt"] += 1
    state["branch"] = args[args.index("-B") + 1]
    state["head"] = args[-1]
    save(state)
    log(f"checkout:{state['attempt']}:{state['branch']}:{state['head']}")
    sys.exit(0)

if command == "rev-parse":
    revision = args[-1]
    if revision == "refs/remotes/origin/main^{commit}":
        print(state["main"])
    elif revision == "HEAD^{commit}":
        print(state["head"])
    else:
        raise SystemExit(f"unexpected rev-parse: {revision}")
    sys.exit(0)

if command == "diff":
    if "--name-only" in args:
        print("submissions/index.json")
        if (
            enabled("diff-proof-fail")
            and "--cached" not in args
        ):
            print("README.md")
        sys.exit(0)
    if "--quiet" in args and args[-1] == "submissions/index.json":
        sys.exit(1)
    sys.exit(0)

if command == "ls-files":
    if "--others" in args:
        sys.exit(0)
    if "-s" in args:
        mode = (
            "120000"
            if enabled("mode-proof-fail")
            else "100644"
        )
        print(f"{mode} {sha('d')} 0\tsubmissions/index.json")
        sys.exit(0)
    raise SystemExit(f"unexpected ls-files: {args}")

if command == "add":
    sys.exit(0)

if command == "commit":
    commit_characters = "abcdef0123456789"
    commit = sha(commit_characters[state["attempt"] - 1])
    state["head"] = commit
    state["parents"][commit] = state["main"]
    state["trees"][commit] = sha(commit_characters[state["attempt"]])
    save(state)
    log(f"commit:{commit}:{state['parents'][commit]}")
    sys.exit(0)

if command == "rev-list":
    commit = args[-1]
    print(f"{commit} {state['parents'][commit]}")
    sys.exit(0)

if command == "diff-tree":
    print("submissions/index.json")
    sys.exit(0)

if command == "ls-tree":
    log(f"commit-proof:{args[1]}")
    print(f"100644 blob {sha('d')}\tsubmissions/index.json")
    sys.exit(0)

if command == "show":
    print(state["trees"][args[-1]])
    sys.exit(0)

if command == "push":
    if "--delete" in args:
        branch = args[-1]
        log(f"branch-delete-attempt:{branch}")
        if enabled("cleanup-fail"):
            sys.exit(1)
        log(f"branch-delete:{branch}")
        sys.exit(0)

    refspec = args[-1]
    source, destination = refspec.split(":", 1)
    if destination.startswith("refs/heads/bot/regenerate-index-"):
        log(f"temp-push:{source}:{destination.removeprefix('refs/heads/')}")
        state["temp_pushes"] += 1
        save(state)
        if enabled("temp-push-fail"):
            sys.exit(1)
        sys.exit(0)
    if destination == "refs/heads/main":
        state["main_pushes"] += 1
        push_number = state["main_pushes"]
        log(f"main-push:{source}")
        if enabled("race-once") and push_number == 1:
            state["main"] = sha("2")
            save(state)
            sys.exit(1)
        if enabled("always-race"):
            next_characters = "23456789"
            state["main"] = sha(next_characters[push_number - 1])
            save(state)
            sys.exit(1)
        if enabled("main-reject"):
            save(state)
            sys.exit(1)
        state["main"] = source
        save(state)
        sys.exit(0)
    raise SystemExit(f"unexpected push refspec: {refspec}")

raise SystemExit(f"unexpected git command: {args}")
"""


MOCK_GH = r"""
import json
import os
from pathlib import Path
import sys

state_path = Path(os.environ["MOCK_STATE"])
log_path = Path(os.environ["MOCK_LOG"])
args = sys.argv[1:]


def load():
    return json.loads(state_path.read_text(encoding="utf-8"))


def save(state):
    state_path.write_text(json.dumps(state), encoding="utf-8")


def log(message):
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(message + "\n")


def raw_field(name):
    prefix = name + "="
    for index, argument in enumerate(args):
        if argument == "--raw-field" and args[index + 1].startswith(prefix):
            return args[index + 1][len(prefix):]
    raise SystemExit(f"missing raw field: {name}")


state = load()
modes = {
    mode
    for mode in os.environ["MOCK_MODE"].split(",")
    if mode
}


def enabled(mode):
    return mode in modes

if args[0:2] == ["api", "--method"]:
    method = args[2]
    if method == "POST":
        head = raw_field("head_sha")
        name = raw_field("name")
        external_id = raw_field("external_id")
        log(f"check-create:{head}:{name}:{external_id}")
        if enabled("create-fail"):
            sys.exit(1)
        state["check_count"] += 1
        check_id = str(100 + state["check_count"])
        state["checks"][check_id] = {
            "head": head,
            "name": name,
            "external_id": external_id,
        }
        save(state)
        print(
            "\t".join([
                check_id,
                name,
                head,
                "completed",
                "success",
                "github-actions",
                "15368",
                external_id,
            ])
        )
        sys.exit(0)
    if method == "GET":
        endpoint = next(
            argument for argument in args
            if "/check-runs/" in argument
        )
        check_id = endpoint.rsplit("/", 1)[-1]
        record = state["checks"][check_id]
        log(f"check-read:{record['head']}:{check_id}")
        if enabled("read-fail"):
            sys.exit(1)
        app_id = "99999" if enabled("wrong-app") else "15368"
        name = (
            "Untrusted lookalike"
            if enabled("wrong-name")
            else record["name"]
        )
        head = "f" * 40 if enabled("wrong-sha") else record["head"]
        conclusion = (
            "failure"
            if enabled("wrong-conclusion")
            else "success"
        )
        print(
            "\t".join([
                check_id,
                name,
                head,
                "completed",
                conclusion,
                "github-actions",
                app_id,
                record["external_id"],
            ])
        )
        sys.exit(0)

raise SystemExit(f"unexpected gh command: {args}")
"""


MOCK_PYTHON = r"""
import os
from pathlib import Path
import sys

with Path(os.environ["MOCK_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write("python:" + " ".join(sys.argv[1:]) + "\n")

if (
    "validation-fail" in os.environ["MOCK_MODE"].split(",")
    and sys.argv[1:] == ["tools/build_index.py", "--check"]
):
    sys.exit(1)
"""


MOCK_SLEEP = r"""
import os
from pathlib import Path
import signal
import sys

with Path(os.environ["MOCK_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write("sleep:" + " ".join(sys.argv[1:]) + "\n")

modes = set(os.environ["MOCK_MODE"].split(","))
if "signal-int" in modes:
    os.kill(os.getppid(), signal.SIGINT)
elif "signal-term" in modes:
    os.kill(os.getppid(), signal.SIGTERM)
"""


class SubmissionsIndexWorkflowSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.script = extract_run_script(cls.workflow)

    def test_job_has_only_needed_write_permissions(self):
        job = self.workflow.split("  regenerate-index:\n", 1)[1]
        permissions = job.split("    permissions:\n", 1)[1].split(
            "    # Serialize writer runs", 1
        )[0]
        self.assertEqual(
            {
                "checks: write",
                "contents: write",
            },
            {
                line.strip()
                for line in permissions.splitlines()
                if line.strip()
            },
        )
        self.assertNotIn("id-token: write", job)
        self.assertNotIn("administration: write", job)
        self.assertNotIn("pull-requests: write", job)

    def test_only_trusted_writer_can_write_checks_and_is_sha_pinned(self):
        requesters = []
        checks_write = re.compile(
            r"^\s*checks:\s*['\"]?write['\"]?\s*(?:#.*)?$",
            re.MULTILINE,
        )
        job_write = re.compile(
            r"^      [A-Za-z0-9_-]+:\s*['\"]?write['\"]?"
            r"\s*(?:#.*)?$",
            re.MULTILINE,
        )
        for path in workflow_paths():
            workflow = path.read_text(encoding="utf-8")
            self.assertNotRegex(
                workflow,
                r"(?m)^\s*permissions:\s*['\"]?write-all['\"]?\s*$",
                f"{path} grants implicit checks: write",
            )
            self.assertNotRegex(
                workflow,
                r"(?m)^\s*permissions:\s*\{",
                f"{path} uses an unscannable inline permissions mapping",
            )
            blocks = workflow_job_blocks(workflow)
            block_occurrences = 0
            top_level = workflow.split("\njobs:\n", 1)[0]
            top_permissions = re.search(
                r"(?ms)^permissions:\s*\n(?P<body>(?:^  .*(?:\n|$))*)",
                top_level,
            )
            top_level_write = bool(
                top_permissions
                and re.search(
                    r"(?m)^  [A-Za-z0-9_-]+:\s*['\"]?write['\"]?"
                    r"\s*(?:#.*)?$",
                    top_permissions.group("body"),
                )
            )
            for job_name, block in blocks.items():
                occurrences = len(checks_write.findall(block))
                block_occurrences += occurrences
                requesters.extend(
                    [(str(path.relative_to(ROOT)), job_name)] * occurrences
                )
                if top_level_write or job_write.search(block):
                    checkout_refs = re.findall(
                        r"actions/checkout@([^\s#]+)",
                        block,
                    )
                    for checkout_ref in checkout_refs:
                        self.assertRegex(
                            checkout_ref,
                            r"^[0-9a-f]{40}$",
                            f"{path}:{job_name} has an unpinned checkout",
                        )
            self.assertEqual(
                len(checks_write.findall(workflow)),
                block_occurrences,
                f"{path} requests checks: write outside a job",
            )

        self.assertEqual(
            [
                (
                    ".github/workflows/submissions-index.yml",
                    "regenerate-index",
                ),
            ],
            requesters,
        )

        checkout_refs = re.findall(
            r"actions/checkout@([^\s#]+)",
            self.workflow,
        )
        self.assertEqual([CHECKOUT_SHA, CHECKOUT_SHA], checkout_refs)

    def test_only_protected_gate_declares_required_job_display_name(self):
        producers = []
        for path in workflow_paths():
            workflow = path.read_text(encoding="utf-8")
            for job_id, block in workflow_job_blocks(workflow).items():
                if workflow_job_display_name(block) == REQUIRED_CONTEXT:
                    producers.append((
                        str(path.relative_to(ROOT)),
                        job_id,
                    ))
        self.assertEqual(
            [
                (
                    ".github/workflows/reviewed-png-attestation.yml",
                    "verify-controller-provenance",
                ),
            ],
            producers,
        )

    def test_pull_request_paths_cover_all_workflows(self):
        pull_request_block = self.workflow.split("  pull_request:\n", 1)[1].split(
            "\n  push:\n",
            1,
        )[0]
        path_entries = re.findall(
            r'^\s*-\s*"([^"]+)"\s*$',
            pull_request_block,
            re.MULTILINE,
        )
        workflow_entries = [
            entry for entry in path_entries
            if entry.startswith(".github/workflows/")
        ]
        self.assertEqual([".github/workflows/**"], workflow_entries)

    def test_only_pull_request_validation_runs_are_cancelled(self):
        workflow_concurrency = self.workflow.split("\njobs:\n", 1)[0].split(
            "\nconcurrency:\n",
            1,
        )[1]
        self.assertIn(
            "cancel-in-progress: "
            "${{ github.event_name == 'pull_request' }}",
            workflow_concurrency,
        )
        self.assertNotIn("cancel-in-progress: true", workflow_concurrency)

        writer = workflow_job_blocks(self.workflow)["regenerate-index"]
        self.assertIn("cancel-in-progress: false", writer)

    def test_exact_required_context_and_actions_app_are_pinned(self):
        self.assertIn(
            f'readonly CHECK_NAME="{REQUIRED_CONTEXT}"',
            self.script,
        )
        self.assertIn('readonly CHECK_APP_SLUG="github-actions"', self.script)
        self.assertIn('readonly CHECK_APP_ID="15368"', self.script)
        self.assertIn('readonly MAX_AUDIT_CHARS=2000', self.script)
        self.assertIn(
            "readonly MAX_SAME_SHA_PUSH_ATTEMPTS=4",
            self.script,
        )
        self.assertIn(
            "readonly PROPAGATION_DELAY_BASE_SECONDS=3",
            self.script,
        )
        self.assertIn(
            "readonly MAX_PROPAGATION_WAIT_SECONDS=18",
            self.script,
        )
        self.assertIn(
            "audit summary exceeded its fixed size bound",
            self.script,
        )
        self.assertIn("checks: write", self.workflow)

    def test_exit_and_signal_traps_preserve_primary_status(self):
        self.assertIn("local primary_status=\"$?\"", self.script)
        self.assertIn("trap - EXIT INT TERM", self.script)
        self.assertIn("trap cleanup_on_exit EXIT", self.script)
        self.assertIn("trap 'handle_signal INT 130' INT", self.script)
        self.assertIn("trap 'handle_signal TERM 143' TERM", self.script)
        self.assertIn(
            "the original signal/exit status is preserved",
            self.script,
        )

    def test_documentation_uses_bare_context_and_states_residual_risk(self):
        composite_occurrences = []
        markdown_paths = [
            ROOT / "README.md",
            *sorted((ROOT / "specs").glob("*.md")),
        ]
        self.assertTrue(all(
            path == ROOT / "README.md"
            or path.parent == ROOT / "specs"
            for path in markdown_paths
        ))
        for path in markdown_paths:
            document = path.read_text(encoding="utf-8")
            if COMPOSITE_CONTEXT in document:
                composite_occurrences.append(str(path.relative_to(ROOT)))
        self.assertEqual([], composite_occurrences)

        documents = "\n".join(
            (ROOT / relative).read_text(encoding="utf-8")
            for relative in ("README.md", "specs/SUBMISSION_PROTOCOL.md")
        )
        compact = " ".join(documents.split())
        self.assertIn(
            "required status check **Verify controller provenance** "
            "from GitHub Actions app id `15368`",
            compact,
        )
        self.assertIn(
            "enforces the context plus integration id, not workflow identity",
            compact,
        )
        self.assertIn(
            "default `GITHUB_TOKEN` workflow permissions must therefore "
            "remain read-only",
            compact,
        )
        self.assertIn(
            "Any new or changed workflow requesting `checks: write`",
            compact,
        )
        self.assertIn(
            "local PR-head tests are defense in depth, not an "
            "enforcement boundary",
            compact,
        )
        self.assertIn(
            "MUST NOT add a require-PR rule",
            compact,
        )

    def test_transaction_source_contains_all_ordered_security_gates(self):
        ordered = [
            "python3 tools/build_index.py --check",
            'git push origin "${commit_sha}:refs/heads/${branch}"',
            "gh api --method POST",
            "gh api --method GET",
            'git push origin "${commit_sha}:refs/heads/main"',
        ]
        positions = [self.script.index(fragment) for fragment in ordered]
        self.assertEqual(sorted(positions), positions)
        self.assertIn(
            '[[ "$parent_record" == "$commit_sha $base_sha" ]]',
            self.script,
        )
        self.assertIn("does not have regular-file Git mode 100644", self.script)
        self.assertIn("does not have exactly the fetched main tip", self.script)

    def test_only_github_token_is_used_without_candidate_code_or_bypass(self):
        self.assertIn("GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}", self.workflow)
        self.assertNotIn("PERSONAL_ACCESS_TOKEN", self.workflow)
        self.assertNotIn("github_pat_", self.workflow)
        self.assertNotIn("candidate/", self.script)
        self.assertNotIn("force-with-lease", self.script)
        self.assertNotRegex(self.script, r"git push [^\n]* (?:-f|--force)")
        self.assertNotIn("gh pr", self.script)

    def test_no_fallback_pr_or_retained_branch_path_exists(self):
        self.assertNotIn("pull-requests: write", self.workflow)
        self.assertNotIn("gh pr create", self.script)
        self.assertNotIn("--head", self.script)
        self.assertIn("no fallback PR was opened", self.script)
        self.assertIn(
            "a newer main push will enqueue a fresh writer run",
            self.script,
        )

    def test_embedded_shell_has_valid_bash_syntax(self):
        result = subprocess.run(
            [shutil.which("bash"), "-n"],
            input=self.script,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)


class SubmissionsIndexWorkflowExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = extract_run_script(
            WORKFLOW_PATH.read_text(encoding="utf-8")
        )

    def run_workflow(self, mode):
        with tempfile.TemporaryDirectory(
            prefix="protected-index-workflow-"
        ) as temporary:
            root = Path(temporary)
            mock_bin = root / "bin"
            mock_bin.mkdir()
            (root / "submissions").mkdir()
            (root / "submissions" / "index.json").write_text(
                "{}\n", encoding="utf-8"
            )
            state_path = root / "state.json"
            log_path = root / "events.log"
            state_path.write_text(
                json.dumps({
                    "attempt": 0,
                    "branch": "",
                    "head": "1" * 40,
                    "main": "1" * 40,
                    "main_pushes": 0,
                    "temp_pushes": 0,
                    "check_count": 0,
                    "checks": {},
                    "parents": {},
                    "trees": {},
                }),
                encoding="utf-8",
            )
            log_path.write_text("", encoding="utf-8")

            interpreter = sys.executable
            for name, source in (
                ("git", MOCK_GIT),
                ("gh", MOCK_GH),
                ("python3", MOCK_PYTHON),
                ("sleep", MOCK_SLEEP),
            ):
                path = mock_bin / name
                path.write_text(
                    f"#!{interpreter}\n"
                    + textwrap.dedent(source).lstrip(),
                    encoding="utf-8",
                )
                path.chmod(0o755)

            env = os.environ.copy()
            env.update({
                "PATH": str(mock_bin) + os.pathsep + env["PATH"],
                "MOCK_STATE": str(state_path),
                "MOCK_LOG": str(log_path),
                "MOCK_MODE": mode,
                "GITHUB_RUN_ID": "4242",
                "GITHUB_RUN_ATTEMPT": "3",
                "GITHUB_REPOSITORY": "kody-w/public-art-collective",
                "GITHUB_SERVER_URL": "https://github.com",
                "GH_TOKEN": "not-a-real-token",
            })
            result = subprocess.run(
                [shutil.which("bash")],
                input=self.script,
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            events = log_path.read_text(encoding="utf-8").splitlines()
            return result, events

    def test_success_orders_validation_branch_check_readback_then_main(self):
        result, events = self.run_workflow("success")
        self.assertEqual(0, result.returncode, result.stderr)

        validation = events.index(
            "python:tools/build_index.py --check"
        )
        commit_proof = next(
            index for index, event in enumerate(events)
            if event.startswith("commit-proof:")
        )
        temp_push = next(
            index for index, event in enumerate(events)
            if event.startswith("temp-push:")
        )
        check_create = next(
            index for index, event in enumerate(events)
            if event.startswith("check-create:")
        )
        check_read = next(
            index for index, event in enumerate(events)
            if event.startswith("check-read:")
        )
        main_push = next(
            index for index, event in enumerate(events)
            if event.startswith("main-push:")
        )
        self.assertLess(validation, commit_proof)
        self.assertLess(commit_proof, temp_push)
        self.assertLess(temp_push, check_create)
        self.assertLess(check_create, check_read)
        self.assertLess(check_read, main_push)
        self.assertIn(
            ":Verify controller provenance:",
            events[check_create],
        )

    def test_validation_diff_and_temp_push_fail_before_main(self):
        expected_temp_push = {
            "validation-fail": False,
            "diff-proof-fail": False,
            "mode-proof-fail": False,
            "temp-push-fail": True,
        }
        for mode, has_temp_push in expected_temp_push.items():
            with self.subTest(mode=mode):
                result, events = self.run_workflow(mode)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(
                    has_temp_push,
                    any(event.startswith("temp-push:") for event in events),
                )
                self.assertFalse(any(
                    event.startswith("check-create:") for event in events
                ))
                self.assertFalse(any(
                    event.startswith("main-push:") for event in events
                ))
                if has_temp_push:
                    self.assertTrue(any(
                        event.startswith("branch-delete-attempt:")
                        for event in events
                    ))

    def test_every_post_push_failure_attempts_branch_deletion(self):
        for mode in (
            "create-fail",
            "read-fail",
            "wrong-app",
            "wrong-name",
            "wrong-sha",
            "wrong-conclusion",
            "post-temp-fetch-fail",
        ):
            with self.subTest(mode=mode):
                result, events = self.run_workflow(mode)
                self.assertNotEqual(0, result.returncode)
                self.assertTrue(any(
                    event.startswith("temp-push:") for event in events
                ))
                self.assertFalse(any(
                    event.startswith("main-push:") for event in events
                ))
                self.assertTrue(any(
                    event.startswith("branch-delete-attempt:")
                    for event in events
                ))

    def test_cleanup_failure_does_not_mask_primary_failure(self):
        result, events = self.run_workflow(
            "create-fail,cleanup-fail"
        )
        self.assertEqual(1, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn(
            "::error::Could not create the required Check Run.",
            output,
        )
        self.assertIn(
            "::warning::Could not delete temporary branch",
            output,
        )
        self.assertTrue(any(
            event.startswith("branch-delete-attempt:")
            for event in events
        ))
        self.assertFalse(any(
            event.startswith("main-push:") for event in events
        ))

    def test_no_race_rejection_retries_same_sha_four_times_then_fails(self):
        result, events = self.run_workflow("main-reject")
        self.assertNotEqual(0, result.returncode)
        main_pushes = [
            event.split(":", 1)[1]
            for event in events
            if event.startswith("main-push:")
        ]
        checks = [
            event for event in events if event.startswith("check-create:")
        ]
        self.assertEqual(4, len(main_pushes))
        self.assertEqual([main_pushes[0]] * 4, main_pushes)
        self.assertEqual(1, len(checks))
        self.assertEqual(["sleep:3", "sleep:6", "sleep:9"], [
            event for event in events if event.startswith("sleep:")
        ])
        self.assertTrue(any(
            event.startswith("branch-delete-attempt:")
            for event in events
        ))
        output = result.stdout + result.stderr
        self.assertIn(
            "on all 4 bounded push attempts while origin/main remained",
            output,
        )
        self.assertIn(
            "single successful Check Run was not recreated or reused",
            output,
        )
        self.assertIn(
            "bare 'Verify controller provenance' context "
            "from GitHub Actions integration id 15368",
            output,
        )
        self.assertNotIn("pr-create:", "\n".join(events))

    def test_int_and_term_cleanup_preserve_signal_status(self):
        cases = (
            ("main-reject,signal-int", "INT", 130, False),
            ("main-reject,signal-term", "TERM", 143, False),
            (
                "main-reject,signal-term,cleanup-fail",
                "TERM",
                143,
                True,
            ),
        )
        for mode, signal_name, expected_status, cleanup_fails in cases:
            with self.subTest(mode=mode):
                result, events = self.run_workflow(mode)
                self.assertEqual(expected_status, result.returncode)
                self.assertEqual(
                    1,
                    sum(
                        event.startswith("temp-push:")
                        for event in events
                    ),
                )
                self.assertTrue(any(
                    event.startswith("branch-delete-attempt:")
                    for event in events
                ))
                output = result.stdout + result.stderr
                self.assertIn(f"Received {signal_name}", output)
                if cleanup_fails:
                    self.assertIn(
                        "original signal/exit status is preserved",
                        output,
                    )

    def test_race_builds_and_checks_a_fresh_commit(self):
        result, events = self.run_workflow("race-once")
        self.assertEqual(0, result.returncode, result.stderr)
        temp_pushes = [
            event.split(":")[1] for event in events
            if event.startswith("temp-push:")
        ]
        check_heads = [
            event.split(":")[1] for event in events
            if event.startswith("check-create:")
        ]
        main_pushes = [
            event.split(":")[1] for event in events
            if event.startswith("main-push:")
        ]
        self.assertEqual(2, len(temp_pushes))
        self.assertEqual(2, len(check_heads))
        self.assertEqual(2, len(main_pushes))
        self.assertNotEqual(temp_pushes[0], temp_pushes[1])
        self.assertEqual(temp_pushes, check_heads)
        self.assertEqual(temp_pushes, main_pushes)
        self.assertTrue(any(
            event == "branch-delete:bot/regenerate-index-4242-3-1"
            for event in events
        ))
        self.assertFalse(any(
            event.startswith("sleep:") for event in events
        ))

    def test_retry_cleanup_failure_is_warning_only_for_unique_branches(self):
        result, events = self.run_workflow(
            "race-once,cleanup-fail"
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            2,
            sum(event.startswith("temp-push:") for event in events),
        )
        self.assertEqual(
            2,
            sum(event.startswith("check-create:") for event in events),
        )
        self.assertGreaterEqual(
            sum(
                event.startswith("branch-delete-attempt:")
                for event in events
            ),
            2,
        )
        self.assertIn(
            "retry cleanup is warning-only because branch names are unique",
            result.stdout,
        )

    def test_exhausted_races_fail_and_clean_every_branch_without_pr(self):
        result, events = self.run_workflow("always-race")
        self.assertNotEqual(0, result.returncode)
        checks = [
            event for event in events if event.startswith("check-create:")
        ]
        self.assertEqual(5, len(checks))
        self.assertEqual(
            5,
            sum(event.startswith("branch-delete:") for event in events),
        )
        self.assertEqual(
            5,
            sum(event.startswith("main-push:") for event in events),
        )
        self.assertFalse(any(
            event.startswith("sleep:") for event in events
        ))
        self.assertNotIn("pr-create:", "\n".join(events))
        self.assertIn(
            "Main raced all 5 bounded protected update attempts",
            result.stdout + result.stderr,
        )
        self.assertIn(
            "a newer main push will enqueue a fresh writer run",
            result.stdout + result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
