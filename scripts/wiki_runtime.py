"""Portable, read-only wiki planning and original-source retrieval.

All paths in outputs/source_snapshot are PROJECT-relative. baseline is a
wiki-relative full snapshot (directory keys end in '/'). No function applies a
plan, copies source bodies, imports a producer, or creates package caches.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import copy
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
from urllib.parse import quote

import okf_bundle as core

__all__ = ['validate_contract', 'scaffold_files', 'sync_plan', 'query',
           'format_plan', 'check_bundle', 'read_contract', 'source_exclusions',
           'validate_registry_transition']
INDEX_START = '<!-- okf-directory-listing:start -->'
INDEX_END = '<!-- okf-directory-listing:end -->'
_REQUIRED = {'schema_version', 'project_name', 'wiki_dir', 'source_roots',
             'excluded_roots', 'authority_rules', 'fallback', 'copy_policy'}
_BLOCKED_PARTS = {'.git', '.wiki-desk', '.agents', '.claude', '.hermes', '.codex', '.ssh', '.aws',
                  '__pycache__', '.pytest_cache', '.cache', '.venv', 'venv',
                  'node_modules', 'secret', 'secrets', 'generated', 'build', 'dist'}
_SECRET_SUFFIXES = {'.pem', '.key', '.p12', '.pfx', '.keystore'}
_SOURCE_SUFFIX = re.compile(r'\.[A-Za-z0-9]+')
_RECORD_OWNED = {'id', 'source_path', 'sha256', 'title', 'document_type',
                 'authority_rank', 'role'}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _project(root: Path) -> Path:
    root = Path(os.path.abspath(os.fspath(root)))
    for part in [*reversed(root.parents), root]:
        if part.is_symlink():
            raise ValueError(f'unsafe symlink in project root: {part}')
    if not root.is_dir():
        raise ValueError('project root must be an existing directory')
    return root


def _relative(value, label: str, allow_dot=False) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f'{label}: explicit non-empty relative path required')
    if '\\' in value or ':' in value or any(ord(c) < 32 for c in value):
        raise ValueError(f'{label}: unsafe path spelling')
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or (not p.parts and not allow_dot):
        raise ValueError(f'{label}: absolute/escaping/empty path refused')
    if p.as_posix() != value:
        raise ValueError(f'{label}: canonical relative path required')
    return value


def _safe(root: Path, rel: str, exists=False) -> Path:
    _relative(rel, 'target path', allow_dot=True)
    path = root / rel
    current = root
    for part in PurePosixPath(rel).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f'unsafe symlink: {rel}')
        if current.exists() and not (current.is_file() or current.is_dir()):
            raise ValueError(f'nonregular path: {rel}')
    if exists and not path.exists():
        raise ValueError(f'missing path: {rel}')
    return path


def _below(path: str, parent: str) -> bool:
    return parent == '.' or path == parent or path.startswith(parent + '/')


def _rule(value, label: str, pattern=False):
    if not isinstance(value, dict):
        raise ValueError(f'{label}: mapping required')
    keys = {'document_type', 'authority_rank', 'role'} | ({'pattern'} if pattern else set())
    if keys - value.keys():
        raise ValueError(f'{label}: missing explicit keys: {sorted(keys - value.keys())}')
    for name in ('document_type', 'role'):
        if not isinstance(value[name], str) or not value[name].strip():
            raise ValueError(f'{label}.{name}: non-empty string required')
    if type(value['authority_rank']) is not int:
        raise ValueError(f'{label}.authority_rank: integer required')
    if pattern:
        p = value['pattern']
        if (not isinstance(p, str) or not p.strip() or p.startswith('/') or
                '\\' in p or ':' in p or '..' in PurePosixPath(p).parts or
                any(ord(c) < 32 for c in p)):
            raise ValueError(f'{label}.pattern: project-relative glob required')


def validate_contract(contract: dict, project_root: Path) -> dict:
    """Validate every required key, without filling policy defaults.

    Extension keys are retained. Existing empty document roots are allowed;
    missing document roots, symlink ancestors and wiki/control roots are not.
    Rule order is meaningful: first matched wins, rank sorts query results.
    """
    project = _project(project_root)
    if not isinstance(contract, dict) or _REQUIRED - contract.keys():
        raise ValueError('contract: all explicit schema keys are required')
    if type(contract['schema_version']) is not int or contract['schema_version'] != 1:
        raise ValueError('contract.schema_version: supported value is integer 1')
    if not isinstance(contract['project_name'], str) or not contract['project_name'].strip():
        raise ValueError('contract.project_name: non-empty string required')
    if contract['copy_policy'] != 'path_reference':
        raise ValueError('contract.copy_policy: only path_reference is supported')
    wiki = _relative(contract['wiki_dir'], 'wiki_dir')
    if any(part.casefold() in _BLOCKED_PARTS for part in PurePosixPath(wiki).parts):
        raise ValueError('wiki_dir cannot use reserved control/generated/secret paths')
    _safe(project, wiki)
    for key in ('source_roots', 'excluded_roots'):
        roots = contract[key]
        if not isinstance(roots, list) or (key == 'source_roots' and not roots):
            raise ValueError(f'{key}: explicit list required; source_roots cannot be empty')
        seen = set()
        for value in roots:
            _relative(value, key, allow_dot=key == 'source_roots')
            if value in seen:
                raise ValueError(f'{key}: duplicate root: {value}')
            seen.add(value)
            _safe(project, value, exists=key == 'source_roots')
            if key == 'source_roots' and (_below(value, wiki) or
                    any(p.casefold() in _BLOCKED_PARTS for p in PurePosixPath(value).parts)):
                raise ValueError(f'source root is excluded control/wiki/generated/secret: {value}')
    if 'source_suffixes' in contract:
        suffixes = contract['source_suffixes']
        if (not isinstance(suffixes, list) or not suffixes or
                any(not isinstance(s, str) or not _SOURCE_SUFFIX.fullmatch(s) for s in suffixes)):
            raise ValueError('source_suffixes: non-empty list of file suffixes such as ".md" required')
        if len({s.casefold() for s in suffixes}) != len(suffixes):
            raise ValueError('source_suffixes: duplicate suffix')
        for value in contract['source_roots']:
            if _safe(project, value, exists=True).is_file() and not _suffix_ok(value, contract):
                raise ValueError(f'source root file is outside source_suffixes: {value}')
    if not isinstance(contract['authority_rules'], list):
        raise ValueError('authority_rules: ordered list required')
    for i, rule in enumerate(contract['authority_rules']):
        _rule(rule, f'authority_rules[{i}]', pattern=True)
    _rule(contract['fallback'], 'fallback')
    return copy.deepcopy(contract)


def _json_load(data: bytes, label: str) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'{label}: duplicate JSON key: {key}')
            result[key] = value
        return result
    try:
        result = json.loads(data.decode('utf-8'), object_pairs_hook=pairs,
                            parse_constant=lambda s: (_ for _ in ()).throw(ValueError(f'nonfinite JSON: {s}')))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f'{label}: invalid JSON') from exc
    if not isinstance(result, dict):
        raise ValueError(f'{label}: object required')
    return result


def read_contract(project_root: Path, contract_path: str) -> dict:
    """Read an explicit project-relative contract, never a contract in the wiki."""
    project = _project(project_root)
    rel = _relative(contract_path, 'contract_path')
    path = _safe(project, rel, exists=True)
    if not path.is_file():
        raise ValueError('contract must be a regular file outside the wiki')
    contract = validate_contract(_json_load(path.read_bytes(), rel), project)
    if _below(rel, contract['wiki_dir']):
        raise ValueError('contract must be outside the wiki')
    return contract


def _snapshot(project: Path, wiki: str) -> dict[str, str]:
    bundle = _safe(project, wiki)
    if not bundle.exists():
        return {}
    if not bundle.is_dir():
        raise ValueError('wiki_dir must be a directory')
    result = {}
    for base, dirs, files in os.walk(bundle, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(base) / name
            rel = path.relative_to(bundle).as_posix()
            _safe(project, (PurePosixPath(wiki) / rel).as_posix(), exists=True)
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                result[rel + '/'] = 'directory'
            elif stat.S_ISREG(mode):
                result[rel] = _digest(path.read_bytes())
            else:
                raise ValueError(f'nonregular wiki entry: {rel}')
    return dict(sorted(result.items()))


def _excluded(rel: str, contract: dict) -> bool:
    parts = PurePosixPath(rel).parts
    name = parts[-1].casefold() if parts else ''
    return (_below(rel, contract['wiki_dir']) or
            any(_below(rel, p) for p in contract['excluded_roots']) or
            any(p.casefold() in _BLOCKED_PARTS for p in parts) or
            name == '.env' or name.startswith('.env.') or
            name in {'credentials', 'credentials.json', 'secrets.json', 'secrets.yaml', 'secrets.yml'} or
            PurePosixPath(name).suffix in _SECRET_SUFFIXES)


def _suffix_ok(rel: str, contract: dict) -> bool:
    """Absent policy retains all regular files; filtering never opens a body."""
    suffixes = contract.get('source_suffixes')
    return suffixes is None or PurePosixPath(rel).suffix.casefold() in {s.casefold() for s in suffixes}


def _walk_prefix(project: Path, base: str) -> str:
    """Compute the project-relative prefix once per walked directory."""
    rel = Path(base).relative_to(project).as_posix()
    return '' if rel == '.' else rel + '/'


def _paths(project: Path, contract: dict) -> list[str]:
    collected = set()
    for root in contract['source_roots']:
        path = _safe(project, root, exists=True)
        if path.is_file():
            if not _excluded(root, contract) and _suffix_ok(root, contract):
                collected.add(root)
            continue
        for base, dirs, files in os.walk(path, followlinks=False):
            prefix = _walk_prefix(project, base)
            retained = []
            for name in sorted(dirs):
                rel = prefix + name
                # Do not traverse excluded trees, but never hide a visible symlink.
                if os.path.islink(os.path.join(base, name)):
                    raise ValueError(f'unsafe source symlink: {rel}')
                if _excluded(rel, contract):
                    continue
                _safe(project, rel, exists=True)
                retained.append(name)
            dirs[:] = retained
            for name in sorted(files):
                rel = prefix + name
                if os.path.islink(os.path.join(base, name)):
                    raise ValueError(f'unsafe source symlink: {rel}')
                if _excluded(rel, contract) or not _suffix_ok(rel, contract):
                    continue
                candidate = _safe(project, rel, exists=True)
                if not candidate.is_file():
                    raise ValueError(f'nonregular source: {rel}')
                collected.add(rel)
    return sorted(collected)


def source_exclusions(project_root: Path, contract: dict) -> tuple[str, ...]:
    """Return the shared source policy without opening excluded file bodies.

    Lifecycle snapshots and scan must use this same policy as the inventory.
    Visible symlinks remain a refusal, even when their spelling is excluded.
    """
    project = _project(project_root)
    contract = validate_contract(contract, project)
    excluded = set(contract['excluded_roots']) | {contract['wiki_dir']}
    for source in contract['source_roots']:
        path = _safe(project, source, exists=True)
        if _excluded(source, contract):
            excluded.add(source)
            continue
        if path.is_file():
            continue
        for base, dirs, files in os.walk(path, followlinks=False):
            prefix = _walk_prefix(project, base)
            retained = []
            for name in sorted(dirs):
                rel = prefix + name
                if os.path.islink(os.path.join(base, name)):
                    raise ValueError(f'unsafe source symlink: {rel}')
                if _excluded(rel, contract):
                    excluded.add(rel)
                else:
                    _safe(project, rel, exists=True)
                    retained.append(name)
            dirs[:] = retained
            for name in sorted(files):
                rel = prefix + name
                if os.path.islink(os.path.join(base, name)):
                    raise ValueError(f'unsafe source symlink: {rel}')
                if _excluded(rel, contract) or not _suffix_ok(rel, contract):
                    excluded.add(rel)
                else:
                    _safe(project, rel, exists=True)
    return tuple(sorted(excluded))


def _authority(rel: str, contract: dict) -> dict:
    rule = next((r for r in contract['authority_rules']
                 if fnmatch.fnmatchcase(rel, r['pattern'])), contract['fallback'])
    return {key: rule[key] for key in ('document_type', 'authority_rank', 'role')}


def _title(data: bytes, rel: str) -> str:
    try:
        text = data.decode('utf-8')
    except UnicodeError:
        return PurePosixPath(rel).stem
    heading = re.search(r'^#\s+(.+?)\s*#*\s*$', text, re.MULTILINE)
    return heading[1] if heading else PurePosixPath(rel).stem


def _inventory(project: Path, contract: dict) -> tuple[list[dict], dict[str, str]]:
    records, hashes = [], {}
    ids = set()
    for rel in _paths(project, contract):
        data = _safe(project, rel, exists=True).read_bytes()
        identity = 'src-' + _digest(rel.encode('utf-8'))
        if identity in ids:
            raise ValueError('source path-digest collision; refusing ambiguous IDs')
        ids.add(identity)
        hashes[rel] = _digest(data)
        records.append({'id': identity, 'source_path': rel, 'sha256': hashes[rel],
                        'title': _title(data, rel), **_authority(rel, contract)})
    return records, hashes


def _registry_entries(registry: dict) -> dict[str, dict]:
    """Validate active identity/path/hash structure, without filesystem reads."""
    if not isinstance(registry, dict):
        raise ValueError('registry must be an object')
    if type(registry.get('schema_version')) is not int or registry['schema_version'] != 1:
        raise ValueError('registry schema_version must be integer 1')
    if not isinstance(registry.get('sources'), list):
        raise ValueError('registry sources must be a list')
    if 'archived_sources' in registry and not isinstance(registry['archived_sources'], list):
        raise ValueError('registry archived_sources must be a list')
    identities, paths = set(), {}
    for row in registry['sources']:
        if not isinstance(row, dict):
            raise ValueError('registry source must be an object')
        if not isinstance(row.get('id'), str) or not row['id'].strip():
            raise ValueError('registry source ID missing')
        rel = _relative(row.get('source_path'), 'registered source_path')
        if row['id'] in identities or rel in paths:
            raise ValueError('duplicate registered source ID/path')
        identities.add(row['id'])
        paths[rel] = row
        if not isinstance(row.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', row['sha256']):
            raise ValueError('registered sha256 missing/invalid; hash retrofit refused')
    return paths


def _reconciliation(accept_removed, relocations) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    """Normalize only the container, never repair a requested path spelling."""
    if not isinstance(accept_removed, (tuple, list)) or not isinstance(relocations, (tuple, list)):
        raise ValueError('reconciliation requests must be tuple/list collections')
    removed = tuple(_relative(path, 'accept_removed') for path in accept_removed)
    moves = []
    for pair in relocations:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise ValueError('relocations require (old, new) path pairs')
        moves.append((_relative(pair[0], 'relocation old'), _relative(pair[1], 'relocation destination')))
    old = [path for path, _ in moves]
    new = [path for _, path in moves]
    if (len(set(removed)) != len(removed) or len(set(old)) != len(old) or
            len(set(new)) != len(new) or set(removed) & set(old) or
            (set(removed) | set(old)) & set(new)):
        raise ValueError('duplicate/overlapping reconciliation requests')
    all_paths = removed + tuple(old) + tuple(new)
    for i, path in enumerate(all_paths):
        if any(_below(path, other) or _below(other, path) for other in all_paths[i + 1:]):
            raise ValueError('overlapping reconciliation paths')
    return removed, tuple(moves)


def _reconciliation_targets(previous: dict[str, dict], removed, moves) -> None:
    affected = set(removed) | {old for old, _ in moves}
    if affected - previous.keys():
        raise ValueError('reconciliation path is not an active registered source')
    if any(new in previous for _, new in moves):
        raise ValueError('relocation destination collides with a registered source')


def _archive_events(previous: dict[str, dict], removed, moves, now: str) -> list[dict]:
    return ([{'source': copy.deepcopy(previous[path]), 'reason': 'removed', 'at': now}
             for path in removed] +
            [{'source': copy.deepcopy(previous[old]), 'reason': 'relocated', 'at': now, 'destination': new}
             for old, new in moves])


def _same_json(a, b) -> bool:
    # JSON equality must not treat True as 1 or silently accept nonfinite values.
    try:
        return json.dumps(a, sort_keys=True, allow_nan=False) == json.dumps(b, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError('registry transition requires finite JSON values') from exc


def validate_registry_transition(previous: dict, registry: dict, *, accept_removed=(),
                                 relocations=(), now: str | None = None) -> bool:
    """Independently verify identity, metadata and exact append-only history.

    Filesystem eligibility and current hashes belong to the planner/caller's
    source snapshot validation. This validator never opens original bodies.
    Existing history may contain unknown event shapes and is retained verbatim.
    """
    before, after = _registry_entries(previous), _registry_entries(registry)
    removed, moves = _reconciliation(accept_removed, relocations)
    _reconciliation_targets(before, removed, moves)
    affected = set(removed) | {old for old, _ in moves}
    destinations = {new: old for old, new in moves}
    expected = (before.keys() - affected) | destinations.keys()
    if not expected <= after.keys() or affected & after.keys():
        raise ValueError('registry transition lost an active source or retained a reconciled path')
    top_before = {k: v for k, v in previous.items() if k not in {'sources', 'archived_sources'}}
    top_after = {k: v for k, v in registry.items() if k not in {'sources', 'archived_sources'}}
    if not _same_json(top_before, top_after):
        raise ValueError('registry transition changed top-level metadata')
    observations = _RECORD_OWNED - {'id'}
    old_ids = {row['id'] for row in before.values()}
    for path, row in after.items():
        if not _RECORD_OWNED <= row.keys() or not isinstance(row['title'], str):
            raise ValueError('registry transition requires complete source observations')
        _rule(row, 'registry source')
        original = before.get(destinations.get(path, path))
        if original is not None:
            kept_before = {k: v for k, v in original.items() if k not in observations}
            kept_after = {k: v for k, v in row.items() if k not in observations}
            if not _same_json(kept_before, kept_after):
                raise ValueError('registry transition changed source ID or extension metadata')
        elif row['id'] != 'src-' + _digest(path.encode('utf-8')) or row['id'] in old_ids:
            raise ValueError('new source identity must be a noncolliding path digest')
    history = previous.get('archived_sources', [])
    following = registry.get('archived_sources', [])
    event_count = len(removed) + len(moves)
    if event_count:
        if len(following) != len(history) + event_count:
            raise ValueError('registry archived_sources append count mismatch')
        first = following[len(history)]
        if not isinstance(first, dict) or not core._timestamp(first.get('at')):
            raise ValueError('registry archive timestamp requires an explicit offset')
        stamp = _now(now) if now is not None else first['at']
        expected_history = history + _archive_events(before, removed, moves, stamp)
    else:
        if now is not None:
            _now(now)
        if ('archived_sources' in previous) != ('archived_sources' in registry):
            raise ValueError('registry transition changed history field presence')
        expected_history = history
    if not _same_json(expected_history, following):
        raise ValueError('registry archived_sources must preserve exact history and requested events')
    return True


def _load_registry(project: Path, contract: dict, *, allow_missing=()) -> dict:
    rel = contract['wiki_dir'] + '/source-registry.json'
    path = _safe(project, rel)
    if not path.exists():
        return {'schema_version': 1, 'sources': []}
    if not path.is_file():
        raise ValueError('source registry must be a regular JSON file')
    registry = _json_load(path.read_bytes(), rel)
    for rel in _registry_entries(registry):
        source = _safe(project, rel, exists=rel not in allow_missing)
        if rel not in allow_missing and not source.is_file():
            raise ValueError(f'missing registered regular source: {rel}')
    return registry


def _registry(project: Path, contract: dict, *, accept_removed=(), relocations=(),
              now: str | None = None) -> tuple[dict, dict[str, str]]:
    removed, moves = _reconciliation(accept_removed, relocations)
    affected = set(removed) | {old for old, _ in moves}
    old = _load_registry(project, contract, allow_missing=affected)
    previous = {r['source_path']: r for r in old['sources']}
    _reconciliation_targets(previous, removed, moves)
    records, hashes = _inventory(project, contract)
    indexed = {r['source_path']: r for r in records}
    if affected & indexed.keys():
        raise ValueError('reconciliation requires a missing or out-of-inventory registered source')
    if any(new not in indexed for _, new in moves):
        raise ValueError('relocation destination is missing, excluded or outside current source inventory')
    unresolved = previous.keys() - indexed.keys() - affected
    if unresolved:
        raise ValueError('registered sources outside current scope; pruning refused: ' +
                         ', '.join(sorted(unresolved)))
    destinations = {new: before for before, new in moves}
    merged, ids = [], set()
    for row in records:
        before = previous.get(destinations.get(row['source_path'], row['source_path']), {})
        current = copy.deepcopy(before)
        current.update(row)
        if before:
            current['id'] = before['id']
        if current['id'] in ids:
            raise ValueError('registered/new source ID collision')
        ids.add(current['id'])
        merged.append(current)
    result = copy.deepcopy(old)
    result['sources'] = merged
    if affected:
        result['archived_sources'] = copy.deepcopy(old.get('archived_sources', [])) + _archive_events(previous, removed, moves, _now(now))
    validate_registry_transition(old, result, accept_removed=removed, relocations=moves, now=now)
    return result, hashes


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def _lookup(registry: dict) -> dict:
    return {r['id']: {'resource': 'project:' + r['source_path'],
                      'source_path': r['source_path'], 'sha256': r['sha256']}
            for r in registry['sources']}


def _now(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec='seconds')
    if not core._timestamp(value):
        raise ValueError('now: valid ISO timestamp with explicit offset required')
    return value


def _reserved(names):
    for name in names:
        leaf = PurePosixPath(name).name
        if leaf.casefold() in {'index.md', 'log.md'} and leaf not in {'index.md', 'log.md'}:
            raise ValueError(f'ambiguous reserved filename case; use exact index.md/log.md: {name}')
    folded = [n.casefold() for n in names]
    if len(set(folded)) != len(folded):
        raise ValueError('ambiguous case-colliding Markdown paths')
    parent_spelling = {}
    for name in names:
        for parent in PurePosixPath(name).parents:
            spelling = parent.as_posix()
            prior = parent_spelling.setdefault(spelling.casefold(), spelling)
            if prior != spelling:
                raise ValueError('ambiguous case-colliding wiki directory paths')


def _texts(project: Path, contract: dict, baseline: dict) -> dict[str, str]:
    names = sorted(n for n in baseline if n.lower().endswith('.md') and not n.endswith('/'))
    _reserved(names)
    result = {}
    for name in names:
        try:
            result[name] = _safe(project, contract['wiki_dir'] + '/' + name, exists=True).read_bytes().decode('utf-8')
        except UnicodeError as exc:
            raise ValueError(f'wiki Markdown must be UTF-8: {name}') from exc
    return result


def _outside_block(body: str, start=INDEX_START, end=INDEX_END) -> tuple[str, str, bool]:
    if start not in body and end not in body:
        return body, '', False
    if body.count(start) != 1 or body.count(end) != 1 or body.index(start) >= body.index(end):
        raise ValueError('invalid/ambiguous generated block markers')
    prefix, rest = body.split(start, 1)
    _, suffix = rest.split(end, 1)
    return prefix, suffix, True


def directory_indices(bundle: Path, texts: dict[str, str]) -> dict[str, str]:
    """Generate only bounded listings; preserve both outside body segments."""
    _reserved(texts)
    dirs = {PurePosixPath(name).parent for name in texts}
    dirs.add(PurePosixPath('.'))
    for directory in list(dirs):
        dirs.update(directory.parents)
    output = dict(texts)
    for directory in sorted(dirs, key=str):
        name = (directory / 'index.md').as_posix()
        original = output.get(name, '# Knowledge directory\n\n')
        metadata, body = core.parse_markdown(original)
        prefix, suffix, bounded = _outside_block(body)
        if not bounded:
            prefix += '' if prefix.endswith('\n\n') else '\n' if prefix.endswith('\n') else '\n\n'
        lines = [INDEX_START, '## Directory navigation', '']
        for child in sorted(d for d in dirs if d != directory and d.parent == directory):
            lines.append(f'- [{child.name}](/' + quote((child / 'index.md').as_posix()) + ')')
        for rel, text in sorted(texts.items()):
            p = PurePosixPath(rel)
            if p.parent != directory or p.name == 'index.md':
                continue
            meta, _ = core.parse_markdown(text)
            title = str(meta.get('title', p.stem)).replace('[', '\\[').replace(']', '\\]').replace('\n', ' ')
            description = str(meta.get('description', p.stem)).replace('\n', ' ')
            lines.append(f'- [{title}](/' + quote(rel) + f') — {description}')
        lines.append(INDEX_END)
        output[name] = core.normalize_index(bundle, name, core.render_markdown(metadata, prefix + '\n'.join(lines) + suffix))
    return output


def preservation(before: str, after: str, bundle: Path, rel: str) -> dict:
    old, body = core.parse_markdown(before)
    new, new_body = core.parse_markdown(after)
    preserved = all(k in new and new[k] == v for k, v in old.items() if k not in {'sources', 'status', 'type'})
    for key, destination in [('type', 'legacy_type'), ('status', 'workflow_status')]:
        if key in old and new.get(key) != old[key]:
            candidates = [new.get(destination)] + ([new.get('legacy_status')] if key == 'status' else [])
            preserved = preserved and any(old[key] == value for value in candidates)
    if 'sources' in old:
        a, b = old['sources'], new.get('sources')
        if not isinstance(a, list):
            preserved = preserved and a == b
        elif not isinstance(b, list) or len(a) != len(b):
            preserved = False
        else:
            for previous, current in zip(a, b):
                if isinstance(previous, dict):
                    preserved = preserved and isinstance(current, dict) and all(k in current and current[k] == v for k, v in previous.items())
                elif isinstance(previous, str):
                    preserved = preserved and (previous == current or isinstance(current, dict) and current.get('id') == previous)
                else:
                    preserved = preserved and previous == current
    expected = core.rewrite_wikilinks(bundle, rel, body)
    leaf = PurePosixPath(rel).name
    if leaf == 'log.md':
        body_ok = core.normalize_log(expected) == after
    elif leaf == 'index.md':
        prefix, suffix, bounded = _outside_block(expected)
        new_prefix, new_suffix, new_bounded = _outside_block(new_body)
        if bounded:
            body_ok = new_bounded and prefix == new_prefix and suffix == new_suffix
        else:
            # Only separator newlines may be appended before the first listing.
            body_ok = new_bounded and new_prefix.startswith(prefix) and not new_prefix[len(prefix):].strip('\r\n') and not new_suffix
            if not new_bounded:
                body_ok = new_body == expected
    else:
        body_ok = expected == new_body
    return {'metadata_preserved': bool(preserved), 'body_preserved_except_normalization': bool(body_ok),
            'body_exact': body == new_body, 'before_keys': [str(k) for k in old], 'after_keys': [str(k) for k in new]}


def _registry_md(registry: dict, previous: str, now: str) -> str:
    start, end = '<!-- wiki-desk:source-registry:start -->', '<!-- wiki-desk:source-registry:end -->'
    if previous:
        meta, body = core.parse_markdown(previous)
    else:
        meta, body = {}, '# Original source registry\n\nMetadata and path references only. Existence and hashes do not establish approval.\n\n'
    meta.setdefault('type', 'SourceRegistry')
    meta.setdefault('title', 'Original source registry')
    meta.setdefault('description', 'Project-relative source paths, content observations and explicit authority rules.')
    meta.setdefault('generated', {'by': 'process:wiki-desk-source-inventory', 'at': now})
    prefix, suffix, bounded = _outside_block(body, start, end)
    if not bounded:
        prefix += '' if prefix.endswith('\n\n') else '\n' if prefix.endswith('\n') else '\n\n'
    lines = [start, '| ID | Source path | Title | Type | Rank | Role | SHA256 |',
             '| --- | --- | --- | --- | ---: | --- | --- |']
    def cell(v):
        return str(v).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')
    for row in sorted(registry['sources'], key=lambda r: (-r['authority_rank'], r['source_path'])):
        link = '[' + cell(row['source_path']).replace('[', '\\[').replace(']', '\\]') + '](project:' + quote(row['source_path']) + ')'
        lines.append('| ' + ' | '.join([cell(row['id']), link, cell(row['title']), cell(row['document_type']),
                                       cell(row['authority_rank']), cell(row['role']), cell(row['sha256'])]) + ' |')
    lines.append(end)
    return core.render_markdown(meta, prefix + '\n'.join(lines) + suffix)


def scaffold_files(project_root: Path, contract: dict, now: str | None = None) -> dict[str, bytes]:
    project = _project(project_root)
    contract = validate_contract(contract, project)
    now = _now(now)
    wiki = contract['wiki_dir']
    if _safe(project, wiki).exists():
        raise ValueError('fresh scaffold refuses existing wiki; use format/sync for adoption')
    registry, source_snapshot = _registry(project, contract)
    texts = {
        'index.md': core.render_markdown({'okf_version': '0.2'}, '# ' + contract['project_name'] + ' knowledge index\n\nA path-reference wiki; original documents remain authoritative.\n\n'),
        'log.md': '# Wiki log\n\n',
        'SCHEMA.md': core.render_markdown({'type': 'Reference', 'title': 'Project wiki schema',
                                         'description': 'Local path-reference and OKF 0.2 contracts.',
                                         'generated': {'by': 'process:wiki-desk-scaffold', 'at': now}},
            '# Project wiki schema\n\nThe project contract is `<installed-skill>/project/contract.json`, outside this wiki.\n'
            'Unknown producer metadata and types are retained. Sources remain in their original project paths.\n'
            'Source registry existence and hashes are observations, not approval or verification.\n'
            'Knowledge lifecycle, generated events, verified events and document authority are separate.\n'),
        'concepts/index.md': '# Knowledge concepts\n\n',
        'sources/index.md': '# Source navigation\n\n',
        'source-registry.md': _registry_md(registry, '', now),
    }
    texts = directory_indices(project / wiki, texts)
    outputs = {wiki + '/' + name: text.encode('utf-8') for name, text in texts.items()}
    outputs[wiki + '/source-registry.json'] = _json_bytes(registry)
    if _inventory(project, contract)[1] != source_snapshot or _safe(project, wiki).exists():
        raise ValueError('source/wiki snapshot drift during scaffold')
    return outputs


def _plan_report(project: Path, contract: dict, texts: dict[str, str], desired: dict[str, str],
                 outputs: dict[str, bytes], baseline: dict[str, str], source_snapshot: dict[str, str],
                 now: str, mode: str, failures: dict | None = None,
                 registry_owned=False, allow_missing=()) -> dict:
    failures = failures or {}
    wiki, bundle = contract['wiki_dir'], project / contract['wiki_dir']
    rows = []
    for name, text in sorted(desired.items()):
        issues = list(failures.get(name, [])) + core.validate_markdown(bundle, name, text)
        # Planned directory indices are part of the complete desired graph.
        from urllib.parse import unquote
        issues = [i for i in issues if not (i.startswith('warning:broken-link:/') and
                  unquote(i.split('warning:broken-link:/', 1)[1]).split('#', 1)[0] in desired)]
        guard = {'metadata_preserved': True, 'body_preserved_except_normalization': True}
        if name in texts:
            try:
                if registry_owned and name == 'source-registry.md':
                    old_meta, old_body = core.parse_markdown(texts[name])
                    new_meta, new_body = core.parse_markdown(text)
                    start, end = '<!-- wiki-desk:source-registry:start -->', '<!-- wiki-desk:source-registry:end -->'
                    a, b, bounded = _outside_block(old_body, start, end)
                    c, d, _ = _outside_block(new_body, start, end)
                    body_ok = (a == c and b == d) if bounded else c.startswith(a) and not c[len(a):].strip('\r\n') and not d
                    guard = {'metadata_preserved': all(k in new_meta and new_meta[k] == v for k, v in old_meta.items()),
                             'body_preserved_except_normalization': bool(body_ok)}
                else:
                    guard = preservation(texts[name], text, bundle, name)
            except (ValueError, TypeError) as exc:
                guard = {'metadata_preserved': False, 'body_preserved_except_normalization': False}
                issues.append(f'error:preservation:{exc}')
            if not all(guard[k] for k in ('metadata_preserved', 'body_preserved_except_normalization')):
                issues.append('error:preservation:original metadata/body loss')
        rows.append({'path': wiki + '/' + name, 'wiki_path': name, 'new': name not in texts,
                     'changed': text != texts.get(name), 'before_sha256': baseline.get(name),
                     'after_sha256': _digest(text.encode('utf-8')), 'issues': list(dict.fromkeys(issues)), **guard})
    extra_rows = []
    for path, payload in sorted(outputs.items()):
        rel = PurePosixPath(path).relative_to(wiki).as_posix()
        if not rel.lower().endswith('.md'):
            extra_rows.append({'path': path, 'wiki_path': rel, 'new': rel not in baseline,
                               'changed': _digest(payload) != baseline.get(rel),
                               'before_sha256': baseline.get(rel), 'after_sha256': _digest(payload), 'issues': []})
    all_rows = rows + extra_rows
    global_diagnostics = [{'path': wiki + '/' + name, 'issues': issues}
                          for name, issues in failures.items() if name not in desired]
    errors = sum(i.startswith('error:') for r in rows + global_diagnostics for i in r['issues'])
    preservation_complete = set(texts) <= set(desired) and all(
        r['metadata_preserved'] and r['body_preserved_except_normalization'] for r in rows)
    unchanged = _snapshot(project, wiki) == baseline
    try:
        sources_unchanged = _inventory(project, contract)[1] == source_snapshot
    except (ValueError, OSError):
        sources_unchanged = False
    if not unchanged or not sources_unchanged:
        errors += 1
    coverage = len(texts) == len(set(texts)) and set(texts) <= set(desired) and len(desired) == len(rows) == len({r['wiki_path'] for r in rows})
    changed = sorted(r['path'] for r in all_rows if r['changed'])
    original_registry = _load_registry(project, contract, allow_missing=allow_missing)
    source_changes = [{'path': row['source_path'], 'registered_sha256': row['sha256'],
                       'current_sha256': source_snapshot.get(row['source_path'])}
                      for row in original_registry['sources']
                      if row['sha256'] != source_snapshot.get(row['source_path'])]
    return {'mode': mode, 'planned_at': now, 'applied': False,
            'expected': len(texts), 'collected': len(texts), 'unique': len(set(texts)),
            'final_expected': len(desired), 'final_collected': len(rows), 'final_unique': len({r['wiki_path'] for r in rows}),
            'new_page_count': len(set(desired) - set(texts)), 'coverage_complete': coverage,
            'coverage': {'expected': len(texts), 'collected': len(texts), 'unique': len(set(texts)),
                         'complete': coverage},
            'error_count': errors, 'warning_count': sum(i.startswith('warning:') for r in rows for i in r['issues']),
            'safety_count': sum(i.startswith('safety:') for r in rows for i in r['issues']),
            'preservation_complete': preservation_complete, 'snapshot_unchanged': unchanged,
            'source_snapshot_unchanged': sources_unchanged, 'source_changes': source_changes,
            'source_count': len(source_snapshot), 'changed_files': changed, 'changed_count': len(changed),
            'denominator': 'markdown', 'file_count': len(all_rows), 'markdown_files': rows,
            'nonmarkdown_files': extra_rows, 'diagnostics': global_diagnostics,
            'files': all_rows, 'paths': all_rows,
            'conformant': bool(coverage and not errors and preservation_complete and unchanged and sources_unchanged)}


def sync_plan(project_root: Path, contract: dict, now: str | None = None, *,
              accept_removed=(), relocations=()) -> dict:
    project = _project(project_root)
    contract = validate_contract(contract, project)
    now = _now(now)
    wiki = contract['wiki_dir']
    baseline = _snapshot(project, wiki)
    texts = _texts(project, contract, baseline)
    if not texts:
        raise ValueError('sync requires an existing non-empty wiki; use scaffold for fresh installation')
    removed, moves = _reconciliation(accept_removed, relocations)
    registry, source_snapshot = _registry(project, contract, accept_removed=removed, relocations=moves, now=now)
    desired = dict(texts)
    desired['source-registry.md'] = _registry_md(registry, texts.get('source-registry.md', ''), now)
    desired = directory_indices(project / wiki, desired)
    outputs = {wiki + '/' + name: text.encode('utf-8') for name, text in desired.items()}
    outputs[wiki + '/source-registry.json'] = _json_bytes(registry)
    report = _plan_report(project, contract, texts, desired, outputs, baseline, source_snapshot,
                          now, 'sync-dry-run', registry_owned=True,
                          allow_missing=set(removed) | {old for old, _ in moves})
    return {'outputs': outputs, 'report': report, 'baseline': baseline, 'source_snapshot': source_snapshot}


def format_plan(project_root: Path, contract: dict, now: str | None = None) -> dict:
    project = _project(project_root)
    contract = validate_contract(contract, project)
    now = _now(now)
    wiki = contract['wiki_dir']
    baseline = _snapshot(project, wiki)
    texts = _texts(project, contract, baseline)
    if not texts:
        raise ValueError('format requires an existing wiki with Markdown files')
    registry, source_snapshot = _registry(project, contract)
    lookup, desired, failures = _lookup(registry), {}, {}
    for name, text in texts.items():
        try:
            leaf = PurePosixPath(name).name
            if leaf == 'index.md':
                desired[name] = core.normalize_index(project / wiki, name, text)
            elif leaf == 'log.md':
                desired[name] = core.normalize_log(core.rewrite_wikilinks(project / wiki, name, text))
            else:
                desired[name] = core.normalize_concept(project / wiki, name, text, source_lookup=lookup, now=now)
        except (ValueError, TypeError) as exc:
            desired[name] = text
            failures[name] = [f'error:normalization:{exc}']
    if not failures:
        try:
            desired = directory_indices(project / wiki, desired)
        except (ValueError, TypeError) as exc:
            failures['index.md'] = [f'error:directory-index:{exc}']
    outputs = {wiki + '/' + name: text.encode('utf-8') for name, text in desired.items()}
    report = _plan_report(project, contract, texts, desired, outputs, baseline, source_snapshot,
                          now, 'format-dry-run', failures=failures)
    return {'outputs': outputs, 'report': report, 'baseline': baseline, 'source_snapshot': source_snapshot}


def query(project_root: Path, contract: dict, terms: str, limit: int = 10) -> dict:
    project = _project(project_root)
    contract = validate_contract(contract, project)
    if not isinstance(terms, str) or not terms.strip():
        raise ValueError('query terms: non-empty string required')
    if type(limit) is not int or limit < 1:
        raise ValueError('query limit: positive integer required')
    try:
        tokens = [t.casefold() for t in shlex.split(terms) if t.strip()]
    except ValueError as exc:
        raise ValueError('query terms: invalid quoting') from exc
    if not tokens:
        raise ValueError('query terms contain no search tokens')
    before = _snapshot(project, contract['wiki_dir'])
    registry, source_snapshot = _registry(project, contract)
    matches, read, unread = [], [], []
    for row in registry['sources']:
        rel = row['source_path']
        data = _safe(project, rel, exists=True).read_bytes()
        try:
            text = data.decode('utf-8')
        except UnicodeError:
            unread.append({'path': rel, 'reason': 'non-UTF-8 original; metadata only'})
            continue
        read.append(rel)
        title = _title(data, rel)
        haystack = ('\n'.join([rel, row['id'], title, text])).casefold()
        if not all(t in haystack for t in tokens):
            continue
        score = sum(3 if t in title.casefold() else 1 for t in tokens)
        matches.append({**copy.deepcopy(row), 'title': title, 'sha256': _digest(data),
                        'original_read': True, 'metadata_match': all(t in (row['title'] + '\n' + rel).casefold() for t in tokens),
                        'original_term_match': all(t in text.casefold() for t in tokens),
                        'relevance': score, 'review_status': 'original-read-not-semantic-approval'})
    matches.sort(key=lambda r: (-r['authority_rank'], -r['relevance'], r['source_path']))
    wiki_unchanged = _snapshot(project, contract['wiki_dir']) == before
    source_unchanged = _inventory(project, contract)[1] == source_snapshot
    return {'terms': terms, 'results': matches[:limit], 'matched_count': len(matches),
            'returned_count': len(matches[:limit]), 'source_count': len(registry['sources']),
            'metadata_is_approval': False, 'approval_inferred': False,
            'read_coverage': {'expected': len(registry['sources']), 'collected': len(read), 'unique': len(set(read)),
                              'read_count': len(read), 'unread_count': len(unread), 'unread': unread,
                              'complete': len(read) == len(registry['sources'])},
            'snapshot_unchanged': wiki_unchanged, 'source_snapshot_unchanged': source_unchanged,
            'error_count': int(not wiki_unchanged or not source_unchanged)}


def check_bundle(project_root: Path, contract: dict) -> dict:
    project = _project(project_root)
    contract = validate_contract(contract, project)
    wiki = contract['wiki_dir']
    baseline = _snapshot(project, wiki)
    texts = _texts(project, contract, baseline)
    rows = [{'path': wiki + '/' + name, 'issues': core.validate_markdown(project / wiki, name, text)}
            for name, text in sorted(texts.items())]
    count = len(texts)
    errors = sum(i.startswith('error:') for r in rows for i in r['issues'])
    if not count:
        errors += 1
    unchanged = _snapshot(project, wiki) == baseline
    if not unchanged:
        errors += 1
    profile_errors = []
    for reserved in ('index.md', 'log.md'):
        if reserved not in texts:
            profile_errors.append(f'missing root {reserved}')
    if 'index.md' in texts:
        try:
            meta, _ = core.parse_markdown(texts['index.md'])
            if str(meta.get('okf_version')) != '0.2':
                profile_errors.append('root index requires okf_version 0.2')
        except (TypeError, ValueError):
            profile_errors.append('root index frontmatter invalid')
    return {'conformant': bool(count and not errors and unchanged), 'error_count': errors,
            'expected': count, 'collected': len(rows), 'unique': len({r['path'] for r in rows}),
            'final_expected': count, 'final_collected': len(rows), 'final_unique': len({r['path'] for r in rows}),
            'coverage': {'expected': count, 'collected': len(rows), 'unique': len({r['path'] for r in rows}), 'complete': bool(count and count == len(rows))},
            'coverage_complete': bool(count and count == len(rows)), 'snapshot_unchanged': unchanged,
            'profile_complete': bool(not profile_errors and unchanged), 'profile_errors': profile_errors,
            'warning_count': sum(i.startswith('warning:') for r in rows for i in r['issues']),
            'safety_count': sum(i.startswith('safety:') for r in rows for i in r['issues']),
            'files': rows, 'paths': rows}
