"""R4 explicit reconciliation; no real source or operational state writes."""
import sys
sys.dont_write_bytecode = True
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import okf_bundle as core
import wiki_runtime as runtime

NOW = '2026-01-02T03:04:05+00:00'


def put(root, rel, data):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)


def apply_fixture(root, outputs):
    for rel, data in outputs.items():
        put(root, rel, data)


def registry(root):
    return json.loads((root / '__llm-wiki/source-registry.json').read_bytes())


def planned(plan):
    return json.loads(plan['outputs']['__llm-wiki/source-registry.json'])


@pytest.fixture
def seeded(tmp_path):
    cfg = {'schema_version': 1, 'project_name': 'Synthetic reconciliation', 'wiki_dir': '__llm-wiki',
           'source_roots': ['docs'], 'excluded_roots': ['docs/private'], 'source_suffixes': ['.md'],
           'authority_rules': [], 'fallback': {'document_type': 'reference', 'authority_rank': 0, 'role': 'reference'},
           'copy_policy': 'path_reference'}
    put(tmp_path, 'docs/a.md', '# A\nSYNTHETIC_SOURCE_BODY\n')
    put(tmp_path, 'docs/b.md', '# B\nSYNTHETIC_SOURCE_BODY\n')
    apply_fixture(tmp_path, runtime.scaffold_files(tmp_path, cfg, NOW))
    old = registry(tmp_path)
    old['producer'] = {'nested': [True, 3]}
    old['sources'][0].update({'x-extension': {'nested': ['keep']},
                              'verified': {'by': 'human:fixture', 'at': NOW, 'scope': 'old content only'},
                              'status': 'pending_review'})
    put(tmp_path, '__llm-wiki/source-registry.json', json.dumps(old))
    return tmp_path, cfg, old


def test_default_missing_guard_unchanged(seeded):
    root, cfg, old = seeded
    (root / 'docs/a.md').unlink()
    for method, arg in ((runtime.sync_plan, NOW), (runtime.format_plan, NOW), (runtime.query, 'A')):
        with pytest.raises(ValueError, match='missing'):
            method(root, cfg, arg)
    assert registry(root) == old


def test_accept_removed_archives_full_metadata_only_requested_path(seeded):
    root, cfg, old = seeded
    (root / 'docs/a.md').unlink()
    plan = runtime.sync_plan(root, cfg, NOW, accept_removed=('docs/a.md',))
    new = planned(plan)
    assert new['sources'] == [old['sources'][1]]
    assert new['archived_sources'] == [{'source': old['sources'][0], 'reason': 'removed', 'at': NOW}]
    assert new['producer'] == old['producer']
    assert plan['source_snapshot'].keys() == {'docs/b.md'}
    assert plan['report']['conformant'] and plan['report']['source_snapshot_unchanged']
    assert runtime.validate_registry_transition(old, new, accept_removed=('docs/a.md',), now=NOW) is True
    assert registry(root) == old  # planner writes zero
    apply_fixture(root, plan['outputs'])
    assert runtime.sync_plan(root, cfg, NOW)['report']['changed_files'] == []
    result = runtime.query(root, cfg, 'SYNTHETIC_SOURCE_BODY')
    assert result['source_count'] == 1 and not result['approval_inferred']


def test_relocate_preserves_id_extensions_updates_observations_and_lookup(seeded):
    root, cfg, old = seeded
    (root / 'docs/a.md').rename(root / 'docs/moved.md')
    put(root, 'docs/moved.md', '# Moved title\nNew synthetic original.\n')
    plan = runtime.sync_plan(root, cfg, NOW, relocations=(('docs/a.md', 'docs/moved.md'),))
    new = planned(plan)
    row = next(row for row in new['sources'] if row['source_path'] == 'docs/moved.md')
    assert row['id'] == old['sources'][0]['id']
    for key in ('x-extension', 'verified', 'status'):
        assert row[key] == old['sources'][0][key]
    assert row['title'] == 'Moved title' and row['sha256'] == plan['source_snapshot']['docs/moved.md']
    assert new['archived_sources'] == [{'source': old['sources'][0], 'reason': 'relocated', 'at': NOW, 'destination': 'docs/moved.md'}]
    assert runtime._lookup(new)[row['id']]['resource'] == 'project:docs/moved.md'
    assert runtime.validate_registry_transition(old, new, relocations=(('docs/a.md', 'docs/moved.md'),), now=NOW)
    apply_fixture(root, plan['outputs'])
    put(root, '__llm-wiki/concepts/a.md', core.render_markdown({'sources': [row['id']]}, '# Concept\n'))
    fmt = runtime.format_plan(root, cfg, NOW)
    meta, _ = core.parse_markdown(fmt['outputs']['__llm-wiki/concepts/a.md'].decode())
    assert meta['sources'][0]['resource'] == 'project:docs/moved.md'
    assert runtime.query(root, cfg, row['id'])['results'][0]['source_path'] == 'docs/moved.md'


