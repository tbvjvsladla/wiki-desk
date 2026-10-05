"""Synthetic R10 regressions: one filter, no filtered body opens."""
import sys
sys.dont_write_bytecode = True
import io
import json
import os
import shutil
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import fs_safety as fs
import package_manifest as manifest  # type: ignore[import-not-found]
import wiki_desk as desk
import wiki_runtime as runtime

NOW = '2026-01-02T03:04:05+00:00'
FILTERED = ('docs/b.json', 'docs/d.txt', 'docs/sub/e.log')


def contract(**extra):
    cfg = {'schema_version': 1, 'project_name': 'Synthetic suffix fixture',
           'wiki_dir': '__llm-wiki', 'source_roots': ['docs'], 'excluded_roots': [],
           'authority_rules': [], 'fallback': {'document_type': 'reference', 'authority_rank': 0, 'role': 'reference'},
           'copy_policy': 'path_reference'}
    cfg.update(extra)
    return cfg


def put(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode() if isinstance(text, str) else text)


@pytest.fixture
def project(tmp_path):
    for rel in ('docs/a.md', 'docs/sub/c.MD', *FILTERED):
        put(tmp_path, rel, '# Synthetic title\nSYNTHETIC_BODY_NOT_METADATA\n')
    return tmp_path


def apply_fixture(root, outputs):
    for rel, data in outputs.items():
        put(root, rel, data)


def test_absent_key_preserves_all_regular_inventory(project):
    cfg = runtime.validate_contract(contract(), project)
    assert runtime._paths(project, cfg) == sorted(('docs/a.md', 'docs/sub/c.MD', *FILTERED))


@pytest.mark.parametrize('root', ['docs', '.'])
def test_casefold_inventory_and_shared_exclusions(project, root):
    cfg = contract(source_roots=[root], source_suffixes=['.MD'])
    assert runtime._paths(project, runtime.validate_contract(cfg, project)) == ['docs/a.md', 'docs/sub/c.MD']
    excluded = runtime.source_exclusions(project, cfg)
    assert set(FILTERED) <= set(excluded)
    assert not {'docs/a.md', 'docs/sub/c.MD'} & set(excluded)


def test_filtered_bodies_never_open_in_runtime_scan_and_snapshot(project):
    cfg = contract(source_suffixes=['.md'])
    put(project, 'contract.json', json.dumps(cfg))
    forbidden = {project / rel for rel in FILTERED}
    real_open, real_os_open = Path.open, os.open
    attempts = []
    def guarded(path, *args, **kwargs):
        if Path(path) in forbidden:
            attempts.append(str(path))
            raise AssertionError('filtered Path.open: ' + str(path))
        return real_open(path, *args, **kwargs)
    def os_guarded(path, flags, *args, **kwargs):
        if isinstance(path, (str, bytes, os.PathLike)) and Path(os.fsdecode(path)) in forbidden:
            attempts.append(str(path))
            raise AssertionError('filtered os.open: ' + str(path))
        return real_os_open(path, flags, *args, **kwargs)
    with patch.object(Path, 'open', guarded), patch.object(os, 'open', os_guarded):
        excluded = runtime.source_exclusions(project, cfg)
        snap = fs.snapshot(project, cfg['source_roots'], excludes=excluded)
        result = runtime.query(project, cfg, 'synthetic')
        outputs = runtime.scaffold_files(project, cfg, NOW)
        apply_fixture(project, outputs)
        sync = runtime.sync_plan(project, cfg, NOW)
        runtime.format_plan(project, cfg, NOW)
        with redirect_stdout(io.StringIO()) as stdout:
            rc = desk.main(['scan', '--root', str(project), '--contract', str(project / 'contract.json')])
    assert attempts == []
    assert {rel for rel, state in snap.entries if state.kind == 'file'} == {'docs/a.md', 'docs/sub/c.MD'}
    assert set(sync['source_snapshot']) == {'docs/a.md', 'docs/sub/c.MD'}
    assert result['source_count'] == 2 and result['read_coverage']['complete']
    assert b'SYNTHETIC_BODY_NOT_METADATA' not in b'\n'.join(outputs.values())
    scanned = json.loads(stdout.getvalue())
    assert rc == 0, scanned
    assert {row['path'] for row in scanned['source_files']} == {'docs/a.md', 'docs/sub/c.MD'}


def test_filtered_edits_additions_and_deletions_are_not_sync_drift(project):
    cfg = contract(source_suffixes=['.md'])
    apply_fixture(project, runtime.scaffold_files(project, cfg, NOW))
    put(project, 'docs/b.json', 'changed')
    (project / 'docs/d.txt').unlink()
    put(project, 'docs/sub/new.csv', 'a,b')
    plan = runtime.sync_plan(project, cfg, NOW)
    assert plan['report']['source_changes'] == []
    assert plan['report']['changed_files'] == []
    put(project, 'docs/a.md', '# Changed title\n')
    assert runtime.sync_plan(project, cfg, NOW)['report']['source_changes']


@pytest.mark.parametrize('value', [[], ['md'], ['.m d'], ['.tar.gz'], [''], [1], '.md', ['.md', '.MD'], None, ['.md '], ['..md']])
def test_invalid_suffix_contract_is_refused(project, value):
    with pytest.raises(ValueError, match='source_suffixes'):
        runtime.validate_contract(contract(source_suffixes=value), project)


def test_explicit_file_root_mismatch_is_fail_closed(project):
    with pytest.raises(ValueError, match='outside source_suffixes'):
        runtime.validate_contract(contract(source_roots=['docs/b.json'], source_suffixes=['.md']), project)
    cfg = contract(source_roots=['docs/a.md', 'docs/sub'], source_suffixes=['.md'])
    assert runtime._paths(project, runtime.validate_contract(cfg, project)) == ['docs/a.md', 'docs/sub/c.MD']


