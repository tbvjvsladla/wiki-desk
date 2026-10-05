"""Lifecycle/FS unit fixtures. No live host/model discovery is claimed.

RuntimeFixture isolates the NEW published API; real runtime/scaffold plus
installed-copy integration is a separate release gate run by the parent.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import base64
from contextlib import redirect_stdout
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import types
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).absolute().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fs_safety as fs  # type: ignore[import-not-found]
import package_manifest as manifest  # type: ignore[import-not-found]
import wiki_desk as desk  # type: ignore[import-not-found]

SKILL = desk.HOSTS["hermes"]
FIXTURE_PARENT = Path(os.environ.get("WIKI_DESK_TEST_TMPDIR", tempfile.gettempdir()))


def tree(root: Path) -> tuple:
    """Independent no-follow state observer including invalid/special paths."""
    result = []
    def visit(path: Path) -> None:
        st = path.lstat()
        mode = stat.S_IMODE(st.st_mode)
        rel = path.relative_to(root).as_posix()
        if stat.S_ISLNK(st.st_mode):
            result.append((rel, "symlink", mode, os.readlink(path)))
        elif stat.S_ISDIR(st.st_mode):
            result.append((rel, "dir", mode, tuple(sorted(p.name for p in path.iterdir()))))
            for child in sorted(path.iterdir()):
                visit(child)
        elif stat.S_ISREG(st.st_mode):
            result.append((rel, "file", mode, hashlib.sha256(path.read_bytes()).hexdigest(), st.st_size))
        else:
            result.append((rel, "special", mode, stat.S_IFMT(st.st_mode)))
    visit(root)
    return tuple(result)


class FixtureCase(unittest.TestCase):
    def setUp(self) -> None:
        FIXTURE_PARENT.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="unit-", dir=FIXTURE_PARENT)
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.root = self.home / "project"
        self.root.mkdir()

    def put(self, rel: str, data: bytes = b"contents\n", mode: int = 0o644,
            root: Path | None = None) -> Path:
        path = (root or self.root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)
        return path

    def assert_refusal_unchanged(self, function, *, root: Path | None = None) -> None:
        root = root or self.root
        before = tree(root)
        with self.assertRaises((fs.SafetyError, OSError, ValueError)):
            function()
        self.assertEqual(before, tree(root))


class FilesystemSafetyTests(FixtureCase):
    def test_canonical_safe_relative_and_escape(self):
        for rel in ("", ".", "..", "../outside", "a/../../b", "/etc/passwd", "a//b", "a/./b",
                    "a/", "a\\b", "C:/escape", "nul\x00name"):
            with self.subTest(rel=rel), self.assertRaises(fs.SafetyError):
                fs.safe_relative(rel)
        self.assertEqual(fs.safe_relative("한국어/한 문서.md"), "한국어/한 문서.md")
        self.assertEqual(fs.canonical_root(self.root), self.root)
        with self.assertRaises(fs.SafetyError):
            fs.canonical_root(Path("/"))
        with self.assertRaises(fs.SafetyError):
            fs.canonical_root(self.root / "../project")
        with self.assertRaises(fs.SafetyError):
            fs.canonical_root(self.home / "absent")

    def test_root_ancestor_directory_and_file_symlinks(self):
        outside = self.home / "outside"
        outside.mkdir()
        self.put("plain.md")
        (self.home / "alias").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(fs.SafetyError):
            fs.canonical_root(self.home / "alias")
        with self.assertRaises(fs.SafetyError):
            fs.canonical_root(self.home / "alias" / "nested")
        (self.root / "directory-link").symlink_to(outside, target_is_directory=True)
        (self.root / "file-link").symlink_to(self.root / "plain.md")
        for rel in ("directory-link", "directory-link/new.md", "file-link"):
            self.assert_refusal_unchanged(lambda rel=rel: fs.safe_path(self.root, rel))
        self.assertEqual(tree(outside), ((".", "dir", stat.S_IMODE(outside.stat().st_mode), ()),))

    def test_special_file_and_file_parent_collision(self):
        os.mkfifo(self.root / "pipe")
        self.assert_refusal_unchanged(lambda: fs.snapshot(self.root, ("pipe",)))
        self.put("file-parent")
        self.assert_refusal_unchanged(lambda: fs.safe_path(self.root, "file-parent/child"))

    def test_atomic_helper_itself_refuses_symlink_directory_special(self):
        self.put("real", b"original")
        (self.root / "link").symlink_to(self.root / "real")
        (self.root / "directory").mkdir()
        os.mkfifo(self.root / "fifo")
        for rel in ("link", "directory", "fifo"):
            with self.subTest(rel=rel):
                self.assert_refusal_unchanged(lambda rel=rel: fs.atomic_bytes(self.root / rel, b"bad"))

    def test_snapshot_guards_nested_types_modes_hashes_children(self):
        self.put("owned/a/b.md", b"a", 0o600)
        baseline = fs.snapshot(self.root, ("owned",))
        self.assertEqual(baseline.as_dict()["owned/a/b.md"].sha256, hashlib.sha256(b"a").hexdigest())
        (self.root / "owned/a/b.md").chmod(0o644)
        self.assert_refusal_unchanged(lambda: fs.verify_snapshot(baseline))
        (self.root / "owned/a/b.md").chmod(0o600)
        fs.verify_snapshot(baseline)
        self.put("owned/new.md")
        self.assert_refusal_unchanged(lambda: fs.verify_snapshot(baseline))

    def test_complete_preflight_last_write_unsafe_and_collision(self):
        self.put("owned/a.md", b"before")
        baseline = fs.snapshot(self.root, ("owned",))
        for writes in ((fs.Write("owned/a.md", b"after"), fs.Write("../escape", b"bad")),
                       (fs.Write("owned/a.md", b"after"), fs.Write("owned", b"bad")),
                       (fs.Write("owned/a.md", b"after"), fs.Write("owned/a.md", b"duplicate")),
                       (fs.Write("owned/a.md", b"after"), fs.Write("unguarded.md", b"bad"))):
            tx = fs.Transaction(self.root, baseline, writes)
            self.assert_refusal_unchanged(tx.apply)

    def test_new_descendants_inside_existing_guarded_tree(self):
        self.put("owned/existing.md", b"old")
        baseline = fs.snapshot(self.root, ("owned",))
        tx = fs.Transaction(self.root, baseline,
                            (fs.Write("owned/new/nested.md", b"new"), fs.Write("owned/sibling.md", b"sibling")),
                            mkdirs=(("owned/new", 0o755),))
        self.assertEqual(tx.apply()["writes"], 2)
        self.assertEqual((self.root / "owned/new/nested.md").read_bytes(), b"new")

    def test_mixed_file_directory_mutation_collisions_preflight(self):
        baseline = fs.snapshot(self.root, ("fresh",))
        tx = fs.Transaction(self.root, baseline, (fs.Write("fresh", b"file"),),
                            mkdirs=(("fresh/child", 0o755),))
        self.assert_refusal_unchanged(tx.apply)
        (self.root / "fresh").mkdir()
        baseline = fs.snapshot(self.root, ("fresh",))
        tx = fs.Transaction(self.root, baseline, rmdirs=("fresh",),
                            mkdirs=(("fresh", 0o755),))
        self.assert_refusal_unchanged(tx.apply)

    def test_baseline_file_and_parent_drift_refuse_before_writes(self):
        self.put("owned/a.md", b"before")
        baseline = fs.snapshot(self.root, ("owned", "fresh"))
        tx = fs.Transaction(self.root, baseline, (fs.Write("owned/a.md", b"after"), fs.Write("fresh/x.md", b"new")))
        self.put("owned/a.md", b"user edit")
        self.assert_refusal_unchanged(tx.apply)
        self.put("owned/a.md", b"before")
        self.root.chmod(0o700)
        self.assert_refusal_unchanged(tx.apply)

    def test_unrelated_env_bytes_are_not_a_baseline_dependency(self):
        self.put(".env", b"unrelated initial\n", 0o600)
        baseline = fs.snapshot(self.root, ("owned",))
        self.put(".env", b"user changed secret body\n", 0o600)
        result = fs.Transaction(self.root, baseline, (fs.Write("owned/a.md", b"new"),)).apply()
        self.assertTrue(result["readback_verified"])
        self.assertEqual((self.root / ".env").read_bytes(), b"user changed secret body\n")
        self.assertNotIn(".env", baseline.as_dict())

    def test_exception_after_every_mutation_exact_rollback(self):
        self.put("owned/a.bin", b"\x00\xffold", 0o600)
        self.put("owned/gone.md", b"delete", 0o640)
        (self.root / "owned/empty").mkdir(mode=0o700)
        initial = tree(self.root)
        def make():
            return fs.Transaction(self.root, fs.snapshot(self.root, ("owned", "new")),
                (fs.Write("owned/a.bin", b"\xffreplacement", 0o755), fs.Write("new/nested/b.md", b"fresh")),
                ("owned/gone.md",), ("owned/empty",), (("new/empty", 0o755),))
        seen = []
        result = make().apply(fault=lambda count, rel: seen.append((count, rel)))
        mutations = result["mutations"]
        # Restore this unit fixture without using the code under test.
        import shutil
        shutil.rmtree(self.root)
        self.root.mkdir()
        self.put("owned/a.bin", b"\x00\xffold", 0o600)
        self.put("owned/gone.md", b"delete", 0o640)
        (self.root / "owned/empty").mkdir(mode=0o700)
        self.assertEqual(initial, tree(self.root))
        for failing in range(1, mutations + 1):
            with self.subTest(failing=failing):
                def fault(count, rel):
                    if count == failing:
                        raise RuntimeError("injected after " + str(count))
                with self.assertRaisesRegex(RuntimeError, "injected"):
                    make().apply(fault=fault)
                self.assertEqual(initial, tree(self.root))

    def test_readback_failure_and_keyboard_interrupt_rollback(self):
        self.put("owned/file", b"preimage", 0o600)
        baseline = fs.snapshot(self.root, ("owned",))
        tx = fs.Transaction(self.root, baseline, (fs.Write("owned/file", b"changed", 0o755),))
        initial = tree(self.root)
        with self.assertRaisesRegex(RuntimeError, "readback"):
            tx.apply(readback=lambda: (_ for _ in ()).throw(RuntimeError("readback failure")))
        self.assertEqual(initial, tree(self.root))
        with self.assertRaises(KeyboardInterrupt):
            tx.apply(fault=lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        self.assertEqual(initial, tree(self.root))

    def test_fsync_failure_after_replace_rolls_back_and_cleans_temporary(self):
        self.put("owned/file", b"preimage", 0o600)
        baseline = fs.snapshot(self.root, ("owned",))
        tx = fs.Transaction(self.root, baseline, (fs.Write("owned/file", b"changed"),))
        original = fs._fsync_dir
        calls = 0
        def once(path):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("injected fsync")
            return original(path)
        initial = tree(self.root)
        with patch.object(fs, "_fsync_dir", once), self.assertRaisesRegex(OSError, "injected fsync"):
            tx.apply()
        self.assertEqual(initial, tree(self.root))

    def test_directory_removal_cannot_drop_user_children(self):
        self.put("owned/user.md", b"user")
        baseline = fs.snapshot(self.root, ("owned",))
        self.assert_refusal_unchanged(fs.Transaction(self.root, baseline, rmdirs=("owned",)).apply)


class PackageFixtureCase(FixtureCase):
    def make_package(self) -> Path:
        package = self.home / "package"
        package.mkdir()
        for rel in manifest.REQUIRED_FILES:
            self.put(rel, b"Unit-fixture package placeholder; NOT a live host invocation.\n", root=package)
        self.put("support/nested/a.txt", b"complete closure\n", root=package)
        (package / "empty-directory").mkdir()
        (package / "scripts/wiki_desk.py").chmod(0o755)
        return package



class ManifestTests(PackageFixtureCase):
    def test_generate_deterministic_verify_entire_closure(self):
        package = self.make_package()
        first = manifest.generate(package)
        raw = (package / manifest.MANIFEST_NAME).read_bytes()
        second = manifest.generate(package)
        self.assertEqual(raw, (package / manifest.MANIFEST_NAME).read_bytes())
        self.assertEqual(first, second)
        self.assertIn("support/nested/a.txt", [x["path"] for x in first["inventory"]["files"]])
        self.assertIn("empty-directory", first["inventory"]["directories"])
        self.assertFalse(first["publisher_trust_verified"])

    def test_missing_manifest_bounded_blocked_not_pass(self):
        package = self.make_package()
        with self.assertRaises(manifest.ManifestMissing):
            manifest.verify(package)

    def test_content_size_mode_extra_file_entrypoint_tamper(self):
        for mode in ("content", "mode", "extra", "entrypoint", "missing"):
            with self.subTest(mode=mode):
                package = self.make_package()
                manifest.generate(package)
                if mode == "content":
                    self.put("SKILL.md", b"edited", root=package)
                elif mode == "mode":
                    (package / "scripts/wiki_desk.py").chmod(0o644)
                elif mode == "extra":
                    self.put("unmanifested.txt", root=package)
                elif mode == "entrypoint":
                    declared = json.loads((package / manifest.MANIFEST_NAME).read_bytes())
                    declared["entrypoints"] = []
                    self.put(manifest.MANIFEST_NAME, desk.json_bytes(declared), root=package)
                else:
                    (package / "scripts/wiki_runtime.py").unlink()
                with self.assertRaises(fs.SafetyError):
                    manifest.verify(package)
                import shutil
                shutil.rmtree(package)

    def test_excludes_only_git_cache_manifest_not_support_docs(self):
        package = self.make_package()
        self.put(".git/config", b"git ignored", root=package)
        self.put("scripts/__pycache__/cached.pyc", b"cache ignored", root=package)
        report = manifest.generate(package)
        self.assertTrue(report["verified"])
        self.put(".git/extra", root=package)
        self.put("scripts/__pycache__/more.pyc", root=package)
        self.assertTrue(manifest.verify(package)["verified"])
        self.put("references/extra.md", root=package)
        with self.assertRaises(fs.SafetyError):
            manifest.verify(package)

    def test_package_symlink_and_special_refused(self):
        package = self.make_package()
        (package / "link").symlink_to(package / "SKILL.md")
        with self.assertRaises(fs.SafetyError):
            manifest.generate(package)
        (package / "link").unlink()
        os.mkfifo(package / "pipe")
        with self.assertRaises(fs.SafetyError):
            manifest.generate(package)


class RuntimeFixture:
    """Deterministic lifecycle isolation. Not the release runtime/host verifier."""
    @staticmethod
    def source_exclusions(root, contract):
        import wiki_runtime
        return wiki_runtime.source_exclusions(root, contract)

    @staticmethod
    def preservation(before, after, bundle, rel):
        import wiki_runtime
        return wiki_runtime.preservation(before, after, bundle, rel)

    def validate_contract(self, contract, root):
        if not isinstance(contract, dict) or contract.get("schema_version") != 1:
            raise fs.SafetyError("Fixture contract invalid")
        fs.safe_relative(contract["wiki_dir"])
        return dict(contract)

    def scaffold_files(self, root, contract, now=None):
        wiki = contract["wiki_dir"]
        return {wiki + "/index.md": b"---\nokf_version: '0.2'\n---\n\n# Fixture wiki\n",
                wiki + "/source-registry.md": b"---\ntype: Reference\n---\n\nFixture paths only\n\n"}

    def plan_result(self, root, contract, changes):
        """Explicit complete API contract, not a preserved=True shortcut.

        Desired outputs include unchanged Markdown. Real content validators and
        preservation are still required by the lifecycle boundary.
        """
        wiki = contract["wiki_dir"]
        before = {p.relative_to(root).as_posix(): p.read_bytes()
                  for p in sorted((root / wiki).rglob("*.md"))}
        outputs = {**before, **changes}
        source = desk._source_snapshot(root, contract)
        hashes = {rel: state.sha256 for rel, state in source.entries if state.kind == "file"}
        rows = [{"path": rel, "before_sha256": hashlib.sha256(before[rel]).hexdigest() if rel in before else None,
                 "after_sha256": hashlib.sha256(data).hexdigest(), "issues": []}
                for rel, data in sorted(outputs.items())]
        expected, final = len(before), len(outputs)
        report = {"error_count": 0, "expected": expected, "collected": expected, "unique": expected,
                  "final_expected": final, "final_collected": final, "final_unique": final,
                  "file_count": final, "source_count": len(hashes), "coverage_complete": True,
                  "coverage": {"expected": expected, "collected": expected, "unique": expected, "complete": True},
                  "preservation_complete": True, "snapshot_unchanged": True,
                  "source_snapshot_unchanged": True, "conformant": True,
                  "markdown_files": rows, "nonmarkdown_files": [], "files": rows}
        return {"outputs": outputs, "report": report, "source_snapshot": hashes}

    def sync_plan(self, root, contract, now=None):
        wiki = contract["wiki_dir"]
        source = (root / "docs/source.md").read_bytes()
        data = (b"---\ntype: Reference\n---\n\nFixture paths only\n\n"
                b"<!-- wiki-desk:source-registry:start -->\nFixture source digest: " +
                hashlib.sha256(source).hexdigest().encode() +
                b"\n<!-- wiki-desk:source-registry:end -->")
        return self.plan_result(root, contract, {wiki + "/source-registry.md": data})

    def format_plan(self, root, contract, now=None):
        import okf_bundle
        wiki = contract["wiki_dir"]
        outputs = {}
        for path in sorted((root / wiki).rglob("*.md")):
            data = path.read_bytes()
            rel = path.relative_to(root / wiki).as_posix()
            if path.name == "index.md":
                text = okf_bundle.normalize_index(root / wiki, rel, data.decode())
            else:
                text = okf_bundle.normalize_concept(root / wiki, rel, data.decode(), now=now)
            outputs[path.relative_to(root).as_posix()] = text.encode()
        return self.plan_result(root, contract, outputs)

    def query(self, root, contract, terms, limit=10):
        return {"originals_reviewed": False, "candidates": [{"path": "docs/source.md"}]}

    def check_bundle(self, root, contract):
        return {"conformant": True, "error_count": 0, "expected": 2, "collected": 2, "unique": 2}


class LifecycleFixtureCase(PackageFixtureCase):
    def setUp(self):
        super().setUp()
        self.package = self.make_package()
        manifest.generate(self.package)
        self.put("docs/source.md", b"Original project source, never copied into wiki.\n")
        self.put("HERMES.md", b"Existing user context\n")
        self.put(".env", b"Unrelated user environment\n", 0o600)
        self.contract = self.home / "contract.json"
        self.config = {"schema_version": 1, "project_name": "Unit fixture",
                       "wiki_dir": "__llm-wiki", "source_roots": ["docs"], "excluded_roots": [],
                       "authority_rules": [], "fallback": {"document_type": "reference", "authority_rank": 0,
                                                            "role": "reference"}, "copy_policy": "path_reference"}
        self.contract.write_bytes(desk.json_bytes(self.config))
        self.runtime = RuntimeFixture()
        self.mock = patch.object(desk, "_runtime", return_value=self.runtime)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def install_plan(self, host="hermes"):
        return desk.prepare_install(self.root, host, self.contract, self.package, now="2026-01-01T00:00:00Z")

    def install(self, host="hermes"):
        return desk.apply_plan(self.install_plan(host))


class LifecycleUnitTests(LifecycleFixtureCase):
    def test_install_dryrun_is_exact_write_zero(self):
        before = tree(self.root)
        source_before = tree(self.package)
        plan = self.install_plan()
        desk.validate_plan(plan)
        self.assertEqual(plan.report["writes"], 0)
        self.assertEqual(before, tree(self.root))
        self.assertEqual(source_before, tree(self.package))
        self.assertFalse(plan.report["process_crash_atomic"])

    def test_adapter_mapping_complete_copy_idempotent_status(self):
        for host, skill in desk.HOSTS.items():
            with self.subTest(host=host):
                root = self.home / ("target-" + host)
                root.mkdir()
                self.put("docs/source.md", b"source", root=root)
                before = tree(root)
                plan = desk.prepare_install(root, host, self.contract, self.package, now="fixed")
                result = desk.apply_plan(plan)
                self.assertTrue(result["readback_verified"])
                self.assertEqual(result["status"], "APPLIED")
                self.assertGreater(result["writes"], 0)
                self.assertEqual((root / skill / "support/nested/a.txt").read_bytes(), b"complete closure\n")
                self.assertTrue((root / skill / "empty-directory").is_dir())
                for record in manifest.verify(self.package)["inventory"]["files"]:
                    self.assertEqual((root / skill / record["path"]).read_bytes(),
                                     (self.package / record["path"]).read_bytes())
                self.assertTrue((root / skill / manifest.MANIFEST_NAME).is_file())
                installed = tree(root)
                repeat = desk.prepare_install(root, host, self.contract, self.package, now="different")
                self.assertTrue(repeat.report["idempotent"])
                self.assertEqual(desk.apply_plan(repeat)["mutations"], 0)
                self.assertEqual(installed, tree(root))
                state = desk.status(root)
                self.assertEqual(state["changed_owned_files"], [])
                self.assertFalse(state["semantic_approval_verified"])
                self.assertFalse(state["host_live_discovery_verified"])
                inverse = desk.prepare_remove(root, remove_unchanged_wiki=True)
                desk.apply_plan(inverse)
                self.assertEqual(before, tree(root))

    def test_hyphen_underscore_wiki_names(self):
        for wiki in ("__llm-wiki", "__llm_wiki"):
            with self.subTest(wiki=wiki):
                self.config["wiki_dir"] = wiki
                self.contract.write_bytes(desk.json_bytes(self.config))
                before = tree(self.root)
                self.install()
                self.assertTrue((self.root / wiki / "index.md").is_file())
                desk.apply_plan(desk.prepare_remove(self.root, remove_unchanged_wiki=True))
                self.assertEqual(before, tree(self.root))

    def test_collision_refuses_existing_wiki_skill_and_admin(self):
        for rel in ("__llm-wiki", ".agents/skills/wiki-desk", ".wiki-desk"):
            with self.subTest(rel=rel):
                path = self.root / rel
                path.mkdir(parents=True)
                self.put(rel + "/user.md", b"user preserved")
                self.assert_refusal_unchanged(self.install_plan)
                import shutil
                shutil.rmtree(path)

    def test_host_parent_symlink_refuses_and_outside_unchanged(self):
        outside = self.home / "outside"
        outside.mkdir()
        (self.root / ".agents").symlink_to(outside, target_is_directory=True)
        outside_before = tree(outside)
        self.assert_refusal_unchanged(self.install_plan)
        self.assertEqual(outside_before, tree(outside))

    def test_invalid_runtime_output_last_entry_refuses_everything(self):
        original = self.runtime.scaffold_files
        def invalid(*args, **kwargs):
            return {**original(*args, **kwargs), "HERMES.md": b"overwrite context forbidden"}
        with patch.object(self.runtime, "scaffold_files", invalid):
            self.assert_refusal_unchanged(self.install_plan)

    def test_payload_object_and_forged_serialized_plan_refused(self):
        plan = self.install_plan()
        original = plan.transaction
        altered = replace(original, writes=(fs.Write("__llm-wiki/index.md", b"tampered"),) + original.writes[1:])
        object.__setattr__(plan, "transaction", altered)
        self.assert_refusal_unchanged(lambda: desk.apply_plan(plan))
        fresh = self.install_plan()
        fresh.report["fake"] = "mutable object tamper"
        self.assert_refusal_unchanged(lambda: desk.apply_plan(fresh))
        forged = desk.PreparedPlan("install", original, (), {})
        self.assert_refusal_unchanged(lambda: desk.apply_plan(forged))
        self.assert_refusal_unchanged(lambda: desk.validate_plan({"action": "install"}))

    def test_contract_source_package_and_destination_drift_refuse(self):
        for kind in ("contract", "source", "package", "destination", "parent-mode"):
            with self.subTest(kind=kind):
                before_bytes = self.contract.read_bytes()
                plan = self.install_plan()
                if kind == "contract":
                    self.contract.write_bytes(before_bytes + b" ")
                elif kind == "source":
                    self.put("docs/source.md", b"changed source")
                elif kind == "package":
                    self.put("SKILL.md", b"changed package", root=self.package)
                elif kind == "destination":
                    self.put("__llm-wiki/new-user.md", b"new user data")
                else:
                    self.root.chmod(0o700)
                self.assert_refusal_unchanged(lambda: desk.apply_plan(plan))
                if kind == "contract":
                    self.contract.write_bytes(before_bytes)
                elif kind == "source":
                    self.put("docs/source.md", b"Original project source, never copied into wiki.\n")
                elif kind == "package":
                    self.put("SKILL.md", b"Unit-fixture package placeholder; NOT a live host invocation.\n", root=self.package)
                elif kind == "destination":
                    import shutil
                    shutil.rmtree(self.root / "__llm-wiki")
                else:
                    self.root.chmod(0o755)

    def test_trusted_runtime_recomputation_catches_different_payload(self):
        plan = self.install_plan()
        with patch.object(self.runtime, "scaffold_files", return_value={"__llm-wiki/index.md": b"changed trusted output"}):
            self.assert_refusal_unchanged(lambda: desk.apply_plan(plan))

    def test_install_fault_after_every_owned_mutation_exact_rollback(self):
        initial = tree(self.root)
        observed = []
        result = desk.apply_plan(self.install_plan(), fault=lambda count, rel: observed.append(count))
        total = result["mutations"]
        desk.apply_plan(desk.prepare_remove(self.root, remove_unchanged_wiki=True))
        self.assertEqual(initial, tree(self.root))
        for failing in range(1, total + 1):
            with self.subTest(failing=failing):
                def fault(count, rel):
                    if count == failing:
                        raise RuntimeError("injected install")
                with self.assertRaisesRegex(RuntimeError, "injected install"):
                    desk.apply_plan(self.install_plan(), fault=fault)
                self.assertEqual(initial, tree(self.root))

    def test_default_remove_dryrun_and_apply_preserve_wiki_user_context(self):
        self.install()
        self.put("__llm-wiki/user-notes.md", b"My own wiki notes\n")
        before = tree(self.root)
        wiki_before = tree(self.root / "__llm-wiki")
        plan = desk.prepare_remove(self.root)
        desk.validate_plan(plan)
        self.assertEqual(before, tree(self.root))
        desk.apply_plan(plan)
        self.assertEqual(wiki_before, tree(self.root / "__llm-wiki"))
        self.assertEqual((self.root / "HERMES.md").read_bytes(), b"Existing user context\n")
        self.assertEqual((self.root / ".env").read_bytes(), b"Unrelated user environment\n")
        # Package files are gone; the operating state stays inside the skill dir.
        skill = self.root / SKILL
        self.assertEqual(sorted(p.relative_to(skill).as_posix() for p in skill.rglob("*") if p.is_file()),
                         ["project/contract.json", "project/receipt.json"])
        self.assertFalse((self.root / desk.LEGACY_ADMIN).exists())
        self.assertFalse(desk.status(self.root)["installed"])
        self.assert_refusal_unchanged(lambda: desk.prepare_remove(self.root, remove_unchanged_wiki=True))

    def test_full_remove_refuses_changed_ownedfile_extra_wiki_file_or_directory(self):
        self.install()
        for rel in ("__llm-wiki/user.md", "__llm-wiki/user-directory"):
            path = self.root / rel
            if rel.endswith("directory"):
                path.mkdir()
            else:
                path.write_bytes(b"user data")
            self.assert_refusal_unchanged(lambda: desk.prepare_remove(self.root, remove_unchanged_wiki=True))
            path.rmdir() if path.is_dir() else path.unlink()
        self.put("__llm-wiki/index.md", b"edited owned wiki")
        self.assert_refusal_unchanged(lambda: desk.prepare_remove(self.root))
        self.assert_refusal_unchanged(self.install_plan)

    def test_skill_user_extras_never_broad_deleted(self):
        self.install()
        user = self.put(".agents/skills/wiki-desk/user.txt", b"Unmanaged local user addition\n")
        desk.apply_plan(desk.prepare_remove(self.root))
        self.assertEqual(user.read_bytes(), b"Unmanaged local user addition\n")
        self.assertTrue(user.parent.is_dir())
        self.assertFalse((user.parent / "SKILL.md").exists())

    def test_first_preimage_receipt_cumulative_sync_format(self):
        self.install()
        receipt_before = desk._read_receipt(self.root, SKILL)
        source = self.root / "__llm-wiki/source-registry.md"
        source_preimage = receipt_before["owned_files"][source.relative_to(self.root).as_posix()]["preimage"]
        desk.apply_plan(desk.prepare_runtime_action(self.root, "sync", now="fixed"))
        self.put("__llm-wiki/user.md", b"User body\n", 0o600)
        first_user = (self.root / "__llm-wiki/user.md").read_bytes()
        plan = desk.prepare_runtime_action(self.root, "format", now="fixed")
        before = tree(self.root)
        desk.validate_plan(plan)
        self.assertEqual(before, tree(self.root))
        desk.apply_plan(plan)
        receipt = desk._read_receipt(self.root, SKILL)
        key = "__llm-wiki/source-registry.md"
        self.assertEqual(receipt["owned_files"][key]["preimage"], source_preimage)
        user_preimage = receipt["owned_files"]["__llm-wiki/user.md"]["preimage"]
        self.assertEqual(base64.b64decode(user_preimage["bytes_base64"]), first_user)
        self.assertEqual(user_preimage["mode"], 0o600)
        fixed = tree(self.root)
        second = desk.prepare_runtime_action(self.root, "format", now="different")
        self.assertFalse(second.report["drift"])
        self.assertEqual(desk.apply_plan(second)["mutations"], 0)
        self.assertEqual(fixed, tree(self.root))
        self.assert_refusal_unchanged(lambda: desk.prepare_remove(self.root, remove_unchanged_wiki=True))

    def test_sync_format_source_snapshot_and_wiki_drift_all_before_write(self):
        self.install()
        for action in ("sync", "format"):
            with self.subTest(action=action):
                # Sync is not a format repair. Use structurally valid input so
                # this case reaches the drift guard rather than false-PASS.
                self.put("__llm-wiki/user.md", b"---\ntype: Reference\n---\nplain body\n")
                plan = desk.prepare_runtime_action(self.root, action, now="fixed")
                self.put("docs/source.md", b"source changes after planning")
                self.assert_refusal_unchanged(lambda: desk.apply_plan(plan))
                self.put("docs/source.md", b"Original project source, never copied into wiki.\n")
                plan = desk.prepare_runtime_action(self.root, action, now="fixed")
                self.put("__llm-wiki/user.md", b"wiki changes after planning")
                self.assert_refusal_unchanged(lambda: desk.apply_plan(plan))

    def test_new_runtime_output_dirs_are_bound_and_rollback_then_full_inverse(self):
        initial = tree(self.root)
        self.install()
        installed = tree(self.root)
        def output(root, contract, now=None):
            return self.runtime.plan_result(root, contract, {
                "__llm-wiki/generated/nested/new.md": b"---\ntype: Reference\n---\nNew managed generated document\n"})
        with patch.object(self.runtime, "sync_plan", side_effect=output):
            plan = desk.prepare_runtime_action(self.root, "sync", now="fixed")
            total = len(plan.transaction.writes) + len(plan.transaction.mkdirs)
            for failing in range(1, total + 1):
                with self.subTest(failing=failing):
                    def fault(count, rel):
                        if count == failing:
                            raise RuntimeError("injected new runtime directory")
                    with self.assertRaisesRegex(RuntimeError, "injected new runtime directory"):
                        desk.apply_plan(desk.prepare_runtime_action(self.root, "sync", now="fixed"), fault=fault)
                    self.assertEqual(installed, tree(self.root))
            self.assertTrue(desk.apply_plan(plan)["readback_verified"])
        receipt = desk._read_receipt(self.root, SKILL)
        self.assertEqual(receipt["owned_files"]["__llm-wiki/generated/nested/new.md"]["preimage"], {"kind": "missing"})
        desk.apply_plan(desk.prepare_remove(self.root, remove_unchanged_wiki=True))
        self.assertEqual(initial, tree(self.root))

    def test_sync_format_exception_rolls_back_output_and_receipt(self):
        self.install()
        self.put("__llm-wiki/user.md", b"---\ntype: Reference\n---\nplain user body [source-registry](/source-registry.md)\n", 0o600)
        original = tree(self.root)
        for action in ("sync", "format"):
            plan = desk.prepare_runtime_action(self.root, action, now="fixed")
            # Fixture writes only existing regular files and the existing receipt.
            self.assertFalse(plan.transaction.mkdirs)
            for failing in range(1, len(plan.transaction.writes) + 1):
                with self.subTest(action=action, failing=failing):
                    def fault(count, rel):
                        if count == failing:
                            raise RuntimeError("injected runtime action")
                    with self.assertRaisesRegex(RuntimeError, "injected runtime action"):
                        desk.apply_plan(desk.prepare_runtime_action(self.root, action, now="fixed"), fault=fault)
                    self.assertEqual(original, tree(self.root))

    def test_remove_after_skill_only_can_later_full_inverse(self):
        original = tree(self.root)
        self.install()
        desk.apply_plan(desk.prepare_remove(self.root))
        desk.apply_plan(desk.prepare_remove(self.root, remove_unchanged_wiki=True))
        self.assertEqual(original, tree(self.root))

    def test_remove_fault_exact_rollback(self):
        self.install()
        original = tree(self.root)
        plan = desk.prepare_remove(self.root, remove_unchanged_wiki=True)
        total = len(plan.transaction.deletes) + len(plan.transaction.rmdirs)
        for failing in range(1, total + 1):
            def fault(count, rel):
                if count == failing:
                    raise RuntimeError("injected remove")
            with self.assertRaisesRegex(RuntimeError, "injected remove"):
                desk.apply_plan(desk.prepare_remove(self.root, remove_unchanged_wiki=True), fault=fault)
            self.assertEqual(original, tree(self.root))

    def test_status_owned_symlink_refusal_writezero(self):
        self.install()
        file = self.root / "__llm-wiki/index.md"
        file.unlink()
        file.symlink_to(self.root / "docs/source.md")
        self.assert_refusal_unchanged(lambda: desk.status(self.root))

    def test_receipt_scope_forgery_cannot_delete_context(self):
        self.install()
        receipt = desk._read_receipt(self.root, SKILL)
        receipt["owned_files"]["HERMES.md"] = {**desk._file_record((self.root / "HERMES.md").read_bytes(), 0o644),
                                                "preimage": {"kind": "missing"}}
        self.put(desk.receipt_rel(SKILL), desk.json_bytes(receipt))
        self.assert_refusal_unchanged(lambda: desk.prepare_remove(self.root, remove_unchanged_wiki=True))

    def test_cli_exact_actions_errors_and_readonly_check_query_scan(self):
        self.install()
        before = tree(self.root)
        for argv in (("status", "--root", str(self.root)),
                     ("check", "--root", str(self.root)),
                     ("query", "--root", str(self.root), "--terms", "source"),
                     ("scan", "--root", str(self.root), "--contract", str(self.contract))):
            with self.subTest(argv=argv), redirect_stdout(io.StringIO()) as output:
                code = desk.main(list(argv))
                value = json.loads(output.getvalue())
                self.assertEqual(code, 0)
                self.assertEqual(value["writes"], 0)
                self.assertEqual(before, tree(self.root))
        for argv in (("sync",), ("query", "--root", str(self.root)),
                     ("format", "--root", str(self.root), "--check", "--apply"),
                     ("query", "--root", str(self.root), "--terms", "x", "--limit", "0"),
                     ("apply-plan", "external.json")):
            with self.subTest(argv=argv), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(desk.main(list(argv)), 2)
                self.assertEqual(json.loads(output.getvalue())["status"], "BLOCKED")
                self.assertEqual(before, tree(self.root))

    def test_format_check_nonzero_drift_and_no_apply(self):
        self.install()
        self.put("__llm-wiki/plain.md", b"needs formatting\n")
        before = tree(self.root)
        with redirect_stdout(io.StringIO()) as output:
            result = desk.main(["format", "--root", str(self.root), "--check"])
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(output.getvalue())["status"], "DRIFT")
        self.assertEqual(before, tree(self.root))

    def test_runtime_fixture_false_pass_reports_fail_closed(self):
        self.install()
        valid = self.runtime.format_plan(self.root, self.config, now="fixed")
        import copy
        invalid = []
        missing = copy.deepcopy(valid)
        del missing["report"]
        invalid.append(("missing-report", missing))
        for key, value in (("error_count", 1), ("error_count", False),
                           ("preservation_complete", False), ("preservation_complete", "true"),
                           ("snapshot_unchanged", False), ("source_snapshot_unchanged", False),
                           ("coverage_complete", False), ("conformant", False),
                           ("expected", 99), ("unique", 1), ("final_unique", 1),
                           ("file_count", 99), ("source_count", 99)):
            result = copy.deepcopy(valid)
            result["report"][key] = value
            invalid.append((key + "=" + repr(value), result))
        result = copy.deepcopy(valid)
        result["report"]["coverage"]["complete"] = False
        invalid.append(("coverage-incomplete", result))
        result = copy.deepcopy(valid)
        result["report"]["files"].append(result["report"]["files"][0])
        invalid.append(("duplicate-row", result))
        for label, result in invalid:
            for option in ("--check", "--apply"):
                with self.subTest(label=label, option=option):
                    before = tree(self.root)
                    with patch.object(self.runtime, "format_plan", return_value=result), redirect_stdout(io.StringIO()) as out:
                        code = desk.main(["format", "--root", str(self.root), option])
                    self.assertEqual(code, 2)
                    self.assertEqual(json.loads(out.getvalue())["status"], "BLOCKED")
                    self.assertEqual(before, tree(self.root))

    def test_runtime_without_source_policy_never_falls_back_to_secret_reads(self):
        self.put("docs/.env", b"SYNTHETIC SECRET\n")
        with patch.object(self.runtime, "source_exclusions", None):
            self.assert_refusal_unchanged(self.install_plan)

    def test_friendly_missing_pyyaml_without_install_attempt(self):
        self.mock.stop()
        with patch.object(desk.importlib, "import_module", side_effect=ModuleNotFoundError("No module named yaml", name="yaml")):
            with self.assertRaisesRegex(fs.SafetyError, "PyYAML prerequisite missing"):
                desk._runtime()
        self.mock.start()


if __name__ == "__main__":
    unittest.main()