def test_history_append_only_across_two_moves_then_removal(seeded):
    root, cfg, old = seeded
    (root / 'docs/a.md').rename(root / 'docs/c.md')
    first = runtime.sync_plan(root, cfg, NOW, relocations=(('docs/a.md', 'docs/c.md'),))
    apply_fixture(root, first['outputs'])
    (root / 'docs/c.md').rename(root / 'docs/d.md')
    second = runtime.sync_plan(root, cfg, NOW, relocations=(('docs/c.md', 'docs/d.md'),))
    assert planned(second)['archived_sources'][:1] == planned(first)['archived_sources']
    apply_fixture(root, second['outputs'])
    (root / 'docs/d.md').unlink()
    third = runtime.sync_plan(root, cfg, NOW, accept_removed=('docs/d.md',))
    assert planned(third)['archived_sources'][:2] == planned(second)['archived_sources']
    assert len(planned(third)['archived_sources']) == 3
    assert all(event['source']['id'] == old['sources'][0]['id'] for event in planned(third)['archived_sources'])


def test_out_of_scope_explicit_removal_and_move(seeded):
    root, cfg, old = seeded
    cfg['source_roots'] = ['docs/b.md']
    with pytest.raises(ValueError, match='pruning refused'):
        runtime.sync_plan(root, cfg, NOW)
    assert planned(runtime.sync_plan(root, cfg, NOW, accept_removed=('docs/a.md',)))['archived_sources'][0]['source'] == old['sources'][0]
    cfg['source_roots'] = ['docs/b.md', 'docs/new.md']
    put(root, 'docs/new.md', '# New location\n')
    assert next(row for row in planned(runtime.sync_plan(root, cfg, NOW, relocations=(('docs/a.md', 'docs/new.md'),)))['sources'] if row['source_path'] == 'docs/new.md')['id'] == old['sources'][0]['id']


def test_unresolved_extra_missing_is_refused(seeded):
    root, cfg, old = seeded
    (root / 'docs/a.md').unlink()
    (root / 'docs/b.md').unlink()
    with pytest.raises(ValueError, match='missing'):
        runtime.sync_plan(root, cfg, NOW, accept_removed=('docs/a.md',))
    assert registry(root) == old


@pytest.mark.parametrize('removed,moves', [
    (('docs/a.md', 'docs/a.md'), ()),
    (('docs/a.md',), (('docs/a.md', 'docs/c.md'),)),
    ((), (('docs/a.md', 'docs/c.md'), ('docs/a.md', 'docs/d.md'))),
    ((), (('docs/a.md', 'docs/c.md'), ('docs/b.md', 'docs/c.md'))),
    ((), (('docs/a.md', 'docs/b.md'),)),
    ((), (('docs/a.md', '../outside.md'),)),
    ((), (('docs/a.md', 'docs/private/c.md'),)),
    ((), (('docs/a.md', 'docs/c.json'),)),
    (('docs/private/no.md',), ()),
    (('docs/no.md',), ()),
    ((), (('docs/a.md', 'docs/a.md'),)),
    ((), (('docs/a.md', 'docs/c.md'), ('docs/c.md', 'docs/d.md'))),
])
def test_invalid_reconciliation_is_write_zero(seeded, removed, moves):
    root, cfg, old = seeded
    (root / 'docs/a.md').unlink()
    put(root, 'docs/c.md', '# C\n')
    put(root, 'docs/d.md', '# D\n')
    with pytest.raises(ValueError):
        runtime.sync_plan(root, cfg, NOW, accept_removed=removed, relocations=moves)
    assert registry(root) == old


def test_existing_in_scope_source_cannot_be_silently_removed_or_relocated(seeded):
    root, cfg, old = seeded
    put(root, 'docs/c.md', '# C\n')
    for kwargs in ({'accept_removed': ('docs/a.md',)}, {'relocations': (('docs/a.md', 'docs/c.md'),)}):
        with pytest.raises(ValueError):
            runtime.sync_plan(root, cfg, NOW, **kwargs)


@pytest.mark.parametrize('mutation', ['top-metadata', 'top-new', 'extension', 'identity', 'lost-active', 'history', 'reason', 'time', 'destination', 'extra-history', 'new-id'])
def test_independent_transition_validator_rejects_forged_valid_json(seeded, mutation):
    root, cfg, old = seeded
    (root / 'docs/a.md').rename(root / 'docs/c.md')
    new = planned(runtime.sync_plan(root, cfg, NOW, relocations=(('docs/a.md', 'docs/c.md'),)))
    current = next(row for row in new['sources'] if row['source_path'] == 'docs/c.md')
    if mutation == 'top-metadata': new['producer'] = {}
    elif mutation == 'top-new': new['unexpected'] = True
    elif mutation == 'extension': current['x-extension'] = {}
    elif mutation == 'identity': current['id'] = 'replacement'
    elif mutation == 'lost-active': new['sources'] = [current]
    elif mutation == 'history': del new['archived_sources'][0]['source']['verified']
    elif mutation == 'reason': new['archived_sources'][0]['reason'] = 'approved'
    elif mutation == 'time': new['archived_sources'][0]['at'] = '2026-01-02'
    elif mutation == 'destination': new['archived_sources'][0]['destination'] = 'docs/other.md'
    elif mutation == 'extra-history': new['archived_sources'].append(copy.deepcopy(new['archived_sources'][0]))
    else:
        put(root, 'docs/new.md', '# New\n')
        row = runtime._inventory(root, cfg)[0][-1]
        row['id'] = 'forged'
        new['sources'].append(row)
    with pytest.raises(ValueError):
        runtime.validate_registry_transition(old, new, relocations=(('docs/a.md', 'docs/c.md'),), now=NOW)