@pytest.mark.parametrize('rel', ['docs/link.json', 'docs/private.json'])
def test_symlink_refusal_precedes_filter_and_exclusion(project, rel):
    (project / rel).symlink_to(project / 'docs/a.md')
    cfg = contract(source_suffixes=['.md'], excluded_roots=[rel])
    for call in (lambda: runtime._paths(project, runtime.validate_contract(cfg, project)),
                 lambda: runtime.source_exclusions(project, cfg)):
        with pytest.raises(ValueError, match='symlink'):
            call()


def test_walk_prefix_computed_once_per_directory_and_safe_kept(project):
    cfg = runtime.validate_contract(contract(source_suffixes=['.md']), project)
    with patch.object(runtime, '_walk_prefix', wraps=runtime._walk_prefix) as prefix, \
         patch.object(runtime, '_safe', wraps=runtime._safe) as safe:
        assert runtime._paths(project, cfg) == ['docs/a.md', 'docs/sub/c.MD']
    assert prefix.call_count == 2
    assert {'docs', 'docs/sub', 'docs/a.md', 'docs/sub/c.MD'} <= {call.args[1] for call in safe.call_args_list}


def test_schema_declares_optional_nonempty_suffixes():
    schema = json.loads((Path(__file__).resolve().parents[1] / 'assets/project-contract.schema.json').read_bytes())
    prop = schema['properties']['source_suffixes']
    assert 'source_suffixes' not in schema['required']
    assert prop['minItems'] == 1 and prop['uniqueItems'] is True


def test_narrowed_suffix_policy_requires_explicit_archives_without_body_reads(project):
    cfg = contract()
    apply_fixture(project, runtime.scaffold_files(project, cfg, NOW))
    old = json.loads((project / '__llm-wiki/source-registry.json').read_bytes())
    cfg['source_suffixes'] = ['.md']
    forbidden = {project / rel for rel in FILTERED}
    real_open = Path.open
    def guarded(path, *args, **kwargs):
        assert Path(path) not in forbidden, 'filtered registered body opened'
        return real_open(path, *args, **kwargs)
    with patch.object(Path, 'open', guarded):
        for call in (lambda: runtime.sync_plan(project, cfg, NOW),
                     lambda: runtime.format_plan(project, cfg, NOW),
                     lambda: runtime.query(project, cfg, 'synthetic')):
            with pytest.raises(ValueError, match='pruning refused'):
                call()
        plan = runtime.sync_plan(project, cfg, NOW, accept_removed=FILTERED)
    new = json.loads(plan['outputs']['__llm-wiki/source-registry.json'])
    assert {row['source_path'] for row in new['sources']} == {'docs/a.md', 'docs/sub/c.MD'}
    assert [event['source'] for event in new['archived_sources']] == [
        next(row for row in old['sources'] if row['source_path'] == rel) for rel in FILTERED]


def test_filtered_no_read_policy_across_actual_install_apply_sync_and_format(project):
    # Bind an isolated copy, never edit the source package manifest.
    package = project.parent / (project.name + '-package')
    shutil.copytree(Path(__file__).resolve().parents[1], package,
                    ignore=shutil.ignore_patterns('.git', '__pycache__', '.pytest_cache'))
    manifest.generate(package)
    cfg = contract(source_suffixes=['.md'])
    contract_path = project.parent / (project.name + '-contract.json')
    contract_path.write_bytes(desk.json_bytes(cfg))
    forbidden = {project / rel for rel in (*FILTERED, 'docs/late.json')}
    real_open, real_os_open = Path.open, os.open
    attempts = []
    def guarded(path, *args, **kwargs):
        if Path(path) in forbidden:
            attempts.append(str(path))
            raise AssertionError('filtered lifecycle Path.open')
        return real_open(path, *args, **kwargs)
    def os_guarded(path, flags, *args, **kwargs):
        if isinstance(path, (str, bytes, os.PathLike)) and Path(os.fsdecode(path)) in forbidden:
            attempts.append(str(path))
            raise AssertionError('filtered lifecycle os.open')
        return real_os_open(path, flags, *args, **kwargs)
    with patch.object(Path, 'open', guarded), patch.object(os, 'open', os_guarded):
        install = desk.prepare_install(project, 'hermes', contract_path, package, now=NOW)
        assert not (project / '__llm-wiki').exists()
        applied = desk.apply_plan(install)
        assert applied['status'] == 'APPLIED' and applied['readback_verified']
        assert desk.status(project)['status'] == 'PRESENT'
        for action in ('sync', 'format'):
            result = desk.apply_plan(desk.prepare_runtime_action(project, action, now=NOW))
            assert result['status'] == 'UNCHANGED'
        pending = desk.prepare_runtime_action(project, 'sync', now=NOW)
        # Fixture-only creation after planning: stale guards must never read it.
        with real_open(project / 'docs/late.json', 'wb') as stream:
            stream.write(b'SYNTHETIC_FILTERED_LATE_BODY')
        prior = (project / '__llm-wiki/source-registry.json').read_bytes()
        with pytest.raises(fs.SafetyError, match='Source baseline/policy membership drift'):
            desk.apply_plan(pending)
        assert (project / '__llm-wiki/source-registry.json').read_bytes() == prior
        assert desk.apply_plan(desk.prepare_runtime_action(project, 'sync', now=NOW))['status'] == 'UNCHANGED'
    assert attempts == []
