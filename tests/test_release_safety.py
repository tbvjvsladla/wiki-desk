"""FR-01/02/03 regressions at the actual CLI/runtime/filesystem boundary.

Only synthetic scratch projects and locally manifest-bound package copies are
used. These tests do not certify live host discovery or semantic approval.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).absolute().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fs_safety as fs
import package_manifest as manifest
import wiki_desk as desk
import wiki_runtime as runtime
from tests.test_lifecycle import SKILL, tree

PARENT = Path(os.environ.get("WIKI_DESK_TEST_TMPDIR", tempfile.gettempdir()))
STAMP = "2026-10-04T00:00:00Z"


class ReleaseFixtureCase(unittest.TestCase):
    def setUp(self):
        PARENT.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="actual-", dir=PARENT)
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.root = self.home / "project"
        self.root.mkdir()
        self.package = self.home / "package"
        shutil.copytree(SCRIPTS.parent, self.package,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
        # Source manifest can be stale during parallel implementation. Bind
        # actual copied bytes locally, never regenerate the source release here.
        manifest.generate(self.package)
        self.put("docs/a.md", b"# Allowed source\n\nOriginal body stays here.\n")
        self.put("docs/data.txt", b"Allowed non-Markdown source\n")
        self.config = {"schema_version": 1, "project_name": "Safety fixture",
                       "wiki_dir": "__llm-wiki", "source_roots": ["docs"],
                       "excluded_roots": ["docs/private"], "authority_rules": [],
                       "fallback": {"document_type": "Reference", "authority_rank": 0,
                                    "role": "reference"}, "copy_policy": "path_reference"}
        self.contract = self.home / "contract.json"
        self.save_contract()
        self.entry = self.package / "scripts/wiki_desk.py"

    def put(self, rel, data):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def save_contract(self):
        self.contract.write_bytes(desk.json_bytes(self.config))

    def cli(self, action, *args):
        result = subprocess.run([sys.executable, "-B", str(self.entry), action,
                                 "--root", str(self.root), *map(str, args)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.stderr, "")
        return result.returncode, json.loads(result.stdout)

    def install(self):
        code, result = self.cli("install", "--host", "hermes", "--contract", self.contract, "--apply")
        self.assertEqual((code, result["status"]), (0, "APPLIED"), result)
        self.entry = self.root / ".agents/skills/wiki-desk/scripts/wiki_desk.py"
        return result

    def blocked(self, action, *args):
        before = tree(self.root)
        code, result = self.cli(action, *args)
        self.assertNotEqual(code, 0, result)
        self.assertEqual(result["status"], "BLOCKED", result)
        self.assertFalse(result["applied"])
        self.assertEqual(tree(self.root), before)
        return result

class ReleaseSafetyTests(ReleaseFixtureCase):
    def test_source_policy_real_reads_scan_denominator_and_allowed_drift(self):
        secrets = [".env", "docs/.env", "docs/.env.local", "docs/secrets/password.md",
                   "docs/credentials.json", "docs/cert.key", "docs/generated/hidden.md",
                   "docs/private/excluded.md", "docs/.cache/hidden.md"]
        for rel in secrets:
            self.put(rel, b"SYNTHETIC_SECRET_SENTINEL_DO_NOT_READ\n")
        secret_paths = {self.root / rel for rel in secrets}
        for scopes in (["."], ["docs"], ["docs/a.md"]):
            with self.subTest(scopes=scopes):
                self.config["source_roots"] = scopes
                self.save_contract()
                opened = []
                original_open, original_path_open = os.open, Path.open
                def os_spy(path, flags, *args, **kwargs):
                    if Path(path) in secret_paths:
                        opened.append(str(path))
                    return original_open(path, flags, *args, **kwargs)
                def path_spy(path, *args, **kwargs):
                    if path in secret_paths:
                        opened.append(str(path))
                    return original_path_open(path, *args, **kwargs)
                before = tree(self.root)
                with patch.object(os, "open", os_spy), patch.object(Path, "open", path_spy):
                    sources = desk._source_snapshot(self.root, self.config)
                    with redirect_stdout(io.StringIO()) as stdout:
                        code = desk.main(["scan", "--root", str(self.root), "--contract", str(self.contract)])
                    scanned = json.loads(stdout.getvalue())
                    planned = desk.prepare_install(self.root, "hermes", self.contract, self.package, now=STAMP)
                self.assertEqual(opened, [], "Excluded bodies were actually opened")
                self.assertEqual(code, 0, scanned)
                allowed = runtime._paths(self.root, runtime.validate_contract(self.config, self.root))
                self.assertEqual(scanned["source_count"], len(allowed))
                self.assertEqual({r["path"] for r in scanned["source_files"]}, set(allowed))
                self.assertTrue(set(secrets).isdisjoint(sources.as_dict()))
                self.assertEqual(tree(self.root), before)
                desk.apply_plan(planned)
                opened.clear()
                with patch.object(os, "open", os_spy), patch.object(Path, "open", path_spy):
                    for action in ("sync", "format"):
                        plan = desk.prepare_runtime_action(self.root, action, now=STAMP)
                        desk.validate_plan(plan)
                self.assertEqual(opened, [], "Runtime action read an excluded source")
                pending = desk.prepare_runtime_action(self.root, "sync", now=STAMP)
                original = (self.root / "docs/a.md").read_bytes()
                self.put("docs/a.md", b"# Actual allowed-file drift\n")
                drifted = tree(self.root)
                with self.assertRaises((fs.SafetyError, ValueError)):
                    desk.apply_plan(pending)
                self.assertEqual(tree(self.root), drifted)
                self.put("docs/a.md", original)
                desk.apply_plan(desk.prepare_remove(self.root, remove_unchanged_wiki=True))

    def test_explicit_secret_source_file_is_pruned_before_open(self):
        secret = self.put("docs/.env", b"SYNTHETIC_SECRET\n")
        self.config["source_roots"] = ["docs/.env"]
        self.save_contract()
        original, original_os_open = Path.open, os.open
        def spy(path, *args, **kwargs):
            if path == secret:
                self.fail("Explicit excluded source root was read")
            return original(path, *args, **kwargs)
        def os_spy(path, flags, *args, **kwargs):
            if Path(path) == secret:
                self.fail("Explicit excluded source root was opened by fs_safety")
            return original_os_open(path, flags, *args, **kwargs)
        with patch.object(Path, "open", spy), patch.object(os, "open", os_spy), redirect_stdout(io.StringIO()) as stdout:
            code = desk.main(["scan", "--root", str(self.root), "--contract", str(self.contract)])
        result = json.loads(stdout.getvalue())
        self.assertEqual(code, 0, result)
        self.assertEqual(result["source_count"], 0)
        self.assertEqual(result["source_files"], [])

    def test_new_secret_after_planning_is_never_opened_by_stale_guard(self):
        for action, rel in (("install", "docs/.env"), ("sync", "docs/.env.local"),
                            ("format", "docs/newsecrets/secrets.json")):
            with self.subTest(action=action):
                if action == "install":
                    plan = desk.prepare_install(self.root, "hermes", self.contract, self.package, now=STAMP)
                else:
                    plan = desk.prepare_runtime_action(self.root, action, now=STAMP)
                secret = self.put(rel, b"NEW_SYNTHETIC_SECRET_MUST_NOT_BE_OPENED\n")
                before = tree(self.root)
                opened = []
                original = os.open
                def spy(path, flags, *args, **kwargs):
                    if Path(path) == secret:
                        opened.append(str(path))
                    return original(path, flags, *args, **kwargs)
                with patch.object(os, "open", spy):
                    # Actual RED mechanism: generic verification reuses a stale
                    # exclusion tuple and opens a newly introduced credential.
                    with self.assertRaises(fs.SafetyError):
                        fs.verify_snapshot(plan.guards[-1])
                    self.assertEqual(opened, [str(secret)])
                    opened.clear()
                    # GREEN boundary must rederive shared exclusions FIRST.
                    with self.assertRaises(fs.SafetyError):
                        desk.apply_plan(plan)
                    self.assertEqual(opened, [])
                self.assertEqual(before, tree(self.root))
                secret.unlink()
                if action == "install":
                    self.install()

    def test_invalid_actual_format_check_and_apply_whole_plan_refusal(self):
        self.install()
        bad_cases = {
            "unsafe": b"---\ntype: !!python/object/apply:os.system [NOT_EXECUTED]\n---\n# Bad\n",
            "malformed": b"---\ntype: [\n---\n# Bad\n",
            "duplicate": b"---\ntype: Reference\ntype: Conflict\n---\n# Bad\n",
            "actor": b"---\ntype: Reference\nverified: {by: '', at: '2026-10-04T00:00:00Z'}\n---\n# Bad\n",
            "timestamp": b"---\ntype: Reference\nverified: {by: alice, at: not-a-timestamp}\n---\n# Bad\n",
            "generated": b"---\ntype: Reference\ngenerated: []\n---\n# Bad\n",
            "legacy-conflict": b"---\ntype: [invalid]\nlegacy_type: retained\n---\n# Bad\n",
            "workflow-conflict": b"---\ntype: Reference\nstatus: approved\nworkflow_status: pending\nlegacy_status: conflicting\n---\n# Bad\n",
        }
        self.put("__llm-wiki/good.md", b"# Valid legacy page\n\nSafe user prose.\n")
        for label, data in bad_cases.items():
            with self.subTest(label=label):
                self.put("__llm-wiki/bad.md", data)
                self.blocked("format", "--check")
                self.blocked("format", "--apply")
        (self.root / "__llm-wiki/bad.md").unlink()
        self.put("__llm-wiki/log.md", b"# Log\n\n## [2026-02-30] historical action | important subject\n")
        self.blocked("format", "--check")
        self.blocked("format", "--apply")

    def test_actual_fixed_point_only_valid_is_conformant(self):
        self.install()
        code, result = self.cli("format", "--apply")
        self.assertEqual(code, 0, result)
        before = tree(self.root)
        code, result = self.cli("format", "--check")
        self.assertEqual((code, result["status"]), (0, "CONFORMANT"), result)
        self.assertEqual(before, tree(self.root))
        self.put("__llm-wiki/bad.md", b"---\ntype: !!python/object/apply:os.system [NOT_EXECUTED]\n---\n# Bad\n")
        self.blocked("format", "--check")

    def test_report_flags_cannot_certify_corrupt_actual_outputs(self):
        self.install()
        self.put("__llm-wiki/user.md", b"---\ntype: Custom\nunknown: {nested: preserved}\n---\n# User\n\nUSER_CONTENT_MUST_SURVIVE\n")
        native = runtime.format_plan
        for corruption in ("body-loss", "metadata-loss", "invalid-output", "missing-page"):
            with self.subTest(corruption=corruption):
                def corrupt(*args, **kwargs):
                    result = native(*args, **kwargs)
                    rel = "__llm-wiki/user.md"
                    if corruption == "body-loss":
                        result["outputs"][rel] = result["outputs"][rel].replace(b"USER_CONTENT_MUST_SURVIVE", b"LOST")
                    elif corruption == "metadata-loss":
                        result["outputs"][rel] = result["outputs"][rel].replace(b"unknown: {nested: preserved}\n", b"").replace(b"unknown:\n  nested: preserved\n", b"")
                    elif corruption == "invalid-output":
                        result["outputs"][rel] = b"---\ntype: !!python/object/apply:os.system [NOT_EXECUTED]\n---\n# Bad\n"
                    else:
                        del result["outputs"][rel]
                    # Bind forged report hashes too: false-PASS flags and row
                    # consistency must not substitute for actual core/retention.
                    if rel in result["outputs"]:
                        digest = hashlib.sha256(result["outputs"][rel]).hexdigest()
                        for key in ("markdown_files", "files", "paths"):
                            for row in result["report"][key]:
                                if row["path"] == rel:
                                    row["after_sha256"] = digest
                    return result
                before = tree(self.root)
                reason = "inventory" if corruption == "missing-page" else "Actual runtime output"
                with patch.object(runtime, "format_plan", corrupt), self.assertRaisesRegex(fs.SafetyError, reason):
                    desk.prepare_runtime_action(self.root, "format", now=STAMP)
                self.assertEqual(before, tree(self.root))

    def test_trusted_recipe_rechecks_actual_validation_at_apply(self):
        self.install()
        plan = desk.prepare_runtime_action(self.root, "format", now=STAMP)
        native = runtime.format_plan
        def invalid_report(*args, **kwargs):
            result = native(*args, **kwargs)
            result["report"]["error_count"] = 1
            return result
        before = tree(self.root)
        with patch.object(runtime, "format_plan", invalid_report), self.assertRaises((fs.SafetyError, ValueError)):
            desk.apply_plan(plan)
        self.assertEqual(before, tree(self.root))

    def test_generated_user_edits_stay_protected_after_format_and_sync(self):
        self.install()
        for leaf in ("index.md", "log.md", "SCHEMA.md"):
            path = self.root / "__llm-wiki" / leaf
            data = path.read_bytes()
            # Outside any generated block; ordinary format rewrites this link.
            self.put("__llm-wiki/" + leaf, data + b"\nUSER_AUTHORED_IMPORTANT_NOTE [[SCHEMA]]\n")
        code, result = self.cli("format", "--apply")
        self.assertEqual(code, 0, result)
        receipt = desk._read_receipt(self.root, SKILL)
        for leaf in ("index.md", "log.md", "SCHEMA.md"):
            key = "__llm-wiki/" + leaf
            self.assertTrue(receipt["owned_files"][key].get("protected_user_content"), key)
            self.assertEqual(receipt["owned_files"][key]["preimage"], {"kind": "missing"})
            self.assertIn(b"USER_AUTHORED_IMPORTANT_NOTE", (self.root / key).read_bytes())
        code, result = self.cli("status")
        self.assertEqual(code, 0, result)
        self.assertEqual(set(result["protected_user_files"]), {"__llm-wiki/" + leaf for leaf in ("index.md", "log.md", "SCHEMA.md")})
        self.assertFalse(result["full_fresh_inverse_allowed"])
        self.blocked("remove", "--apply", "--remove-unchanged-wiki")
        self.put("docs/a.md", b"# Source changed by user\n")
        code, result = self.cli("sync", "--apply")
        self.assertEqual(code, 0, result)
        code, result = self.cli("format", "--apply")
        self.assertEqual(code, 0, result)
        for leaf in ("index.md", "log.md", "SCHEMA.md"):
            self.assertTrue(desk._read_receipt(self.root, SKILL)["owned_files"]["__llm-wiki/" + leaf]["protected_user_content"])
        self.blocked("remove", "--apply", "--remove-unchanged-wiki")
        wiki_before = tree(self.root / "__llm-wiki")
        code, result = self.cli("remove", "--apply")
        self.assertEqual(code, 0, result)
        self.assertEqual(wiki_before, tree(self.root / "__llm-wiki"))
        self.assertTrue((self.root / "docs/a.md").exists())

    def test_sync_rebase_cannot_grant_remove_permission_to_user_index(self):
        self.install()
        path = self.root / "__llm-wiki/index.md"
        self.put("__llm-wiki/index.md", path.read_bytes() + b"\nUSER_NOTE_RETAINED\n")
        self.put("__llm-wiki/new.md", b"---\ntype: Reference\n---\n# New page\n")
        code, result = self.cli("sync", "--apply")
        self.assertEqual(code, 0, result)
        receipt = desk._read_receipt(self.root, SKILL)
        self.assertTrue(receipt["owned_files"]["__llm-wiki/index.md"].get("protected_user_content"))
        self.blocked("remove", "--apply", "--remove-unchanged-wiki")

    def test_receipt_protection_flag_must_be_boolean_and_status_guarded(self):
        self.install()
        receipt = desk._read_receipt(self.root, SKILL)
        receipt["owned_files"]["__llm-wiki/index.md"]["protected_user_content"] = "false"
        self.put(desk.receipt_rel(SKILL), desk.json_bytes(receipt))
        self.blocked("status")
        self.blocked("remove", "--apply", "--remove-unchanged-wiki")

    def test_pure_generated_delta_still_has_exact_inverse(self):
        before = tree(self.root)
        self.install()
        code, result = self.cli("format", "--apply")
        self.assertEqual(code, 0, result)
        original = (self.root / "docs/a.md").read_bytes()
        self.put("docs/a.md", b"# Updated original\n")
        code, result = self.cli("sync", "--apply")
        self.assertEqual(code, 0, result)
        self.put("docs/a.md", original)
        code, result = self.cli("remove", "--apply", "--remove-unchanged-wiki")
        self.assertEqual(code, 0, result)
        self.assertEqual(before, tree(self.root))

    def test_release_closure_requires_dev_dependencies_and_security_tests(self):
        self.assertIn("requirements-dev.txt", manifest.REQUIRED_FILES)
        self.assertIn("tests/test_release_safety.py", manifest.REQUIRED_FILES)
        for rel in ("requirements-dev.txt", "tests/test_release_safety.py"):
            with self.subTest(rel=rel):
                path = self.package / rel
                contents = path.read_bytes()
                path.unlink()
                with self.assertRaises(fs.SafetyError):
                    manifest.generate(self.package)
                path.write_bytes(contents)


if __name__ == "__main__":
    unittest.main()
