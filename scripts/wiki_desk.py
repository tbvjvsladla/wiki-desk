"""Portable wiki-desk CLI: local plans, explicit apply, scoped transactions.

The public actions never edit host/profile/context files. There is no
serialized-plan apply command. PreparedPlan is an in-process capability sealed
against payload/object tampering; validation re-runs the trusted builder before
any mutation. Single-writer operation is required. Whole-process-crash atomicity
is NOT provided. Status/hash checks do not establish semantic/user approval.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Callable, NoReturn
import weakref

from fs_safety import (Node, SafetyError, Snapshot, Transaction, Write,
                       canonical_root, node, read_regular, safe_path,
                       safe_relative, snapshot, verify_snapshot)
import package_manifest

# 1.0.x kept a project-root .wiki-desk/. Since 1.1 the operating state (project
# contract + lifecycle receipt) lives inside the installed skill, <skill>/project/,
# which the package inventory excludes. A leftover root admin dir is refused,
# never silently ignored, so two operating states can never disagree.
LEGACY_ADMIN = ".wiki-desk"
STATE = package_manifest.STATE_DIR
HOSTS = {"hermes": ".agents/skills/wiki-desk", "codex": ".agents/skills/wiki-desk",
         "claude": ".claude/skills/wiki-desk"}
RESERVED = frozenset((".git", ".hermes", ".agents", ".claude", LEGACY_ADMIN,
                      "HERMES.md", "AGENTS.md", "CLAUDE.md"))


def state_rel(skill: str) -> str:
    return skill + "/" + STATE


def contract_rel(skill: str) -> str:
    return state_rel(skill) + "/contract.json"


def receipt_rel(skill: str) -> str:
    return state_rel(skill) + "/receipt.json"


def _refuse_legacy(root: Path) -> None:
    if node(root, LEGACY_ADMIN).kind != "missing":
        raise SafetyError("Legacy 1.0.x root .wiki-desk/ present; migrate it first "
                          "(references/maintenance.md) — refusing a second operating state")


def _installed_skill(root: Path) -> str:
    """Skill dir whose operating state this invocation manages.

    An installed copy manages itself. A source-package run must find exactly one
    installed state among the host destinations; zero or several are refused."""
    _refuse_legacy(root)
    here = Path(os.path.abspath(__file__)).parent.parent
    candidates = sorted(set(HOSTS.values()))
    for rel in candidates:
        if Path(os.path.abspath(root / rel)) == here:
            return rel
    found = [rel for rel in candidates if node(root, contract_rel(rel)).kind == "file"]
    if len(found) != 1:
        raise SafetyError(f"Expected exactly one installed wiki-desk state among {candidates}; found {found}")
    return found[0]


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _json(data: bytes) -> dict:
    def unique(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise SafetyError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    value = json.loads(data, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise SafetyError("Expected JSON object")
    return value


def _runtime():
    try:
        return importlib.import_module("wiki_runtime")
    except ModuleNotFoundError as exc:
        if exc.name == "yaml":
            raise SafetyError("PyYAML prerequisite missing (requires PyYAML 6); no automatic install") from exc
        raise SafetyError(f"Runtime prerequisite missing: {exc.name}; package closure required") from exc


def _external_file(path: Path) -> tuple[bytes, Snapshot]:
    if ".." in path.parts:
        raise SafetyError("Input path may not contain '..'")
    absolute = Path(path.absolute())
    root = canonical_root(absolute.parent)
    data = read_regular(root, absolute.name)
    return data, snapshot(root, (absolute.name,))


def _contract(root: Path, skill: str) -> dict:
    raw = _json(read_regular(root, contract_rel(skill)))
    # Use the new planned API only; no private-wiki repository APIs.
    return _runtime().validate_contract(raw, root)


def _layout(root: Path, contract: dict, host: str) -> tuple[str, str]:
    if host not in HOSTS:
        raise SafetyError("Unsupported host adapter")
    wiki = safe_relative(contract["wiki_dir"])
    if any(part in RESERVED for part in PurePosixPath(wiki).parts):
        raise SafetyError("Wiki may not occupy host/admin/context paths")
    skill = HOSTS[host]
    for rel in (wiki, skill):
        safe_path(root, rel)
    return wiki, skill


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _source_snapshot(root: Path, contract: dict) -> Snapshot:
    # One authoritative no-read policy; never fall back to a broader snapshot
    # when an old runtime/fixture lacks the shared API. Prune before node/open.
    policy = getattr(_runtime(), "source_exclusions", None)
    if not callable(policy):
        raise SafetyError("Runtime source_exclusions API required; source reads refused")
    return snapshot(root, tuple(contract["source_roots"]), excludes=policy(root, contract))


def _verify_source_snapshot(expected: Snapshot, contract: dict) -> None:
    # Exclusions are filesystem-derived: re-enumerate before hashing, otherwise
    # a newly created .env/secret subtree would be opened by a stale excludes
    # tuple before generic verification could report membership drift.
    if _source_snapshot(expected.root, contract) != expected:
        raise SafetyError("Source baseline/policy membership drift")


def _baseline(root: Path, wiki: str, skill: str) -> Snapshot:
    return snapshot(root, (wiki, skill))


def _file_record(data: bytes, mode: int) -> dict:
    return {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "mode": mode}


def _owned_matches(actual: Node, record: dict) -> bool:
    # Ownership follows Git's portable content/executable semantics. Transaction
    # snapshots/readback still compare every permission bit exactly.
    return (actual.kind == "file" and actual.sha256 == record["sha256"]
            and actual.size == record["size"]
            and bool(actual.mode & 0o111) == bool(record["mode"] & 0o111))


def _preimage(root: Path, rel: str) -> dict:
    state = node(root, rel)
    if state.kind == "missing":
        return {"kind": "missing"}
    if state.kind != "file":
        raise SafetyError(f"Owned write requires regular-file preimage: {rel}")
    return {"kind": "file", "mode": state.mode,
            "bytes_base64": base64.b64encode(read_regular(root, rel)).decode("ascii")}


def _parents(paths: list[str]) -> set[str]:
    return {str(p) for rel in paths for p in PurePosixPath(rel).parents if str(p) != "."}


def _payload(outputs: object, wiki: str) -> tuple[Write, ...]:
    if not isinstance(outputs, dict):
        raise SafetyError("Runtime plan outputs must be a project-relative bytes mapping")
    result = []
    for rel, data in outputs.items():
        safe_relative(rel)
        if not _under(rel, wiki) or rel == wiki or not isinstance(data, bytes):
            raise SafetyError(f"Runtime output escapes wiki or is not bytes: {rel!r}")
        result.append(Write(rel, data))
    return tuple(sorted(result, key=lambda write: write.path))


def _update_receipt(root: Path, receipt: dict, writes: tuple[Write, ...],
                    explicit_dirs: tuple[str, ...] = ()) -> dict:
    # Never replace first-apply preimages with a later sync/format baseline.
    value = _json(json_bytes(receipt))
    owned = value.setdefault("owned_files", {})
    # Writer ownership is not generated-only provenance. Once user bytes/mode
    # diverge from our last receipt, normalization must not launder them into
    # future deletion permission, even when the first preimage was missing.
    for rel, record in owned.items():
        if not _owned_matches(node(root, rel), record):
            record["protected_user_content"] = True
    for write in writes:
        previous = owned.get(write.path, {})
        first = previous.get("preimage")
        if first is None:
            first = _preimage(root, write.path)
        protected = previous.get("protected_user_content", False) or first["kind"] == "file"
        owned[write.path] = {**_file_record(write.data, write.mode), "preimage": first,
                             "protected_user_content": protected}
    directories = _parents([w.path for w in writes] + [receipt_rel(value["skill_dir"])]) | set(explicit_dirs)
    created = value.setdefault("created_dirs", {})
    for rel in sorted(directories):
        if node(root, rel).kind == "missing":
            created.setdefault(rel, 0o755)
    return value


def _read_receipt(root: Path, skill: str, *, legacy: bool = False) -> dict:
    contract_path = LEGACY_ADMIN + "/contract.json" if legacy else contract_rel(skill)
    receipt_path = LEGACY_ADMIN + "/receipt.json" if legacy else receipt_rel(skill)
    value = _json(read_regular(root, receipt_path))
    if value.get("schema_version") != 1 or value.get("host") not in HOSTS:
        raise SafetyError("Invalid lifecycle receipt")
    contract = _json(read_regular(root, contract_path))
    wiki, layout_skill = _layout(root, contract, value["host"])
    if value.get("wiki_dir") != wiki or value.get("skill_dir") != layout_skill or layout_skill != skill:
        raise SafetyError("Receipt layout differs from local contract/host")
    if value.get("contract_sha256") != hashlib.sha256(read_regular(root, contract_path)).hexdigest():
        raise SafetyError("Local contract differs from receipt")
    owned = value.get("owned_files")
    created = value.get("created_dirs")
    if not isinstance(owned, dict) or not isinstance(created, dict):
        raise SafetyError("Invalid receipt ownership records")
    ancestors = _parents([wiki + "/_", skill + "/_", receipt_path])
    for rel, record in owned.items():
        safe_relative(rel)
        if not (rel == contract_path or _under(rel, wiki) or _under(rel, skill)) or rel in (wiki, skill, receipt_path):
            raise SafetyError(f"Receipt ownership escapes managed scope: {rel}")
        if (not isinstance(record, dict) or not isinstance(record.get("sha256"), str)
                or len(record["sha256"]) != 64 or type(record.get("size")) is not int
                or type(record.get("mode")) is not int or not 0 <= record["mode"] <= 0o777):
            raise SafetyError(f"Invalid owned-file record: {rel}")
        if "protected_user_content" in record and type(record["protected_user_content"]) is not bool:
            raise SafetyError(f"Invalid protected-user-content flag: {rel}")
        preimage = record.get("preimage", {})
        if not isinstance(preimage, dict) or preimage.get("kind") not in ("missing", "file"):
            raise SafetyError("Invalid first-apply preimage")
        if preimage["kind"] == "file":
            base64.b64decode(preimage["bytes_base64"], validate=True)
            if type(preimage.get("mode")) is not int or not 0 <= preimage["mode"] <= 0o777:
                raise SafetyError("Invalid preimage mode")
    for rel, mode in created.items():
        safe_relative(rel)
        if rel not in ancestors and not (_under(rel, wiki) or _under(rel, skill)):
            raise SafetyError("Receipt directory escapes managed scope")
        if mode != 0o755:
            raise SafetyError("Invalid created-directory mode")
    return value


def _owned_drift(root: Path, receipt: dict) -> list[str]:
    changed = []
    for rel, record in receipt["owned_files"].items():
        actual = node(root, rel)
        if not _owned_matches(actual, record):
            changed.append(rel)
    return sorted(changed)


@dataclass(frozen=True, eq=False)
class PreparedPlan:
    """In-memory only. Object construction alone confers no apply capability."""
    action: str
    transaction: Transaction
    guards: tuple[Snapshot, ...]
    report: dict
    # The last guard of source-bearing plans is their source snapshot. Bind its
    # exact shared policy to the seal, in immutable bytes rather than a dict.
    source_contract: bytes | None = None


@dataclass(frozen=True)
class _Seal:
    fingerprint: str
    recipe: Callable[[], PreparedPlan]
    readback: Callable[[], None] | None


_SEALS: weakref.WeakKeyDictionary[PreparedPlan, _Seal] = weakref.WeakKeyDictionary()


def _fingerprint(plan: PreparedPlan) -> str:
    # Snapshot dataclasses/bytes are immutable; report and forcibly replaced
    # frozen fields are included in the original in-memory seal.
    return hashlib.sha256(repr((plan.action, plan.transaction, plan.guards,
                               json_bytes(plan.report), plan.source_contract)).encode("utf-8")).hexdigest()


def _prepare(recipe: Callable[[], PreparedPlan],
             readback: Callable[[], None] | None = None) -> PreparedPlan:
    plan = recipe()
    _SEALS[plan] = _Seal(_fingerprint(plan), recipe, readback)
    return plan


def validate_plan(plan: PreparedPlan) -> None:
    if not isinstance(plan, PreparedPlan) or plan not in _SEALS:
        raise SafetyError("Only a registered trusted in-memory plan can be applied; serialized plans refused")
    seal = _SEALS[plan]
    if _fingerprint(plan) != seal.fingerprint:
        raise SafetyError("Plan payload/object tampering")
    # All source/package/contract/baseline checks happen before ANY mutation.
    def verify_guards() -> None:
        for index, guard in enumerate(plan.guards):
            if plan.source_contract is not None and index == len(plan.guards) - 1:
                _verify_source_snapshot(guard, _json(plan.source_contract))
            else:
                verify_snapshot(guard)
    verify_guards()
    plan.transaction.preflight()
    rebuilt = seal.recipe()
    if _fingerprint(rebuilt) != seal.fingerprint:
        raise SafetyError("Trusted planner recomputation differs (input/runtime/output drift)")
    # Reread guards after planner, which must itself be write-zero.
    verify_guards()
    plan.transaction.preflight()


def apply_plan(plan: PreparedPlan, *, fault: Callable[[int, str], None] | None = None) -> dict:
    validate_plan(plan)
    seal = _SEALS[plan]
    result = plan.transaction.apply(fault=fault, readback=seal.readback)
    return {**plan.report, **result, "status": "APPLIED" if result["mutations"] else "UNCHANGED"}


def _plan_report(action: str, transaction: Transaction, **fields: object) -> dict:
    return {"action": action, "status": "PLANNED", "applied": False, "writes": 0,
            "planned_writes": len(transaction.writes), "planned_deletes": len(transaction.deletes),
            "planned_rmdirs": len(transaction.rmdirs),
            "single_writer_required": True, "process_crash_atomic": False,
            "semantic_approval_verified": False, **fields}


def prepare_install(root: Path, host: str, contract_path: Path,
                    package: Path | None = None, *, now: str | None = None) -> PreparedPlan:
    root = canonical_root(root)
    package = canonical_root(package or Path(__file__).absolute().parent.parent)
    stamp = now or datetime.now(timezone.utc).isoformat()

    def build() -> PreparedPlan:
        raw, contract_guard = _external_file(contract_path)
        contract = _runtime().validate_contract(_json(raw), root)
        wiki, skill = _layout(root, contract, host)
        _refuse_legacy(root)
        # Source package must never overlap a managed destination.
        for rel in (wiki, skill):
            target = root / rel
            if package == target or target in package.parents or package in target.parents:
                raise SafetyError("Source-package/destination overlap")
        verified = package_manifest.verify(package)
        package_guard = snapshot(package, (".",), excludes=_package_exclusions(package))
        baseline = _baseline(root, wiki, skill)
        sources = _source_snapshot(root, contract)
        normalized = json_bytes(contract)
        existing = node(root, receipt_rel(skill)).kind == "file"
        if existing:
            receipt = _read_receipt(root, skill)
            if receipt["host"] != host or receipt.get("skill_removed"):
                raise SafetyError("Existing installation has different host or was removed")
            if (read_regular(root, contract_rel(skill)) != normalized or
                    receipt.get("package_manifest_sha256") != verified["manifest_sha256"]):
                raise SafetyError("Reinstall is byte-parity only; contract/package changed")
            drift = _owned_drift(root, receipt)
            if drift:
                raise SafetyError("Changed owned files: " + ", ".join(drift))
            for record in verified["inventory"]["files"] + [_manifest_record(package)]:
                source = read_regular(package, record["path"])
                dest = skill + "/" + record["path"]
                if read_regular(root, dest) != source or bool(node(root, dest).mode & 0o111) != record["executable"]:
                    raise SafetyError(f"Reinstall package byte-parity mismatch: {dest}")
            tx = Transaction(root, baseline)
            return PreparedPlan("install", tx, (contract_guard, package_guard, sources),
                                _plan_report("install", tx, idempotent=True, host=host, wiki_dir=wiki, skill_dir=skill),
                                source_contract=json_bytes(contract))
        if any(node(root, rel).kind != "missing" for rel in (wiki, skill)):
            raise SafetyError("Fresh install refuses existing wiki/skill/admin destination collisions")
        outputs = _runtime().scaffold_files(root, contract, now=stamp)
        writes = list(_payload(outputs, wiki))
        if not writes:
            raise SafetyError("Empty runtime scaffold")
        for record in verified["inventory"]["files"] + [_manifest_record(package)]:
            rel = record["path"]
            mode = 0o755 if record["executable"] else 0o644
            writes.append(Write(skill + "/" + rel, read_regular(package, rel), mode))
        writes.append(Write(contract_rel(skill), normalized))
        explicit_dirs = tuple(skill + "/" + rel for rel in verified["inventory"]["directories"])
        receipt = {"schema_version": 1, "host": host, "wiki_dir": wiki, "skill_dir": skill,
                   "contract_sha256": hashlib.sha256(normalized).hexdigest(),
                   "package_manifest_sha256": verified["manifest_sha256"],
                   "skill_removed": False, "single_writer_required": True,
                   "process_crash_atomic": False, "semantic_approval_verified": False}
        receipt = _update_receipt(root, receipt, tuple(writes), explicit_dirs)
        writes.append(Write(receipt_rel(skill), json_bytes(receipt)))
        tx = Transaction(root, baseline, tuple(sorted(writes, key=lambda w: w.path)),
                         mkdirs=tuple(sorted(receipt["created_dirs"].items())))
        tx.preflight()
        return PreparedPlan("install", tx, (contract_guard, package_guard, sources),
                            _plan_report("install", tx, idempotent=False, host=host, wiki_dir=wiki, skill_dir=skill,
                                         package_files=verified["file_count"] + 1), source_contract=json_bytes(contract))

    def readback() -> None:
        receipt = _read_receipt(root, HOSTS[host])
        if _owned_drift(root, receipt):
            raise SafetyError("Installed owned-file readback mismatch")
        package_manifest.verify(root / receipt["skill_dir"])
    return _prepare(build, readback)


def _package_exclusions(package: Path) -> tuple[str, ...]:
    return tuple(sorted(p.relative_to(package).as_posix() for p in package.rglob("*")
                        if package_manifest.excluded(p.relative_to(package).as_posix())
                        and p.relative_to(package).as_posix() != package_manifest.MANIFEST_NAME))


def _manifest_record(package: Path) -> dict:
    data = read_regular(package, package_manifest.MANIFEST_NAME)
    return {"path": package_manifest.MANIFEST_NAME, "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "executable": False}


def _new_receipt(host: str, wiki: str, skill: str, raw: bytes, verified: dict) -> dict:
    return {"schema_version": 1, "host": host, "wiki_dir": wiki, "skill_dir": skill,
            "contract_sha256": hashlib.sha256(raw).hexdigest(),
            "package_manifest_sha256": verified["manifest_sha256"],
            "skill_removed": False, "single_writer_required": True,
            "process_crash_atomic": False, "semantic_approval_verified": False}


def _package_writes(package: Path, skill: str, verified: dict) -> tuple[Write, ...]:
    return tuple(Write(skill + "/" + row["path"], read_regular(package, row["path"]),
                       0o755 if row["executable"] else 0o644)
                 for row in verified["inventory"]["files"] + [_manifest_record(package)])


def _register_existing(root: Path, receipt: dict, paths: tuple[str, ...], *, protected: bool) -> dict:
    for rel in paths:
        current = node(root, rel)
        if current.kind != "file":
            raise SafetyError(f"Expected existing regular file: {rel}")
        receipt.setdefault("owned_files", {})[rel] = {
            **_file_record(read_regular(root, rel), current.mode),
            "preimage": _preimage(root, rel), "protected_user_content": protected}
    return receipt


def _lifecycle_readback(root: Path, skill: str) -> None:
    receipt = _read_receipt(root, skill)
    if _owned_drift(root, receipt):
        raise SafetyError("Lifecycle owned-file readback mismatch")
    package_manifest.verify(root / skill)


def prepare_rebuild(root: Path, host: str, *, now: str | None = None) -> PreparedPlan:
    """Restore untracked wiki/receipt without rewriting a tracked checkout."""
    root = canonical_root(root)
    if host not in HOSTS:
        raise SafetyError("Unsupported host adapter")
    skill = HOSTS[host]
    stamp = now or datetime.now(timezone.utc).isoformat()

    def build() -> PreparedPlan:
        _refuse_legacy(root)
        raw = read_regular(root, contract_rel(skill))
        contract = _runtime().validate_contract(_json(raw), root)
        wiki, _ = _layout(root, contract, host)
        if set(node(root, state_rel(skill)).children) != {"contract.json"}:
            raise SafetyError("Rebuild requires contract-only operating state")
        if node(root, receipt_rel(skill)).kind != "missing" or node(root, wiki).kind != "missing":
            raise SafetyError("Rebuild requires absent receipt and wiki")
        verified = package_manifest.verify(root / skill)
        baseline = _baseline(root, wiki, skill)
        sources = _source_snapshot(root, contract)
        writes = _payload(_runtime().scaffold_files(root, contract, now=stamp), wiki)
        if not writes:
            raise SafetyError("Empty runtime scaffold")
        receipt = _new_receipt(host, wiki, skill, raw, verified)
        # Existing verified package and contract are not new deletion authority.
        paths = tuple(w.path for w in _package_writes(root / skill, skill, verified)) + (contract_rel(skill),)
        _register_existing(root, receipt, paths, protected=False)
        receipt = _update_receipt(root, receipt, writes)
        tx = Transaction(root, baseline, writes + (Write(receipt_rel(skill), json_bytes(receipt)),),
                         mkdirs=tuple(sorted(receipt["created_dirs"].items())))
        tx.preflight()
        return PreparedPlan("rebuild", tx, (sources,), _plan_report("rebuild", tx, host=host,
                            wiki_dir=wiki, skill_dir=skill, tracked_package_preserved=True),
                            source_contract=json_bytes(contract))
    return _prepare(build, lambda: _lifecycle_readback(root, skill))


def prepare_adopt(root: Path, host: str, contract_path: Path, package: Path | None = None) -> PreparedPlan:
    """Register an arbitrary existing wiki without normalizing any of its bytes."""
    root = canonical_root(root)
    package = canonical_root(package or Path(__file__).absolute().parent.parent)

    def build() -> PreparedPlan:
        _refuse_legacy(root)
        raw, contract_guard = _external_file(contract_path)
        contract = _runtime().validate_contract(_json(raw), root)
        wiki, skill = _layout(root, contract, host)
        if node(root, wiki).kind != "dir" or node(root, receipt_rel(skill)).kind != "missing":
            raise SafetyError("Adopt requires existing wiki directory and absent receipt")
        target = root / skill
        if package == root / wiki or root / wiki in package.parents or package in (root / wiki).parents:
            raise SafetyError("Source-package/wiki overlap")
        # Equality is intentional for adopting a verified existing install.
        # Proper overlap would write into (or over) the source distribution.
        if target in package.parents or package in target.parents:
            raise SafetyError("Source-package/destination overlap")
        verified = package_manifest.verify(package)
        package_guard = snapshot(package, (".",), excludes=_package_exclusions(package))
        baseline = _baseline(root, wiki, skill)
        writes: tuple[Write, ...] = ()
        receipt = _new_receipt(host, wiki, skill, raw, verified)
        directories = tuple(skill + "/" + rel for rel in verified["inventory"]["directories"])
        if node(root, skill).kind == "missing":
            writes = _package_writes(package, skill, verified)
        elif node(root, skill).kind == "dir":
            existing = package_manifest.verify(target)
            if existing["manifest_sha256"] != verified["manifest_sha256"]:
                raise SafetyError("Adopt refuses nonmatching installed package")
            _register_existing(root, receipt, tuple(w.path for w in _package_writes(target, skill, existing)), protected=False)
            state = node(root, state_rel(skill))
            if state.kind == "dir" and set(state.children) - {"contract.json"}:
                raise SafetyError("Adopt refuses colliding/extra operating state")
        else:
            raise SafetyError("Adopt skill destination collision")
        if node(root, contract_rel(skill)).kind == "missing":
            writes += (Write(contract_rel(skill), raw),)
        elif read_regular(root, contract_rel(skill)) == raw:
            _register_existing(root, receipt, (contract_rel(skill),), protected=False)
        else:
            raise SafetyError("Adopt contract collision")
        wiki_files = tuple(rel for rel, state in baseline.entries if _under(rel, wiki) and state.kind == "file")
        _register_existing(root, receipt, wiki_files, protected=True)
        receipt = _update_receipt(root, receipt, writes, directories)
        tx = Transaction(root, baseline, writes + (Write(receipt_rel(skill), json_bytes(receipt)),),
                         mkdirs=tuple(sorted(receipt["created_dirs"].items())))
        tx.preflight()
        return PreparedPlan("adopt", tx, (contract_guard, package_guard),
                            _plan_report("adopt", tx, host=host, wiki_dir=wiki, skill_dir=skill,
                                         wiki_preserved=True, protected_wiki_files=list(wiki_files)))
    return _prepare(build, lambda: _lifecycle_readback(root, HOSTS[host]))


def prepare_migrate_state(root: Path, host: str, package: Path | None = None) -> PreparedPlan:
    """Verified 1.0 package upgrade + state move; no wiki mutations/reinstall."""
    root = canonical_root(root)
    package = canonical_root(package or Path(__file__).absolute().parent.parent)
    if host not in HOSTS:
        raise SafetyError("Unsupported host adapter")
    skill = HOSTS[host]

    def build() -> PreparedPlan:
        legacy_contract = LEGACY_ADMIN + "/contract.json"
        legacy_receipt = LEGACY_ADMIN + "/receipt.json"
        if node(root, LEGACY_ADMIN).kind != "dir" or set(node(root, LEGACY_ADMIN).children) != {"contract.json", "receipt.json"}:
            raise SafetyError("Migration requires exact legacy admin contract/receipt; extra paths refused")
        if node(root, state_rel(skill)).kind != "missing":
            raise SafetyError("Migration operating-state collision")
        old = _read_receipt(root, skill, legacy=True)
        if old.get("skill_removed") or old["host"] != host:
            raise SafetyError("Migration requires a live matching-host legacy installation")
        raw = read_regular(root, legacy_contract)
        contract = _runtime().validate_contract(_json(raw), root)
        wiki, _ = _layout(root, contract, host)
        if node(root, wiki).kind != "dir":
            raise SafetyError("Migration requires existing wiki")
        target = root / skill
        if package == target or target in package.parents or package in target.parents:
            raise SafetyError("Migration requires a separate current source package")
        # Legacy closure predates added tests. Verify its entire original manifest,
        # and bind that manifest to the old receipt, not the new closure list.
        declared = _json(read_regular(target, package_manifest.MANIFEST_NAME))
        actual = package_manifest.inventory(target)
        old_hash = hashlib.sha256(read_regular(target, package_manifest.MANIFEST_NAME)).hexdigest()
        if (declared != actual or old.get("package_manifest_sha256") != old_hash
                or read_regular(target, "VERSION").strip() != b"1.0.0"):
            raise SafetyError("Migration requires verified unchanged legacy 1.0.0 package")
        package_paths = {skill + "/" + row["path"] for row in actual["files"]} | {skill + "/" + package_manifest.MANIFEST_NAME}
        owned_package = {rel for rel in old["owned_files"] if _under(rel, skill)}
        if owned_package != package_paths or any(not _owned_matches(node(root, rel), old["owned_files"][rel]) for rel in package_paths):
            raise SafetyError("Migration refuses changed/incomplete legacy package ownership")
        if any(old["owned_files"][rel].get("protected_user_content") for rel in package_paths):
            raise SafetyError("Migration refuses protected legacy package content")
        verified = package_manifest.verify(package)
        package_guard = snapshot(package, (".",), excludes=_package_exclusions(package))
        baseline = snapshot(root, (wiki, skill, LEGACY_ADMIN))
        writes = _package_writes(package, skill, verified) + (Write(contract_rel(skill), raw, node(root, legacy_contract).mode),)
        new_package = {w.path for w in writes if w.path != contract_rel(skill)}
        obsolete = package_paths - new_package
        # A removed old package file with an original user preimage must never be
        # erased during upgrade. Refuse rather than silently discard that record.
        if any(old["owned_files"][rel]["preimage"]["kind"] != "missing" for rel in obsolete):
            raise SafetyError("Migration refuses obsolete package user preimages")
        receipt = _json(json_bytes(old))
        receipt["package_manifest_sha256"] = verified["manifest_sha256"]
        receipt["owned_files"][contract_rel(skill)] = receipt["owned_files"].pop(legacy_contract)
        receipt["created_dirs"].pop(LEGACY_ADMIN, None)
        for rel in obsolete:
            del receipt["owned_files"][rel]
        # Mark live wiki drift sticky before moving state; do not normalize wiki.
        # Contract moved records compare at the old location until update finishes.
        contract_record = receipt["owned_files"].pop(contract_rel(skill))
        receipt = _update_receipt(root, receipt, tuple(w for w in writes if w.path != contract_rel(skill)),
                                  tuple(skill + "/" + rel for rel in verified["inventory"]["directories"]))
        receipt["owned_files"][contract_rel(skill)] = contract_record
        for rel in _parents([contract_rel(skill), receipt_rel(skill)]):
            if node(root, rel).kind == "missing":
                receipt["created_dirs"].setdefault(rel, 0o755)
        tx = Transaction(root, baseline, writes + (Write(receipt_rel(skill), json_bytes(receipt)),),
                         tuple(sorted(obsolete | {legacy_contract, legacy_receipt})), (LEGACY_ADMIN,),
                         tuple(sorted((rel, mode) for rel, mode in receipt["created_dirs"].items()
                                      if node(root, rel).kind == "missing")))
        tx.preflight()
        return PreparedPlan("migrate-state", tx, (package_guard,), _plan_report("migrate-state", tx,
                            host=host, wiki_dir=wiki, skill_dir=skill, wiki_preserved=True,
                            legacy_manifest_sha256=old_hash))
    # Existing wiki drift is intentionally preserved; package and state readback
    # remain verified, without claiming those user-edited wiki files are unchanged.
    def readback() -> None:
        _read_receipt(root, skill)
        package_manifest.verify(root / skill)
    return _prepare(build, readback)


def status(root: Path) -> dict:
    root = canonical_root(root)
    receipt = _read_receipt(root, _installed_skill(root))
    changed = _owned_drift(root, receipt)
    protected = sorted(rel for rel, record in receipt["owned_files"].items()
                       if record.get("protected_user_content", False))
    return {"action": "status", "status": "DRIFT" if changed else "PRESENT",
            "installed": not receipt.get("skill_removed"), "host": receipt["host"],
            "wiki_dir": receipt["wiki_dir"], "skill_dir": receipt["skill_dir"],
            "owned_files": len(receipt["owned_files"]), "changed_owned_files": changed,
            "protected_user_files": protected,
            "full_fresh_inverse_allowed": not changed and not protected and all(
                record["preimage"]["kind"] == "missing" for rel, record in receipt["owned_files"].items()
                if _under(rel, receipt["wiki_dir"])),
            "read_only": True, "writes": 0, "regular_owned_paths_checked": True,
            "semantic_approval_verified": False, "host_live_discovery_verified": False}


def _removable_dirs(root: Path, candidates: set[str], deletes: set[str]) -> tuple[str, ...]:
    selected: set[str] = set()
    for rel in sorted(candidates, key=lambda r: (-r.count("/"), r)):
        current = node(root, rel)
        if current.kind == "missing":
            continue
        if current.kind != "dir":
            raise SafetyError("Changed created directory: " + rel)
        if all(rel + "/" + child in deletes | selected for child in current.children):
            selected.add(rel)
    return tuple(sorted(selected))


def prepare_remove(root: Path, *, remove_unchanged_wiki: bool = False) -> PreparedPlan:
    root = canonical_root(root)

    def build() -> PreparedPlan:
        receipt = _read_receipt(root, _installed_skill(root))
        wiki, skill = receipt["wiki_dir"], receipt["skill_dir"]
        state = state_rel(skill)
        # Plain remove keeps the operating state (contract + receipt) like it keeps the wiki.
        def package_file(rel: str) -> bool:
            return _under(rel, skill) and not _under(rel, state)
        protected = sorted(rel for rel, record in receipt["owned_files"].items()
                           if record.get("protected_user_content", False)
                           and (remove_unchanged_wiki or package_file(rel)))
        if protected:
            raise SafetyError("Remove refuses protected user content without mutation: " + ", ".join(protected))
        baseline = _baseline(root, wiki, skill)
        drift = _owned_drift(root, receipt)
        if drift:
            raise SafetyError("Changed owned files; remove refuses without mutation: " + ", ".join(drift))
        for rel, expected_mode in receipt["created_dirs"].items():
            if node(root, rel).kind != "dir" or node(root, rel).mode != expected_mode:
                raise SafetyError("Changed managed directory: " + rel)
        owned = receipt["owned_files"]
        selected = {rel for rel in owned if package_file(rel)}
        writes: list[Write] = []
        if remove_unchanged_wiki:
            wiki_snapshot = snapshot(root, (wiki,)).as_dict()
            expected_wiki_files = {rel for rel in owned if _under(rel, wiki)}
            actual_files = {rel for rel, state in wiki_snapshot.items() if _under(rel, wiki) and state.kind == "file"}
            actual_dirs = {rel for rel, state in wiki_snapshot.items() if _under(rel, wiki) and state.kind == "dir"}
            expected_dirs = {rel for rel in receipt["created_dirs"] if _under(rel, wiki)}
            if actual_files != expected_wiki_files or actual_dirs != expected_dirs:
                raise SafetyError("Full fresh inverse refuses extra/unmanaged wiki user data or directories")
            if any(owned[rel]["preimage"]["kind"] != "missing" for rel in expected_wiki_files):
                raise SafetyError("Full fresh inverse refuses user-file preimages")
            selected.update(expected_wiki_files)
            selected.add(contract_rel(skill))
            selected.add(receipt_rel(skill))
        elif not receipt.get("skill_removed"):
            retained = _json(json_bytes(receipt))
            retained["skill_removed"] = True
            retained["owned_files"] = {rel: record for rel, record in owned.items() if rel not in selected}
            writes.append(Write(receipt_rel(skill), json_bytes(retained)))
        deletes = set()
        for rel in selected:
            preimage = owned.get(rel, {}).get("preimage", {"kind": "missing"})
            if preimage["kind"] == "missing":
                deletes.add(rel)
            else:
                writes.append(Write(rel, base64.b64decode(preimage["bytes_base64"], validate=True), preimage["mode"]))
        candidates = {rel for rel in receipt["created_dirs"]
                      if remove_unchanged_wiki or ((_under(rel, skill) and not _under(rel, state))
                                                 or rel in _parents([skill]))}
        rmdirs = _removable_dirs(root, candidates, deletes)
        if not remove_unchanged_wiki and writes:
            retained = _json(writes[0].data)
            retained["created_dirs"] = {rel: mode for rel, mode in receipt["created_dirs"].items() if rel not in rmdirs}
            writes[0] = Write(receipt_rel(skill), json_bytes(retained))
        tx = Transaction(root, baseline, tuple(writes), tuple(sorted(deletes)), rmdirs)
        tx.preflight()
        return PreparedPlan("remove", tx, (), _plan_report("remove", tx,
                            wiki_preserved=not remove_unchanged_wiki, full_fresh_inverse=remove_unchanged_wiki))
    return _prepare(build)


def _registry_preservation(core, before: str, after: str) -> dict:
    """Sync owns only the explicit registry listing, not surrounding user text."""
    old, body = core.parse_markdown(before)
    new, new_body = core.parse_markdown(after)
    start, end = '<!-- wiki-desk:source-registry:start -->', '<!-- wiki-desk:source-registry:end -->'
    def outside(text: str) -> tuple[str, str, bool]:
        if start not in text and end not in text:
            return text, '', False
        if text.count(start) != 1 or text.count(end) != 1 or text.index(start) >= text.index(end):
            raise SafetyError("Invalid registry generated block markers")
        prefix, rest = text.split(start, 1)
        return prefix, rest.split(end, 1)[1], True
    a, b, bounded = outside(body)
    c, d, new_bounded = outside(new_body)
    if before == after:
        return {"metadata_preserved": True, "body_preserved_except_normalization": True}
    body_ok = new_bounded and ((a == c and b == d) if bounded else
                              c.startswith(a) and not c[len(a):].strip('\r\n') and not d)
    return {"metadata_preserved": all(k in new and new[k] == v for k, v in old.items()),
            "body_preserved_except_normalization": bool(body_ok)}


def _validated_runtime_outputs(root: Path, contract: dict, action: str, runtime,
                               result: object, baseline: Snapshot, sources: Snapshot, *,
                               accept_removed: tuple[str, ...] = (),
                               relocations: tuple[tuple[str, str], ...] = (), now: str | None = None) -> dict:
    """Require native acceptance AND independently validate actual desired bytes.

    This gate runs before Write/receipt construction and again in the trusted
    recipe at apply. An all-true diagnostic report is not content evidence.
    """
    if not isinstance(result, dict) or not isinstance(result.get("report"), dict):
        raise SafetyError("Runtime plan requires an explicit acceptance report")
    report = result["report"]
    for key in ("error_count", "expected", "collected", "unique", "final_expected",
                "final_collected", "final_unique", "file_count", "source_count"):
        if type(report.get(key)) is not int or report[key] < 0:
            raise SafetyError(f"Runtime report requires nonnegative integer {key}")
    if report["error_count"] != 0:
        raise SafetyError(f"Runtime plan reports {report['error_count']} structural/preservation errors")
    for key in ("preservation_complete", "snapshot_unchanged", "source_snapshot_unchanged",
                "coverage_complete", "conformant"):
        if report.get(key) is not True:
            raise SafetyError(f"Runtime acceptance gate failed: {key}")
    coverage = report.get("coverage")
    if not isinstance(coverage, dict) or coverage.get("complete") is not True:
        raise SafetyError("Runtime report requires complete coverage")
    for key in ("expected", "collected", "unique"):
        if type(coverage.get(key)) is not int or coverage[key] != report[key]:
            raise SafetyError("Runtime coverage contradicts denominator")
    if not (0 < report["expected"] == report["collected"] == report["unique"] and
            report["final_expected"] == report["final_collected"] == report["final_unique"]):
        raise SafetyError("Runtime original/final denominator incomplete or nonunique")
    outputs = result.get("outputs")
    if not isinstance(outputs, dict):
        raise SafetyError("Runtime plan missing outputs mapping")
    wiki = contract["wiki_dir"]
    for rel, data in outputs.items():
        safe_relative(rel)
        if not _under(rel, wiki) or rel == wiki or not isinstance(data, bytes):
            raise SafetyError(f"Runtime output escapes wiki or is not bytes: {rel!r}")
    before = {rel: state for rel, state in baseline.entries if _under(rel, wiki) and state.kind == "file"}
    original_md = {rel for rel in before if rel.lower().endswith(".md")}
    final_md = {rel for rel in outputs if rel.lower().endswith(".md")}
    if (not original_md <= final_md or report["expected"] != len(original_md) or
            report["final_expected"] != len(final_md) or report["file_count"] != len(outputs)):
        raise SafetyError("Runtime output inventory contradicts actual original/final denominator")
    for key, expected in (("markdown_files", final_md), ("nonmarkdown_files", set(outputs) - final_md),
                          ("files", set(outputs))):
        rows = report.get(key)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise SafetyError(f"Runtime report requires {key} rows")
        paths = [row.get("path") for row in rows]
        if any(not isinstance(path, str) for path in paths) or len(set(paths)) != len(paths) or set(paths) != expected:
            raise SafetyError(f"Runtime {key} coverage is incomplete/duplicate")
        for row in rows:
            rel = row["path"]
            if (row.get("after_sha256") != hashlib.sha256(outputs[rel]).hexdigest() or
                    row.get("before_sha256") != (before[rel].sha256 if rel in before else None)):
                raise SafetyError(f"Runtime report not bound to actual before/output bytes: {rel}")
            issues = row.get("issues")
            if not isinstance(issues, list) or any(not isinstance(i, str) or i.startswith("error:") for i in issues):
                raise SafetyError(f"Runtime report contains invalid/error diagnostics: {rel}")
    source_hashes = {rel: state.sha256 for rel, state in sources.entries if state.kind == "file"}
    if result.get("source_snapshot") != source_hashes or report["source_count"] != len(source_hashes):
        raise SafetyError("Runtime source inventory differs from actual guarded source bytes")
    # Import the real content validator, not a unit fixture's conformance flag.
    core = importlib.import_module("okf_bundle")
    preserve = getattr(runtime, "preservation", None)
    if not callable(preserve):
        raise SafetyError("Runtime preservation API required")
    for rel in sorted(final_md):
        name = PurePosixPath(rel).relative_to(wiki).as_posix()
        text = outputs[rel].decode("utf-8")
        errors = [i for i in core.validate_markdown(root / wiki, name, text) if i.startswith("error:")]
        if errors:
            raise SafetyError(f"Actual runtime output invalid: {rel}: " + "; ".join(errors))
        if rel in before:
            old = read_regular(root, rel).decode("utf-8")
            guard = (_registry_preservation(core, old, text) if action == "sync" and name == "source-registry.md"
                     else preserve(old, text, root / wiki, name))
            if not isinstance(guard, dict) or any(guard.get(k) is not True for k in
                    ("metadata_preserved", "body_preserved_except_normalization")):
                raise SafetyError(f"Actual runtime output loses user metadata/body: {rel}")
    for rel in sorted(set(outputs) - final_md):
        if rel != wiki + "/source-registry.json":
            if rel not in before or read_regular(root, rel) != outputs[rel]:
                raise SafetyError(f"Runtime non-Markdown mutation is not registry-owned: {rel}")
            continue
        registry = _json(outputs[rel])
        if type(registry.get("schema_version")) is not int or registry["schema_version"] != 1 or not isinstance(registry.get("sources"), list):
            raise SafetyError("Actual registry output invalid")
        records = registry["sources"]
        if any(not isinstance(row, dict) or not isinstance(row.get("source_path"), str)
               or not isinstance(row.get("id"), str) for row in records):
            raise SafetyError("Actual registry output requires source identity/path records")
        if (len({row['source_path'] for row in records}) != len(records) or
                len({row['id'] for row in records}) != len(records) or
                {row['source_path']: row.get('sha256') for row in records} != source_hashes):
            raise SafetyError("Actual registry output source coverage/hash mismatch")
        if rel in before:
            previous = _json(read_regular(root, rel))
            validator = getattr(runtime, "validate_registry_transition", None)
            if callable(validator) or accept_removed or relocations:
                if action != "sync":
                    if accept_removed or relocations:
                        raise SafetyError("Registry transitions require sync")
                if not callable(validator):
                    raise SafetyError("Runtime registry-transition validator API required")
                if validator(previous, registry, accept_removed=accept_removed, relocations=relocations, now=now) is not True:
                    raise SafetyError("Runtime registry-transition validation did not pass")
                continue
            if {k: v for k, v in previous.items() if k != "sources"} != {k: v for k, v in registry.items() if k != "sources"}:
                raise SafetyError("Actual registry output loses producer metadata")
            indexed = {row['source_path']: row for row in records}
            owned_keys = {'source_path', 'sha256', 'title', 'document_type', 'authority_rank', 'role'}
            for row in previous.get('sources', []):
                current = indexed.get(row['source_path'], {})
                if any(k not in current or current[k] != v for k, v in row.items() if k not in owned_keys):
                    raise SafetyError("Actual registry output loses source identity/extensions")
    verify_snapshot(baseline)
    _verify_source_snapshot(sources, contract)
    return outputs


def prepare_runtime_action(root: Path, action: str, *, now: str | None = None,
                           accept_removed=(), relocations=()) -> PreparedPlan:
    root = canonical_root(root)
    if action not in ("sync", "format"):
        raise SafetyError("Unsupported runtime mutation action")
    if isinstance(accept_removed, (str, bytes)) or isinstance(relocations, (str, bytes)):
        raise SafetyError("Transition options require path sequences and literal pairs")
    accept_removed = tuple(safe_relative(path) for path in accept_removed)
    pairs = tuple(relocations)
    if any(not isinstance(pair, (tuple, list)) or len(pair) != 2 for pair in pairs):
        raise SafetyError("Relocations require literal (OLD, NEW) pairs")
    relocations = tuple((safe_relative(old), safe_relative(new)) for old, new in pairs)
    if action != "sync" and (accept_removed or relocations):
        raise SafetyError("Transition options are sync-only")
    stamp = now or datetime.now(timezone.utc).isoformat()

    def build() -> PreparedPlan:
        receipt = _read_receipt(root, _installed_skill(root))
        wiki, skill = receipt["wiki_dir"], receipt["skill_dir"]
        contract = _contract(root, skill)
        baseline = _baseline(root, wiki, skill)
        sources = _source_snapshot(root, contract)
        runtime = _runtime()
        kwargs = {"accept_removed": accept_removed, "relocations": relocations} if action == "sync" and (accept_removed or relocations) else {}
        result = getattr(runtime, action + "_plan")(root, contract, now=stamp, **kwargs)
        outputs = _validated_runtime_outputs(root, contract, action, runtime, result, baseline, sources,
                                             accept_removed=accept_removed, relocations=relocations, now=stamp)
        # Native baseline remains diagnostic; source inventory/report rows were
        # cross-checked against independent bytes. Rebuild the recipe at apply.
        writes = tuple(Write(write.path, write.data,
                             node(root, write.path).mode if node(root, write.path).kind == "file" else write.mode)
                       for write in _payload(outputs, wiki))
        changed = tuple(w for w in writes if node(root, w.path) !=
                        Node("file", w.mode, hashlib.sha256(w.data).hexdigest(), len(w.data)))
        all_writes = changed
        mkdirs: tuple[tuple[str, int], ...] = ()
        updated = _update_receipt(root, receipt, changed)
        if changed or updated != receipt:
            all_writes += (Write(receipt_rel(skill), json_bytes(updated)),)
            mkdirs = tuple(sorted((rel, mode) for rel, mode in updated["created_dirs"].items()
                                  if node(root, rel).kind == "missing"))
        tx = Transaction(root, baseline, tuple(sorted(all_writes, key=lambda w: w.path)), mkdirs=mkdirs)
        tx.preflight()
        diagnostics = {k: v for k, v in result.items() if k != "outputs"}
        # Runtime report may contain Path/bytes/dataclasses; do not serialize
        # guessed objects or rely on their boolean preservation claims.
        diagnostics = _public(diagnostics)
        return PreparedPlan(action, tx, (sources,), _plan_report(action, tx,
                            drift=bool(changed), changed_wiki_files=[w.path for w in changed],
                            runtime_report=diagnostics, actual_source_snapshot_guarded=True,
                            accept_removed=list(accept_removed), relocations=[list(pair) for pair in relocations]),
                            source_contract=json_bytes(contract))

    def readback() -> None:
        # Exact writes already verified by Transaction; each changed output is
        # also receipt-bound. Existing user changes outside outputs are allowed.
        skill = _installed_skill(root)
        receipt = _read_receipt(root, skill)
        for write in plan.transaction.writes:
            if write.path != receipt_rel(skill):
                record = receipt["owned_files"].get(write.path)
                if record is None or any(record.get(key) != value for key, value in _file_record(write.data, write.mode).items()):
                    raise SafetyError("Runtime output receipt readback mismatch")
    plan = _prepare(build, readback)
    return plan


def _public(value: object) -> object:
    if isinstance(value, bytes):
        return {"size": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _public(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_public(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import fields
        return _public({field.name: getattr(value, field.name) for field in fields(value)})  # type: ignore[arg-type]
    raise SafetyError(f"Unsupported runtime diagnostic type: {type(value).__name__}")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise SafetyError(message)


def parser() -> argparse.ArgumentParser:
    result = _Parser(description=__doc__)
    sub = result.add_subparsers(dest="action", required=True, parser_class=_Parser)
    sub.add_parser("verify-package")
    for action in ("install", "adopt", "rebuild", "migrate-state"):
        install = sub.add_parser(action)
        install.add_argument("--root", type=Path, required=True)
        install.add_argument("--host", choices=tuple(HOSTS), required=True)
        if action in ("install", "adopt"):
            install.add_argument("--contract", type=Path, required=True)
        install.add_argument("--apply", action="store_true")
    for action in ("status", "remove", "sync", "query", "format", "check", "scan"):
        command = sub.add_parser(action)
        command.add_argument("--root", type=Path, required=True)
        if action in ("remove", "sync", "format"):
            command.add_argument("--apply", action="store_true")
        if action == "remove":
            command.add_argument("--remove-unchanged-wiki", action="store_true")
        if action == "format":
            command.add_argument("--check", action="store_true")
        if action == "query":
            command.add_argument("--terms", required=True)
            command.add_argument("--limit", type=int, default=10)
            command.add_argument("--fail-on-empty", action="store_true")
        if action == "sync":
            command.add_argument("--accept-removed", action="append", default=[])
            command.add_argument("--relocate", action="append", default=[])
        if action == "scan":
            command.add_argument("--contract", type=Path, required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    action = None
    try:
        args = parser().parse_args(argv)
        action = args.action
        if action == "verify-package":
            result = package_manifest.verify(Path(__file__).absolute().parent.parent)
            result.pop("inventory", None)
            result.update(action=action, read_only=True, writes=0)
        elif action == "install":
            plan = prepare_install(args.root, args.host, args.contract)
            result = apply_plan(plan) if args.apply else plan.report
        elif action in ("adopt", "rebuild", "migrate-state"):
            if action == "adopt":
                plan = prepare_adopt(args.root, args.host, args.contract)
            elif action == "rebuild":
                plan = prepare_rebuild(args.root, args.host)
            else:
                plan = prepare_migrate_state(args.root, args.host)
            result = apply_plan(plan) if args.apply else plan.report
        elif action == "status":
            result = status(args.root)
        elif action == "remove":
            plan = prepare_remove(args.root, remove_unchanged_wiki=args.remove_unchanged_wiki)
            result = apply_plan(plan) if args.apply else plan.report
        elif action in ("sync", "format"):
            if action == "format" and args.check and args.apply:
                raise SafetyError("format --check cannot be combined with --apply")
            options = {}
            if action == "sync":
                pairs = []
                for value in args.relocate:
                    if value.count("=") != 1:
                        raise SafetyError("--relocate requires literal OLD=NEW")
                    old, new = value.split("=")
                    pairs.append((safe_relative(old), safe_relative(new)))
                options = {"accept_removed": tuple(args.accept_removed), "relocations": tuple(pairs)}
            plan = prepare_runtime_action(args.root, action, **options)
            result = apply_plan(plan) if args.apply else plan.report
            if action == "format" and args.check:
                result = {**result, "check": True, "status": "DRIFT" if result["drift"] else "CONFORMANT"}
                print(json.dumps(_public(result), ensure_ascii=False, sort_keys=True))
                return 1 if result["drift"] else 0
        elif action == "query":
            root = canonical_root(args.root)
            if args.limit <= 0:
                raise SafetyError("Query limit must be positive")
            result = _runtime().query(root, _contract(root, _installed_skill(root)), args.terms, limit=args.limit)
            result = {**result, "action": action, "read_only": True, "writes": 0}
            print(json.dumps(_public(result), ensure_ascii=False, sort_keys=True))
            return 3 if args.fail_on_empty and result.get("matched_count") == 0 else 0
        elif action == "check":
            root = canonical_root(args.root)
            result = _runtime().check_bundle(root, _contract(root, _installed_skill(root)))
            result = {**result, "action": action, "read_only": True, "writes": 0,
                      "semantic_approval_verified": False}
            print(json.dumps(_public(result), ensure_ascii=False, sort_keys=True))
            valid = bool(result.get("conformant")) and not result.get("error_count")
            valid = valid and result.get("snapshot_unchanged", True) is not False
            if all(key in result for key in ("expected", "collected", "unique")):
                valid = valid and result["expected"] == result["collected"] == result["unique"]
            return 0 if valid else 1
        elif action == "scan":
            root = canonical_root(args.root)
            raw, guard = _external_file(args.contract)
            contract = _runtime().validate_contract(_json(raw), root)
            sources = _source_snapshot(root, contract)
            wiki_state = node(root, contract["wiki_dir"])
            if wiki_state.kind not in ("missing", "dir"):
                raise SafetyError("Scan wiki destination is not a directory")
            wiki_exists = wiki_state.kind == "dir"
            outputs = () if wiki_exists else _payload(_runtime().scaffold_files(root, contract), contract["wiki_dir"])
            verify_snapshot(guard)
            _verify_source_snapshot(sources, contract)
            observed = [{"path": rel, "sha256": state.sha256, "size": state.size}
                        for rel, state in sources.entries if state.kind == "file"]
            result = {"action": action, "read_only": True, "writes": 0,
                      "source_files": observed, "source_count": len(observed),
                      "scaffold_paths": [w.path for w in outputs], "wiki_exists": wiki_exists, "originals_reviewed": False,
                      "semantic_approval_verified": False}
        else:
            raise SafetyError("Unsupported action")
        print(json.dumps(_public(result), ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        # No partially emitted non-JSON stdout/tracebacks. Failed transactions
        # have already attempted and verified whole-preimage rollback.
        print(json.dumps({"action": action, "status": "BLOCKED", "error": str(exc),
                          "error_type": type(exc).__name__, "applied": False}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