def test_symlink_old_or_destination_remains_refused(seeded):
    root, cfg, old = seeded
    (root / 'docs/a.md').unlink()
    (root / 'docs/a.md').symlink_to(root / 'docs/b.md')
    with pytest.raises(ValueError, match='symlink'):
        runtime.sync_plan(root, cfg, NOW, accept_removed=('docs/a.md',))


def test_unknown_history_extension_preserved_and_malformed_history_refused(seeded):
    root, cfg, old = seeded
    old['archived_sources'] = [{'source': {'id': 'historical'}, 'reason': 'legacy', 'x-producer': [1]}]
    put(root, '__llm-wiki/source-registry.json', json.dumps(old))
    (root / 'docs/a.md').unlink()
    plan = runtime.sync_plan(root, cfg, NOW, accept_removed=('docs/a.md',))
    assert planned(plan)['archived_sources'][0] == old['archived_sources'][0]
    old['archived_sources'] = {'not': 'list'}
    put(root, '__llm-wiki/source-registry.json', json.dumps(old))
    with pytest.raises(ValueError, match='archived_sources'):
        runtime.sync_plan(root, cfg, NOW, accept_removed=('docs/a.md',))


def test_arbitrary_registered_id_and_legacy_history_survive_move(seeded):
    root, cfg, old = seeded
    old['sources'][0]['id'] = 'producer:opaque/source identity'
    old['archived_sources'] = [False, 'legacy event', {'unknown': {'value': 1}}]
    put(root, '__llm-wiki/source-registry.json', json.dumps(old))
    (root / 'docs/a.md').rename(root / 'docs/c.md')
    new = planned(runtime.sync_plan(root, cfg, NOW, relocations=[['docs/a.md', 'docs/c.md']]))
    assert next(row for row in new['sources'] if row['source_path'] == 'docs/c.md')['id'] == old['sources'][0]['id']
    assert new['archived_sources'][:-1] == old['archived_sources']
    assert runtime.validate_registry_transition(old, new, relocations=(('docs/a.md', 'docs/c.md'),)) is True


@pytest.mark.parametrize('remove_old', [False, True])
def test_registered_id_collision_with_new_path_digest_is_refused(seeded, remove_old):
    root, cfg, old = seeded
    old['sources'][0]['id'] = 'src-' + runtime._digest(b'docs/new.md')
    put(root, '__llm-wiki/source-registry.json', json.dumps(old))
    put(root, 'docs/new.md', '# New source\n')
    if remove_old:
        (root / 'docs/a.md').unlink()
    with pytest.raises(ValueError, match='collision|noncolliding'):
        runtime.sync_plan(root, cfg, NOW, accept_removed=('docs/a.md',) if remove_old else ())
    assert registry(root) == old


def test_destination_symlink_and_unresolved_scope_loss_refused(seeded):
    root, cfg, old = seeded
    (root / 'docs/a.md').unlink()
    (root / 'docs/c.md').symlink_to(root / 'docs/b.md')
    with pytest.raises(ValueError, match='symlink'):
        runtime.sync_plan(root, cfg, NOW, relocations=(('docs/a.md', 'docs/c.md'),))
    (root / 'docs/c.md').unlink()
    cfg['excluded_roots'].append('docs/b.md')
    with pytest.raises(ValueError, match='pruning refused'):
        runtime.sync_plan(root, cfg, NOW, accept_removed=('docs/a.md',))
    assert registry(root) == old


def test_transition_validator_rejects_type_equal_metadata_and_new_extension(seeded):
    root, cfg, old = seeded
    (root / 'docs/a.md').unlink()
    new = planned(runtime.sync_plan(root, cfg, NOW, accept_removed=('docs/a.md',)))
    typed = copy.deepcopy(new)
    typed['producer']['nested'][0] = 1  # Python equality alone treats True == 1.
    extended = copy.deepcopy(new)
    extended['sources'][0]['new-extension'] = 'not an observation'
    for forged in (typed, extended):
        with pytest.raises(ValueError):
            runtime.validate_registry_transition(old, forged, accept_removed=('docs/a.md',), now=NOW)
