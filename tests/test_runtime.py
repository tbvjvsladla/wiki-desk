"""Synthetic portable-runtime regressions; no private corpus or producers."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.dont_write_bytecode = True
sys.path.insert(0, str(SCRIPTS))
import wiki_runtime as runtime
import okf_bundle as core

NOW = '2026-01-02T03:04:05+00:00'
# Operating state lives inside the installed skill (wiki_desk.contract_rel).
CONTRACT_REL = '.agents/skills/wiki-desk/project/contract.json'


def contract(wiki='__llm-wiki'):
    return {'schema_version': 1, 'project_name': 'Synthetic project', 'wiki_dir': wiki,
            'source_roots': ['docs'], 'excluded_roots': ['docs/private'],
            'authority_rules': [
                {'pattern': 'docs/decisions/**', 'document_type': 'decision', 'authority_rank': 100, 'role': 'decision'},
                {'pattern': 'docs/reports/**', 'document_type': 'report', 'authority_rank': 70, 'role': 'result-evidence'}],
            'fallback': {'document_type': 'reference', 'authority_rank': 0, 'role': 'reference'},
            'copy_policy': 'path_reference'}


def put(root, rel, data):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data.encode('utf-8') if isinstance(data, str) else data)


def fixture_apply(root, outputs):
    """Fixture-only writes, not a public runtime/apply implementation."""
    for rel, data in outputs.items():
        assert not Path(rel).is_absolute() and '..' not in Path(rel).parts
        assert isinstance(data, bytes)
        put(root, rel, data)


def tree(root):
    return {p.relative_to(root).as_posix() + ('/' if p.is_dir() else ''):
            'directory' if p.is_dir() else p.read_bytes()
            for p in root.rglob('*') if not p.is_symlink()}


@pytest.fixture
def project(tmp_path):
    (tmp_path / 'docs').mkdir()
    put(tmp_path, 'docs/decisions/a.md', '# Routing decision\nOpaque original-only phrase ALPHA-PRIVATE-BODY.\n')
    put(tmp_path, 'docs/reports/a.md', '# Routing report\nActual report body.\n')
    put(tmp_path, 'docs/reference.md', '# Routing reference\nUnranked original.\n')
    return tmp_path


@pytest.fixture
def seeded(project):
    cfg = contract()
    put(project, CONTRACT_REL, json.dumps(cfg))
    fixture_apply(project, runtime.scaffold_files(project, cfg, now=NOW))
    return project, cfg


@pytest.mark.parametrize('wiki', ['__llm-wiki', '__llm_wiki'])
def test_scaffold_paths_no_copy_write_zero_and_empty_roots(tmp_path, wiki):
    (tmp_path / 'docs').mkdir()
    cfg = contract(wiki)
    before = tree(tmp_path)
    outputs = runtime.scaffold_files(tmp_path, cfg, now=NOW)
    assert tree(tmp_path) == before
    required = {'index.md', 'log.md', 'SCHEMA.md', 'concepts/index.md', 'sources/index.md',
                'source-registry.md', 'source-registry.json'}
    assert {p.removeprefix(wiki + '/') for p in outputs} == required
    assert all(p.startswith(wiki + '/') and isinstance(b, bytes) for p, b in outputs.items())
    assert core.parse_markdown(outputs[wiki + '/index.md'].decode())[0] == {'okf_version': '0.2'}
    assert json.loads(outputs[wiki + '/source-registry.json'])['sources'] == []
    fixture_apply(tmp_path, outputs)
    assert runtime.check_bundle(tmp_path, cfg)['profile_complete']
    with pytest.raises(ValueError, match='existing wiki'):
        runtime.scaffold_files(tmp_path, cfg, now=NOW)


@pytest.mark.parametrize('key', sorted(runtime._REQUIRED))
def test_contract_requires_each_explicit_key(project, key):
    cfg = contract()
    del cfg[key]
    with pytest.raises(ValueError):
        runtime.validate_contract(cfg, project)


@pytest.mark.parametrize('key,value', [('schema_version', True), ('schema_version', 2), ('project_name', ''),
                                      ('copy_policy', 'copy'), ('wiki_dir', '../outside'), ('wiki_dir', '/abs'),
                                      ('wiki_dir', '.wiki-desk/wiki'), ('source_roots', []),
                                      ('source_roots', ['missing']), ('excluded_roots', None),
                                      ('authority_rules', {}), ('fallback', {}), ('wiki_dir', 'wiki\\escape')])
def test_contract_rejects_invalid_values(project, key, value):
    cfg = contract()
    cfg[key] = value
    with pytest.raises(ValueError):
        runtime.validate_contract(cfg, project)


@pytest.mark.parametrize('key', ['pattern', 'document_type', 'authority_rank', 'role'])
def test_rule_requires_every_field(project, key):
    cfg = contract()
    del cfg['authority_rules'][0][key]
    with pytest.raises(ValueError):
        runtime.validate_contract(cfg, project)


def test_contract_is_outside_wiki_duplicate_keys_refused(seeded):
    root, cfg = seeded
    assert runtime.read_contract(root, CONTRACT_REL) == cfg
    put(root, '__llm-wiki/contract.json', json.dumps(cfg))
    assert runtime.read_contract(root, CONTRACT_REL) == cfg
    with pytest.raises(ValueError, match='outside the wiki'):
        runtime.read_contract(root, '__llm-wiki/contract.json')
    for unsafe in ('../contract.json', '/abs/contract.json', ''):
        with pytest.raises(ValueError):
            runtime.read_contract(root, unsafe)
    put(root, CONTRACT_REL, '{"schema_version": 1, "schema_version": 1}')
    with pytest.raises(ValueError, match='duplicate'):
        runtime.read_contract(root, CONTRACT_REL)


def test_inventory_excludes_control_generated_secret_and_accepts_files(project):
    cfg = contract()
    cfg['source_roots'] = ['docs', 'docs/decisions/a.md']
    for rel in ['docs/private/a.md', 'docs/generated/a.md', 'docs/.git/a.md', 'docs/.env',
                'docs/secrets/a.md', 'docs/file.pem', 'docs/build/a.md']:
        put(project, rel, '# EXCLUDED\nSecret text.\n')
    out = runtime.scaffold_files(project, cfg, NOW)
    rows = json.loads(out['__llm-wiki/source-registry.json'])['sources']
    assert {r['source_path'] for r in rows} == {'docs/decisions/a.md', 'docs/reports/a.md', 'docs/reference.md'}
    assert len({r['id'] for r in rows}) == len(rows)
    for row in rows:
        assert row['id'] == 'src-' + hashlib.sha256(row['source_path'].encode()).hexdigest()
        assert row['sha256'] == hashlib.sha256((project / row['source_path']).read_bytes()).hexdigest()
    assert all(b'ALPHA-PRIVATE-BODY' not in value for value in out.values())
    # The seed metadata may record titles, not arbitrary original body text.
    assert b'Routing decision' in out['__llm-wiki/source-registry.json']


def test_first_matched_rule_fallback_and_higher_numeric_query_rank(project):
    cfg = contract()
    cfg['authority_rules'].insert(0, {'pattern': 'docs/decisions/**', 'document_type': 'first', 'authority_rank': 5, 'role': 'first-match'})
    result = runtime.query(project, cfg, 'Routing')
    assert [r['authority_rank'] for r in result['results']] == [70, 5, 0]
    assert next(r for r in result['results'] if r['source_path'] == 'docs/decisions/a.md')['document_type'] == 'first'
    assert result['read_coverage']['expected'] == result['read_coverage']['collected'] == 3
    assert not result['metadata_is_approval'] and not result['approval_inferred']
    assert all(r['original_read'] and r['review_status'] == 'original-read-not-semantic-approval' for r in result['results'])


def test_query_reads_body_title_and_separates_binary_readcoverage(seeded):
    root, cfg = seeded
    put(root, 'docs/binary.bin', b'\xff\xfe')
    before = tree(root)
    result = runtime.query(root, cfg, 'ALPHA-PRIVATE-BODY', limit=1)
    assert tree(root) == before
    assert result['returned_count'] == 1
    row = result['results'][0]
    assert row['source_path'] == 'docs/decisions/a.md' and row['original_term_match'] and not row['metadata_match']
    assert result['read_coverage'] == {'expected': 4, 'collected': 3, 'unique': 3, 'read_count': 3,
                                     'unread_count': 1, 'unread': [{'path': 'docs/binary.bin', 'reason': 'non-UTF-8 original; metadata only'}], 'complete': False}
    assert runtime.query(root, cfg, '"Routing decision"')['returned_count'] == 1


def test_sync_observes_current_source_preserves_extensions_and_fixedpoint(seeded):
    root, cfg = seeded
    regpath = root / '__llm-wiki/source-registry.json'
    registry = json.loads(regpath.read_bytes())
    registry['extension'] = {'nested': [1, True]}
    row = next(r for r in registry['sources'] if r['source_path'] == 'docs/decisions/a.md')
    identity, oldhash = row['id'], row['sha256']
    row['verified'] = {'by': 'human:fixture-reviewer', 'at': NOW, 'scope': 'prior content only'}
    row['status'] = 'pending_review'
    row['x-extension'] = {'unknown': ['value']}
    put(root, '__llm-wiki/source-registry.json', json.dumps(registry))
    put(root, 'docs/decisions/a.md', '# Revised routing decision\nCURRENT-ORIGINAL-BODY.\n')
    before = tree(root)
    plan = runtime.sync_plan(root, cfg, NOW)
    assert tree(root) == before
    assert plan['source_snapshot']['docs/decisions/a.md'] != oldhash
    assert plan['report']['source_changes'][0]['registered_sha256'] == oldhash
    merged = json.loads(plan['outputs']['__llm-wiki/source-registry.json'])
    current = next(r for r in merged['sources'] if r['id'] == identity)
    for k in ['verified', 'status', 'x-extension']:
        assert current[k] == row[k]
    assert merged['extension'] == registry['extension']
    assert current['sha256'] == plan['source_snapshot']['docs/decisions/a.md']
    assert b'CURRENT-ORIGINAL-BODY' not in b'\n'.join(plan['outputs'].values())
    assert plan['report']['error_count'] == 0 and plan['report']['preservation_complete']
    fixture_apply(root, plan['outputs'])
    assert runtime.sync_plan(root, cfg, NOW)['report']['changed_files'] == []


@pytest.mark.parametrize('method', [runtime.sync_plan, runtime.format_plan, runtime.query])
def test_missing_registered_source_fails_without_pruning_or_writes(seeded, method):
    root, cfg = seeded
    (root / 'docs/decisions/a.md').unlink()
    before = tree(root)
    with pytest.raises(ValueError, match='missing'):
        method(root, cfg, 'Routing' if method is runtime.query else NOW)
    assert tree(root) == before


def test_hash_retrofit_and_contract_scope_pruning_refused(seeded):
    root, cfg = seeded
    cfg['excluded_roots'].append('docs/decisions')
    with pytest.raises(ValueError, match='pruning refused'):
        runtime.sync_plan(root, cfg, NOW)
    cfg = contract()
    registry = json.loads((root / '__llm-wiki/source-registry.json').read_bytes())
    del registry['sources'][0]['sha256']
    put(root, '__llm-wiki/source-registry.json', json.dumps(registry))
    before = tree(root)
    with pytest.raises(ValueError, match='retrofit'):
        runtime.sync_plan(root, cfg, NOW)
    assert tree(root) == before


@pytest.mark.parametrize('place', ['source-file', 'source-dir', 'wiki-file', 'wiki-dir', 'contract', 'root-alias'])
def test_symlink_and_escape_refused(seeded, tmp_path, place):
    root, cfg = seeded
    if place == 'source-file':
        (root / 'docs/link.md').symlink_to(root / 'docs/decisions/a.md')
    elif place == 'source-dir':
        (root / 'docs/link').symlink_to(root / 'docs/decisions', target_is_directory=True)
    elif place == 'wiki-file':
        (root / '__llm-wiki/link.bin').symlink_to(root / 'docs/decisions/a.md')
    elif place == 'wiki-dir':
        (root / '__llm-wiki/link').symlink_to(root / 'docs', target_is_directory=True)
    elif place == 'contract':
        (root / CONTRACT_REL).unlink()
        (root / CONTRACT_REL).symlink_to(root / 'docs/decisions/a.md')
        with pytest.raises(ValueError, match='symlink'):
            runtime.read_contract(root, CONTRACT_REL)
        return
    else:
        alias = root.parent / (root.name + '-alias')
        alias.symlink_to(root, target_is_directory=True)
        with pytest.raises(ValueError, match='symlink'):
            runtime.format_plan(alias, cfg, NOW)
        return
    with pytest.raises(ValueError, match='symlink'):
        runtime.format_plan(root, cfg, NOW)


def test_explicit_project_root_and_source_lookup_no_producer(seeded):
    root, cfg = seeded
    registry = json.loads((root / '__llm-wiki/source-registry.json').read_bytes())
    identity = registry['sources'][0]['id']
    put(root, '__llm-wiki/concepts/a.md', core.render_markdown({'sources': [identity]}, '# A\nFact.\n'))
    before = tree(root)
    plan = runtime.format_plan(root, cfg, NOW)
    assert tree(root) == before
    meta, _ = core.parse_markdown(plan['outputs']['__llm-wiki/concepts/a.md'].decode())
    assert meta['sources'][0]['resource'] == 'project:' + registry['sources'][0]['source_path']
    assert meta['sources'][0]['sha256'] == registry['sources'][0]['sha256']
    assert not any(n in sys.modules for n in ['audit_response_authority', 'refresh_document_universe', 'migrate_okf_bundle'])


def test_whole_markdown_denominator_preservation_both_index_sides_and_fixedpoint(seeded):
    root, cfg = seeded
    body = '# Legacy root\nHistorical aggregate 7.\n\n' + runtime.INDEX_START + '\nOld listing\n' + runtime.INDEX_END + '\n\nImportant suffix.\n'
    put(root, '__llm-wiki/index.md', core.render_markdown({'okf_version': '0.2'}, body))
    metadata = {'type': 'ExtensionType', 'generated': {'by': 'process:previous', 'at': NOW, 'extra': 1},
                'verified': [{'by': 'human:fixture', 'at': NOW, 'scope': 'historical result'}],
                'sources': [{'id': 'old', 'resource': 'explicit population scope', 'extension': {'a': 1}}],
                'historical': False, 'history_note': 'Known prior note', 'status': 'done', 'x-unknown': [1, {'a': True}]}
    put(root, '__llm-wiki/references/Guide.MD', core.render_markdown(metadata, '# Guide\r\nPast result.\r\n\r\n```md\r\n[[missing]]\r\n```\r\n'))
    put(root, '__llm-wiki/scripts/README.md', '# Script overview\nNot excluded.\n')
    (root / '__llm-wiki/empty').mkdir()
    put(root, '__llm-wiki/opaque.bin', b'\x00\xff')
    before = tree(root)
    original_names = [n for n in runtime._snapshot(root, cfg['wiki_dir']) if n.lower().endswith('.md')]
    plan = runtime.format_plan(root, cfg, NOW)
    report = plan['report']
    assert tree(root) == before
    assert report['expected'] == report['collected'] == report['unique'] == len(original_names)
    assert report['final_expected'] == report['final_collected'] == report['final_unique']
    assert {'__llm-wiki/scripts/README.md', '__llm-wiki/SCHEMA.md', '__llm-wiki/references/Guide.MD'} <= plan['outputs'].keys()
    assert 'empty/' in plan['baseline'] and 'opaque.bin' in plan['baseline']
    assert report['snapshot_unchanged'] and report['preservation_complete'] and report['error_count'] == 0
    output_body = core.parse_markdown(plan['outputs']['__llm-wiki/index.md'].decode())[1]
    assert runtime._outside_block(output_body)[:2] == runtime._outside_block(body)[:2]
    new_meta, new_body = core.parse_markdown(plan['outputs']['__llm-wiki/references/Guide.MD'].decode())
    for key, value in metadata.items():
        if key != 'status':
            assert new_meta[key] == value
    assert new_meta['workflow_status'] == 'done' and 'status' not in new_meta
    assert new_body == core.parse_markdown((root / '__llm-wiki/references/Guide.MD').read_bytes().decode())[1]
    assert report['files'] and json.dumps(report, allow_nan=False)
    fixture_apply(root, plan['outputs'])
    assert runtime.format_plan(root, cfg, NOW)['report']['changed_files'] == []
    assert runtime.check_bundle(root, cfg)['conformant']


@pytest.mark.parametrize('mutation', ['suffix', 'prefix', 'unknown', 'source', 'verified', 'history'])
def test_structurally_valid_mutated_payload_detects_preservation_loss(seeded, mutation):
    root, cfg = seeded
    if mutation in ['suffix', 'prefix']:
        rel = 'index.md'
        before = core.render_markdown({'okf_version': '0.2'}, '# Keep prefix\n' + runtime.INDEX_START + '\nlisting\n' + runtime.INDEX_END + '\nKeep suffix\n')
        after = before.replace('Keep ' + mutation, 'Lost ' + mutation)
    else:
        rel = 'concepts/a.md'
        meta = {'type': 'Custom', 'x-extension': {'nested': 1}, 'historical': True,
                'sources': [{'id': 's', 'resource': 'explicit scope', 'x': 2}],
                'verified': {'by': 'human:fixture', 'at': NOW}}
        before = core.render_markdown(meta, '# A\n')
        if mutation == 'unknown':
            del meta['x-extension']
        elif mutation == 'source':
            meta['sources'][0]['resource'] = 'different scope'
        elif mutation == 'verified':
            del meta['verified']
        else:
            del meta['historical']
        after = core.render_markdown(meta, '# A\n')
    assert not any(i.startswith('error:') for i in core.validate_markdown(root / cfg['wiki_dir'], rel, after))
    guard = runtime.preservation(before, after, root / cfg['wiki_dir'], rel)
    assert not (guard['metadata_preserved'] and guard['body_preserved_except_normalization'])


@pytest.mark.parametrize('name', ['INDEX.MD', 'concepts/Index.md', 'LOG.MD'])
def test_reserved_case_is_explicit_refusal_not_silent_exclusion(seeded, name):
    root, cfg = seeded
    put(root, '__llm-wiki/' + name, '# Reserved ambiguity\n')
    before = tree(root)
    with pytest.raises(ValueError, match='reserved filename case'):
        runtime.format_plan(root, cfg, NOW)
    with pytest.raises(ValueError, match='reserved filename case'):
        runtime.check_bundle(root, cfg)
    assert tree(root) == before


@pytest.mark.parametrize('kind', ['wiki', 'source'])
def test_midplan_snapshot_drift_reported_not_hidden(seeded, kind):
    root, cfg = seeded
    target = '__llm-wiki/SCHEMA.md' if kind == 'wiki' else 'docs/decisions/a.md'
    original = runtime.core.normalize_concept
    changed = []
    def drift(*args, **kwargs):
        if not changed:
            changed.append(True)
            with (root / target).open('ab') as stream:
                stream.write(b'\nConcurrent fixture edit.\n')
        return original(*args, **kwargs)
    with patch.object(runtime.core, 'normalize_concept', side_effect=drift):
        plan = runtime.format_plan(root, cfg, NOW)
    key = 'snapshot_unchanged' if kind == 'wiki' else 'source_snapshot_unchanged'
    assert plan['report'][key] is False and plan['report']['error_count'] > 0
    assert not plan['report']['conformant']


@pytest.mark.parametrize('stamp', ['2026-01-02', '2026-01-02T03:04:05', '2026-02-30T03:04:05+00:00'])
def test_plan_requires_explicit_valid_offset_now(seeded, stamp):
    root, cfg = seeded
    before = tree(root)
    with pytest.raises(ValueError, match='timestamp'):
        runtime.format_plan(root, cfg, stamp)
    assert tree(root) == before


def test_invalid_yaml_has_all_file_diagnostics_and_zero_writes(seeded):
    root, cfg = seeded
    for name, text in [('unsafe.md', '---\ntype: !!python/object/apply:os.system ["false"]\n---\n'),
                       ('duplicate.md', '---\ntype: A\ntype: B\n---\n'),
                       ('conflict.md', core.render_markdown({'type': 1, 'legacy_type': 2}, '# A\n'))]:
        put(root, '__llm-wiki/' + name, text)
    before = tree(root)
    plan = runtime.format_plan(root, cfg, NOW)
    assert tree(root) == before
    assert plan['report']['error_count'] >= 3
    assert plan['report']['expected'] == plan['report']['collected'] == plan['report']['unique']
    assert {r['wiki_path'] for r in plan['report']['files'] if any(i.startswith('error:') for i in r['issues'])} >= {'unsafe.md', 'duplicate.md', 'conflict.md'}


def test_checker_optional_fields_broken_links_and_profile_are_separate(tmp_path):
    (tmp_path / 'docs').mkdir()
    put(tmp_path, '__llm-wiki/a.md', core.render_markdown({'type': 'Custom', 'x-producer': {'a': 1}}, '# A\n[missing](/missing.md)\n'))
    report = runtime.check_bundle(tmp_path, contract())
    assert report['conformant'] and report['error_count'] == 0
    assert report['warning_count'] == 1 and not report['profile_complete']
    put(tmp_path, '__llm-wiki/index.md', core.render_markdown({'okf_version': '0.1'}, '# I\n'))
    put(tmp_path, '__llm-wiki/log.md', '# Log\n')
    report = runtime.check_bundle(tmp_path, contract())
    assert report['conformant'] and not report['profile_complete']


def test_no_package_bytecode_cache_on_documented_no_bytecode_import(tmp_path):
    folder = tmp_path / 'isolated-code'
    folder.mkdir()
    for name in ['wiki_runtime.py', 'okf_bundle.py']:
        (folder / name).write_bytes((SCRIPTS / name).read_bytes())
    code = 'import sys; sys.path.insert(0, sys.argv[1]); import wiki_runtime; print(len(wiki_runtime.__all__))'
    result = subprocess.run([sys.executable, '-B', '-c', code, str(folder)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '9'  # Runtime APIs, shared exclusions and transition validator.
    assert not (folder / '__pycache__').exists()


class TestPureCoreUnittest(unittest.TestCase):
    """unittest-compatible smoke gate, also collected by pytest."""
    def test_safe_roundtrip_and_explicit_history(self):
        meta = {'type': 'Unknown', 'historical': False, 'producer': {'key': [1, True]}}
        body = '# Explicit\r\nNo implied approval.\r\n'
        self.assertEqual(core.parse_markdown(core.render_markdown(meta, body)), (meta, body))


def test_fresh_seed_is_already_format_and_sync_fixedpoint(seeded):
    root, cfg = seeded
    assert runtime.format_plan(root, cfg, NOW)['report']['changed_files'] == []
    assert runtime.sync_plan(root, cfg, NOW)['report']['changed_files'] == []


def test_overlapping_roots_dedup_and_forced_digest_collision_refused(project):
    cfg = contract()
    cfg['source_roots'] = ['docs', 'docs/decisions', 'docs/decisions/a.md']
    assert len(runtime._inventory(project, cfg)[0]) == 3
    with patch.object(runtime, '_digest', return_value='a' * 64):
        with pytest.raises(ValueError, match='collision'):
            runtime.scaffold_files(project, cfg, NOW)


@pytest.mark.parametrize('mutation', ['id', 'path', 'escape'])
def test_registry_duplicate_identity_path_or_escape_is_refused(seeded, mutation):
    root, cfg = seeded
    registry = json.loads((root / '__llm-wiki/source-registry.json').read_bytes())
    if mutation == 'id':
        registry['sources'][1]['id'] = registry['sources'][0]['id']
    elif mutation == 'path':
        registry['sources'][1]['source_path'] = registry['sources'][0]['source_path']
    else:
        registry['sources'][0]['source_path'] = '../outside.md'
    put(root, '__llm-wiki/source-registry.json', json.dumps(registry))
    before = tree(root)
    with pytest.raises(ValueError):
        runtime.sync_plan(root, cfg, NOW)
    assert tree(root) == before


@pytest.mark.parametrize('rel', ['docs/private', 'docs/generated', 'docs/.env'])
def test_excluded_visible_symlinks_are_not_silently_hidden(project, rel):
    (project / rel).symlink_to(project / 'docs/decisions/a.md')
    with pytest.raises(ValueError, match='symlink'):
        runtime.scaffold_files(project, contract(), NOW)


def test_all_source_roots_file_and_dot_supported_no_wiki_self_index(seeded):
    root, cfg = seeded
    cfg['source_roots'] = ['.']
    records, hashes = runtime._inventory(root, cfg)
    assert len(records) == len(hashes) == 3
    assert all(not r['source_path'].startswith(('__llm-wiki/', '.wiki-desk/')) for r in records)
    cfg['source_roots'] = ['docs/decisions/a.md']
    assert set(runtime._inventory(root, cfg)[1]) == {'docs/decisions/a.md'}


def test_sync_registry_md_keeps_unknown_fields_and_outside_generated_body(seeded):
    root, cfg = seeded
    original_path = root / '__llm-wiki/source-registry.md'
    meta, body = core.parse_markdown(original_path.read_bytes().decode())
    meta['type'] = 'Unregistered View'
    meta['verified'] = {'by': 'human:prior-fixture', 'at': NOW, 'scope': 'only old inventory'}
    meta['x-extension'] = {'nested': [2, 3]}
    body = 'User prefix.\n\n' + body + '\nUser suffix.\n'
    put(root, '__llm-wiki/source-registry.md', core.render_markdown(meta, body))
    put(root, 'docs/new.md', '# New original title\nBody must not persist in wiki.\n')
    plan = runtime.sync_plan(root, cfg, NOW)
    new_meta, new_body = core.parse_markdown(plan['outputs']['__llm-wiki/source-registry.md'].decode())
    assert new_meta == meta
    start, end = '<!-- wiki-desk:source-registry:start -->', '<!-- wiki-desk:source-registry:end -->'
    assert runtime._outside_block(body, start, end)[:2] == runtime._outside_block(new_body, start, end)[:2]
    assert plan['report']['preservation_complete'] and plan['report']['error_count'] == 0
    assert b'Body must not persist in wiki.' not in b'\n'.join(plan['outputs'].values())


@pytest.mark.parametrize('bad_markers', [runtime.INDEX_START, runtime.INDEX_END,
                                         runtime.INDEX_END + runtime.INDEX_START,
                                         runtime.INDEX_START + runtime.INDEX_START + runtime.INDEX_END])
def test_malformed_index_markers_block_format_without_write(seeded, bad_markers):
    root, cfg = seeded
    put(root, '__llm-wiki/index.md', core.render_markdown({'okf_version': '0.2'}, '# User index\n' + bad_markers + '\n'))
    before = tree(root)
    plan = runtime.format_plan(root, cfg, NOW)
    assert tree(root) == before
    assert plan['report']['error_count'] > 0 and not plan['report']['preservation_complete']


def test_midcheck_snapshot_drift_is_nonconformant(seeded):
    root, cfg = seeded
    validate = runtime.core.validate_markdown
    mutated = []
    def drift(*args, **kwargs):
        if not mutated:
            mutated.append(True)
            put(root, '__llm-wiki/new-empty.bin', b'')
        return validate(*args, **kwargs)
    with patch.object(runtime.core, 'validate_markdown', side_effect=drift):
        result = runtime.check_bundle(root, cfg)
    assert not result['snapshot_unchanged'] and not result['conformant'] and result['error_count'] > 0


def test_error_reports_remain_json_safe_for_safe_yaml_nonstring_keys(seeded):
    root, cfg = seeded
    put(root, '__llm-wiki/keys.md', '---\ntype: Custom\n.nan: extension\n---\n# Keys\n')
    plan = runtime.format_plan(root, cfg, NOW)
    json.dumps(plan['report'], allow_nan=False)


def test_case_colliding_directory_names_fail_before_planning(seeded):
    root, cfg = seeded
    put(root, '__llm-wiki/Group/a.md', '# A\n')
    put(root, '__llm-wiki/group/b.md', '# B\n')
    before = tree(root)
    with pytest.raises(ValueError, match='case-colliding wiki directory'):
        runtime.format_plan(root, cfg, NOW)
    assert tree(root) == before


def test_report_denominators_separate_markdown_from_registry_json(seeded):
    root, cfg = seeded
    report = runtime.sync_plan(root, cfg, NOW)['report']
    assert report['denominator'] == 'markdown'
    assert report['final_collected'] == len(report['markdown_files'])
    assert report['file_count'] == len(report['files']) == len(report['markdown_files']) + len(report['nonmarkdown_files'])
    assert report['nonmarkdown_files'][0]['wiki_path'] == 'source-registry.json'
