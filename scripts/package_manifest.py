"""Deterministic, exhaustive portable-package inventory (stdlib only).

Generate LAST after README/support/tests are frozen. Missing manifest is BLOCKED,
not a passing package check. This verifies content/closure, not publisher trust.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
import hashlib
import json
from pathlib import Path
import stat

from fs_safety import SafetyError, atomic_bytes, canonical_root, read_regular, safe_path

MANIFEST_NAME = "package-manifest.json"
ENTRYPOINTS = ("scripts/wiki_desk.py", "scripts/package_manifest.py")
REQUIRED_FILES = (
    "SKILL.md", "README.md", "LICENSE", "VERSION", "requirements.txt", "requirements-dev.txt",
    "scripts/fs_safety.py", "scripts/wiki_desk.py", "scripts/package_manifest.py",
    "scripts/wiki_runtime.py", "scripts/okf_bundle.py",
    "tests/test_lifecycle.py", "tests/test_runtime.py", "tests/test_okf_portable.py",
    "tests/test_privacy_policy.py", "tests/test_release_safety.py", "tests/test_state_layout.py",
    "tests/test_lifecycle_extensions.py", "tests/__init__.py",
    "tests/test_source_suffixes.py", "tests/test_reconciliation.py", "tests/test_portability.py",
    "assets/project-contract.example.json", "assets/project-contract.schema.json",
    "references/bootstrap.md", "references/okf.md", "references/authority.md",
    "references/installation.md", "references/maintenance.md", "references/external-sources.md",
)
CACHE_NAMES = frozenset(("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache"))
# Installed-skill operating state (project contract + lifecycle receipt). It is
# target-local, never package content: the package inventory excludes this
# top-level directory so an installed copy still verifies with its state inside.
STATE_DIR = "project"


class ManifestMissing(SafetyError):
    pass


def excluded(relative: str) -> bool:
    parts = Path(relative).parts
    return (relative == MANIFEST_NAME or ".git" in parts or (parts[:1] == (STATE_DIR,)) or
            any(p in CACHE_NAMES for p in parts) or relative.endswith((".pyc", ".pyo")))


def inventory(package: Path) -> dict:
    package = canonical_root(package)
    files: list[dict] = []
    directories: list[str] = []

    def walk(directory: Path) -> None:
        for path in sorted(directory.iterdir(), key=lambda p: p.name):
            rel = path.relative_to(package).as_posix()
            if excluded(rel):
                continue
            safe_path(package, rel)
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                directories.append(rel)
                walk(path)
            elif stat.S_ISREG(mode):
                data = read_regular(package, rel)
                files.append({"path": rel, "size": len(data),
                              "sha256": hashlib.sha256(data).hexdigest(),
                              "executable": bool(mode & 0o111)})
            else:
                raise SafetyError(f"Package special path refused: {rel}")
    walk(package)
    files.sort(key=lambda item: item["path"])
    return {"schema_version": 1, "entrypoints": list(ENTRYPOINTS),
            "file_count": len(files), "files": files, "directories": sorted(directories)}


def _closure(actual: dict) -> None:
    paths = {record["path"] for record in actual["files"]}
    missing = sorted(set(REQUIRED_FILES) - paths)
    if missing:
        raise SafetyError("Incomplete package closure: " + ", ".join(missing))
    if any(entry not in paths for entry in actual["entrypoints"]):
        raise SafetyError("Declared entrypoint is not inventory-bound")


def manifest_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def generate(package: Path) -> dict:
    package = canonical_root(package)
    actual = inventory(package)
    _closure(actual)
    path = safe_path(package, MANIFEST_NAME)
    if path.exists() and not path.is_file():
        raise SafetyError("Manifest destination is not a regular file")
    atomic_bytes(path, manifest_bytes(actual))
    # Generate is itself a state-changing package action; verify exact target.
    return verify(package)


def verify(package: Path) -> dict:
    package = canonical_root(package)
    if not safe_path(package, MANIFEST_NAME).is_file():
        raise ManifestMissing("Package manifest absent; generate last after package freeze")
    try:
        declared = json.loads(read_regular(package, MANIFEST_NAME))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise SafetyError(f"Invalid package manifest: {exc}") from exc
    actual = inventory(package)
    _closure(actual)
    if declared != actual:
        raise SafetyError("Package inventory drift or tampered manifest/entrypoints")
    return {"verified": True, "file_count": actual["file_count"],
            "entrypoints": actual["entrypoints"], "inventory": actual,
            "manifest_sha256": hashlib.sha256(read_regular(package, MANIFEST_NAME)).hexdigest(),
            "publisher_trust_verified": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("generate", "verify"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    try:
        result = generate(args.root) if args.action == "generate" else verify(args.root)
        result.pop("inventory", None)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (SafetyError, OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
