"""Scoped filesystem transactions, for a single cooperating writer.

Every precondition is checked before the first mutation. Atomic replacement is
per file, NOT whole-transaction OS/process-crash atomicity. Python exceptions
(including KeyboardInterrupt) roll back bytes, modes and created directories.
No concurrent hostile writer or process termination guarantee is made.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
from dataclasses import dataclass
from typing import Callable, Iterable


class SafetyError(ValueError):
    """Refusal before mutation, or a failed transaction with rollback."""


def safe_relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise SafetyError(f"Unsafe relative path: {value!r}")
    p = PurePosixPath(value)
    if p.is_absolute() or any(x in ("", ".", "..") for x in value.split("/")):
        raise SafetyError(f"Unsafe relative path: {value!r}")
    if str(p) != value or ":" in p.parts[0]:
        raise SafetyError(f"Noncanonical relative path: {value!r}")
    return value


def canonical_root(value: str | Path) -> Path:
    raw = Path(value).expanduser()
    if ".." in raw.parts:
        raise SafetyError("Root may not contain '..'")
    root = Path(os.path.abspath(raw))
    if root == Path(root.anchor):
        raise SafetyError("Filesystem root is not a project root")
    cursor = Path(root.anchor)
    for part in root.parts[1:]:
        cursor /= part
        try:
            mode = cursor.lstat().st_mode
        except FileNotFoundError as exc:
            raise SafetyError(f"Project root must already exist: {root}") from exc
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise SafetyError(f"Non-directory or symlink root/ancestor: {cursor}")
    return root


def safe_path(root: Path, relative: str, *, allow_root: bool = False) -> Path:
    root = canonical_root(root)
    if relative == "." and allow_root:
        return root
    safe_relative(relative)
    cursor = root
    parts = PurePosixPath(relative).parts
    for i, part in enumerate(parts):
        cursor /= part
        try:
            mode = cursor.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise SafetyError(f"Symlink refused: {cursor}")
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise SafetyError(f"Special file refused: {cursor}")
        if i != len(parts) - 1 and not stat.S_ISDIR(mode):
            raise SafetyError(f"Non-directory ancestor: {cursor}")
    return cursor


def read_regular(root: Path, relative: str) -> bytes:
    path = safe_path(root, relative)
    if not path.is_file():
        raise SafetyError(f"Expected regular file: {relative}")
    # Do not follow a final symlink even if another writer breaks the assumption.
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise SafetyError(f"Expected regular file: {relative}")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return stream.read()
    finally:
        os.close(fd)


@dataclass(frozen=True)
class Node:
    kind: str
    mode: int = 0
    sha256: str = ""
    size: int = 0
    children: tuple[str, ...] = ()


def node(root: Path, relative: str) -> Node:
    path = safe_path(root, relative, allow_root=True)
    try:
        st = path.lstat()
    except FileNotFoundError:
        return Node("missing")
    mode = stat.S_IMODE(st.st_mode)
    if stat.S_ISDIR(st.st_mode):
        return Node("dir", mode, children=tuple(sorted(p.name for p in path.iterdir())))
    data = read_regular(root, relative)
    return Node("file", mode, hashlib.sha256(data).hexdigest(), len(data))


@dataclass(frozen=True)
class Snapshot:
    root: Path
    scopes: tuple[str, ...]
    excludes: tuple[str, ...]
    entries: tuple[tuple[str, Node], ...]

    def as_dict(self) -> dict[str, Node]:
        return dict(self.entries)


def snapshot(root: Path, scopes: Iterable[str], *, excludes: Iterable[str] = ()) -> Snapshot:
    """Tree state in scopes plus nonrecursive parent directory states.

    Directory listings/modes are guarded; unrelated sibling file bodies (e.g.
    .env or .git data) are not read. Exclusions affect recursion, not safety of
    the selected root/ancestors. Root '.' is available for test/read snapshots.
    """
    root = canonical_root(root)
    scopes = tuple(sorted(set(scopes)))
    excludes = tuple(sorted(set(excludes)))
    for rel in scopes:
        if rel != ".":
            safe_relative(rel)
    for rel in excludes:
        safe_relative(rel)
    entries: dict[str, Node] = {}

    def excluded(rel: str) -> bool:
        return any(rel == e or rel.startswith(e + "/") for e in excludes)

    def walk(rel: str) -> None:
        if excluded(rel):
            return
        current = node(root, rel)
        entries[rel] = current
        if current.kind == "dir":
            for child in current.children:
                walk(child if rel == "." else rel + "/" + child)

    for rel in scopes:
        # Ancestor entries deliberately never recurse into unrelated siblings.
        parent = PurePosixPath(rel).parent
        while str(parent) != ".":
            entries[str(parent)] = node(root, str(parent))
            parent = parent.parent
        entries["."] = node(root, ".")
        walk(rel)
    return Snapshot(root, scopes, excludes, tuple(sorted(entries.items())))


def verify_snapshot(expected: Snapshot) -> None:
    if not isinstance(expected, Snapshot):
        raise SafetyError("Expected an in-memory Snapshot, not serialized input")
    actual = snapshot(expected.root, expected.scopes, excludes=expected.excludes)
    if actual != expected:
        before, after = expected.as_dict(), actual.as_dict()
        changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
        raise SafetyError("Baseline drift: " + ", ".join(changed[:20]))


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_bytes(path: Path, data: bytes, mode: int = 0o644) -> None:
    """Write/fsync/replace/fsync parent, cleaning up temporary bytes on failure."""
    if not isinstance(data, bytes):
        raise SafetyError("Atomic payload must be bytes")
    if type(mode) is not int or not 0 <= mode <= 0o777:
        raise SafetyError("Invalid atomic file mode")
    root = canonical_root(path.parent)
    path = safe_path(root, path.name)
    if path.exists() and not path.is_file():
        raise SafetyError("Atomic write destination is not a regular file")
    fd, temporary = tempfile.mkstemp(prefix=".wiki-desk-txn-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


@dataclass(frozen=True)
class Write:
    path: str
    data: bytes
    mode: int = 0o644


@dataclass(frozen=True)
class Transaction:
    root: Path
    baseline: Snapshot
    writes: tuple[Write, ...] = ()
    deletes: tuple[str, ...] = ()
    rmdirs: tuple[str, ...] = ()
    mkdirs: tuple[tuple[str, int], ...] = ()

    def preflight(self) -> None:
        root = canonical_root(self.root)
        if self.baseline.root != root:
            raise SafetyError("Baseline/root mismatch")
        verify_snapshot(self.baseline)
        seen: set[str] = set()
        records = self.baseline.as_dict()
        for write in self.writes:
            rel = safe_relative(write.path)
            if rel in seen or not isinstance(write.data, bytes):
                raise SafetyError("Duplicate path or nonbytes payload")
            if type(write.mode) is not int or write.mode < 0 or write.mode > 0o777:
                raise SafetyError("Invalid file mode")
            seen.add(rel)
            safe_path(root, rel)
            if node(root, rel).kind not in ("missing", "file"):
                raise SafetyError(f"Write/directory collision: {rel}")
        for rel in self.deletes:
            safe_relative(rel)
            if rel in seen or node(root, rel).kind != "file":
                raise SafetyError(f"Delete collision/nonfile: {rel}")
            seen.add(rel)
        if len(set(self.rmdirs)) != len(self.rmdirs):
            raise SafetyError("Duplicate directory removal")
        for rel in self.rmdirs:
            safe_relative(rel)
            if rel in seen or node(root, rel).kind != "dir":
                raise SafetyError(f"Directory removal collision: {rel}")
        if len(dict(self.mkdirs)) != len(self.mkdirs):
            raise SafetyError("Duplicate directory creation")
        for rel, mode in self.mkdirs:
            safe_relative(rel)
            if type(mode) is not int or not 0 <= mode <= 0o777:
                raise SafetyError("Invalid directory mode")
            current = node(root, rel)
            if rel in seen or current.kind not in ("missing", "dir"):
                raise SafetyError(f"Directory creation collision: {rel}")
            if current.kind == "dir" and current.mode != mode:
                raise SafetyError(f"Existing directory mode collision: {rel}")
        for rel in seen | set(self.rmdirs) | set(dict(self.mkdirs)):
            if rel not in records:
                # Existing guarded trees also bind absent future descendants:
                # the first missing component is absent from a snapshotted
                # directory listing. Parent listings do NOT authorize writes
                # into arbitrary sibling trees outside the explicit scopes.
                covered = any(scope == "." or rel == scope or rel.startswith(scope + "/")
                              for scope in self.baseline.scopes)
                excluded = any(rel == e or rel.startswith(e + "/") for e in self.baseline.excludes)
                missing_bound = False
                for parent in PurePosixPath(rel).parents:
                    ancestor = str(parent)
                    state = records.get(ancestor)
                    if state is None:
                        continue
                    if state.kind == "missing":
                        missing_bound = True
                        break
                    child = PurePosixPath(rel).relative_to(parent).parts[0]
                    if state.kind == "dir" and child not in state.children:
                        missing_bound = True
                        break
                if not covered or excluded or not missing_bound or node(root, rel).kind != "missing":
                    raise SafetyError(f"Mutation path not baseline-bound: {rel}")
        for rel, mode in self.mkdirs:
            if rel in set(self.rmdirs) or any(str(parent) in seen for parent in (PurePosixPath(rel), *PurePosixPath(rel).parents)):
                raise SafetyError(f"Directory/file mutation collision: {rel}")
            if any(rel == removed or rel.startswith(removed + "/") for removed in self.rmdirs):
                raise SafetyError("Cannot create beneath removed directory")
        for rel in seen:
            if any(p in seen for p in map(str, PurePosixPath(rel).parents)):
                raise SafetyError(f"File/ancestor mutation collision: {rel}")
        removals = set(self.rmdirs)
        for rel in self.rmdirs:
            for child in node(root, rel).children:
                childrel = rel + "/" + child
                if childrel not in set(self.deletes) | removals:
                    raise SafetyError(f"Nonempty/user directory would be removed: {rel}")
            if any(w.path.startswith(rel + "/") for w in self.writes):
                raise SafetyError("Cannot write beneath removed directory")

    def apply(self, *, fault: Callable[[int, str], None] | None = None,
              readback: Callable[[], None] | None = None) -> dict:
        """Whole preflight, then exception-safe owned mutations and readback.

        fault is a TEST hook invoked after every actual mkdir/write/unlink/rmdir.
        No hook is accepted by the CLI. Rollback uses its own noninjected path.
        """
        self.preflight()
        root = canonical_root(self.root)
        before: dict[str, tuple[Node, bytes | None]] = {}
        for rel in sorted({w.path for w in self.writes} | set(self.deletes) | set(self.rmdirs)):
            state = node(root, rel)
            before[rel] = (state, read_regular(root, rel) if state.kind == "file" else None)
        created: list[str] = []
        touched: list[str] = []
        count = 0

        def step(rel: str) -> None:
            nonlocal count
            count += 1
            if fault:
                fault(count, rel)

        def create_directory(rel: str, mode: int = 0o755) -> None:
            path = safe_path(root, rel)
            if not path.exists():
                path.mkdir(mode=mode)
                created.append(rel)
                path.chmod(mode)
                _fsync_dir(path.parent)
                step(rel)

        try:
            for rel, mode in sorted(self.mkdirs, key=lambda item: (item[0].count("/"), item[0])):
                for parent in reversed(PurePosixPath(rel).parents):
                    if str(parent) != ".":
                        create_directory(str(parent))
                create_directory(rel, mode)
            for write in sorted(self.writes, key=lambda w: w.path):
                parents = list(reversed(PurePosixPath(write.path).parents))
                for parent in parents:
                    if str(parent) != ".":
                        create_directory(str(parent))
                current = node(root, write.path)
                digest = hashlib.sha256(write.data).hexdigest()
                if current == Node("file", write.mode, digest, len(write.data)):
                    continue
                touched.append(write.path)
                atomic_bytes(safe_path(root, write.path), write.data, write.mode)
                step(write.path)
            for rel in sorted(self.deletes):
                touched.append(rel)
                path = safe_path(root, rel)
                path.unlink()
                _fsync_dir(path.parent)
                step(rel)
            for rel in sorted(self.rmdirs, key=lambda r: (-r.count("/"), r)):
                touched.append(rel)
                path = safe_path(root, rel)
                path.rmdir()
                _fsync_dir(path.parent)
                step(rel)
            # Readback failures also restore the complete preimage.
            for write in self.writes:
                expected = Node("file", write.mode, hashlib.sha256(write.data).hexdigest(), len(write.data))
                if node(root, write.path) != expected:
                    raise SafetyError(f"Write readback mismatch: {write.path}")
            for rel, mode in self.mkdirs:
                if node(root, rel).kind != "dir" or node(root, rel).mode != mode:
                    raise SafetyError(f"Directory readback mismatch: {rel}")
            for rel in self.deletes + self.rmdirs:
                if node(root, rel).kind != "missing":
                    raise SafetyError(f"Removal readback mismatch: {rel}")
            if readback:
                readback()
        except BaseException as original:
            errors: list[str] = []
            # Restore removed directories before file preimages.
            for rel in sorted(set(touched), key=lambda r: (r.count("/"), r)):
                state, _ = before[rel]
                if state.kind == "dir":
                    try:
                        path = safe_path(root, rel)
                        path.mkdir(mode=state.mode, exist_ok=True)
                        path.chmod(state.mode)
                    except BaseException as exc:
                        errors.append(f"{rel}: {exc}")
            for rel in reversed(touched):
                state, data = before[rel]
                try:
                    path = safe_path(root, rel)
                    if state.kind == "file":
                        assert data is not None
                        atomic_bytes(path, data, state.mode)
                    elif state.kind == "missing" and path.exists():
                        path.unlink()
                        _fsync_dir(path.parent)
                except BaseException as exc:
                    errors.append(f"{rel}: {exc}")
            for rel in reversed(created):
                try:
                    path = safe_path(root, rel)
                    path.rmdir()
                    _fsync_dir(path.parent)
                except BaseException as exc:
                    errors.append(f"{rel}: {exc}")
            try:
                verify_snapshot(self.baseline)
            except BaseException as exc:
                errors.append(f"rollback verification: {exc}")
            if errors:
                raise SafetyError("Rollback incomplete: " + "; ".join(errors)) from original
            raise
        return {"applied": True, "mutations": count, "readback_verified": True,
                "writes": sum(write.path in touched for write in self.writes),
                "deletes": len(self.deletes), "created_directories": len(created),
                "removed_directories": len(self.rmdirs),
                "single_writer_required": True, "process_crash_atomic": False}
