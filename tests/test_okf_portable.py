"""OKF regression fixtures: timestamps below are not verification evidence."""
import importlib.util
from pathlib import Path
import sys

import pytest

SPEC = importlib.util.spec_from_file_location('okf_bundle', Path(__file__).parents[1] / 'scripts' / 'okf_bundle.py')
assert SPEC is not None and SPEC.loader is not None
core = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = core
SPEC.loader.exec_module(core)
NOW = '2026-10-02T14:00:00+09:00'  # Explicit fixture, never an actual verification.


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / 'bundle'
    (root / 'concepts').mkdir(parents=True)
    (root / 'sources').mkdir()
    (root / 'concepts/target.md').write_text('# target\n', encoding='utf-8')
    (root / 'sources/target.md').write_text('# another target\n', encoding='utf-8')
    (root / 'sources/unique.md').write_text('# unique\n', encoding='utf-8')
    return root


def test_roundtrip_timestamp_unknown_and_exact_body():
    body = '\n# 사실\n\n```python\nx = "[[target]]"\n```\n'
    text = '---\ntype: Unregistered Domain Type\ncreated: 2026-06-09\nlast_checked: 2026-06-09T15:00:00+09:00\nx-extension: {nested: [one, 2]}\n---\n' + body
    meta, actual = core.parse_markdown(text)
    assert meta['created'] == '2026-06-09'
    assert meta['last_checked'] == '2026-06-09T15:00:00+09:00'
    assert actual == body
    assert core.parse_markdown(core.render_markdown(meta, actual)) == (meta, body)


@pytest.mark.parametrize('front', ['[one, two]', 'null', '42', '!!python/object/apply:os.system ["false"]'])
def test_reject_nonmapping_or_unsafe_yaml(front):
    with pytest.raises(ValueError):
        core.parse_markdown('---\n' + front + '\n---\n# X\n')


def test_missing_and_unterminated_frontmatter():
    assert core.parse_markdown('# X\n') == ({}, '# X\n')
    with pytest.raises(ValueError):
        core.parse_markdown('---\ntype: Reference\n')


def test_identity_body_authority_preserved_and_fixedpoint(bundle):
    body = '\n# 실제 제목\n\n과거 승인 성공은 현재 검증이 아니다.\n\n```md\n[[target]]\n```\n'
    old = core.render_markdown({'cycle': 'v3', 'authority_basis': {'rule': 'explicit project policy'}, 'x-data': [1, 2]}, body)
    new = core.normalize_concept(bundle, 'concepts/example.md', old, now=NOW)
    meta, new_body = core.parse_markdown(new)
    assert meta['title'] == '실제 제목'
    assert meta['description'] == 'Knowledge document: concepts/example.md'
    assert '과거 승인 성공' not in meta['description']
    assert meta['cycle'] == 'v3'
    assert meta['authority_basis'] == {'rule': 'explicit project policy'}
    assert meta['x-data'] == [1, 2]
    assert new_body == body
    assert meta['generated'] == {'by': 'process:wiki-desk-okf-migration', 'at': NOW}
    assert 'verified' not in meta and 'author' not in meta
    assert core.normalize_concept(bundle, 'concepts/example.md', new, now=NOW) == new
    assert core.validate_markdown(bundle, 'concepts/example.md', new) == []


def test_legacy_sources_internal_external_unresolved(bundle):
    old = core.render_markdown({'sources': ['src-external', 'unique', 'missing-id', 'src-local']}, '# Fact\nOriginal evidence.\n')
    lookup = {'src-external': {'uri': 'https://example.org/source', 'source_status': 'missing'},
              'src-local': {'source_path': '/known/original.md', 'source_status': 'active'}}
    meta, _ = core.parse_markdown(core.normalize_concept(bundle, 'concepts/a.md', old, lookup))
    entries = {e['id']: e for e in meta['sources']}
    assert entries['src-external']['resource'] == 'https://example.org/source'
    assert entries['src-external']['source_status'] == 'missing'
    assert entries['src-local']['resource'] == '/known/original.md'
    assert entries['unique']['resource'] == '/sources/unique.md'
    assert entries['missing-id']['resolution'] == 'unresolved'
    assert 'source_id:missing-id' in entries['missing-id']['resource']
    assert all('author' not in e for e in entries.values())
    assert all(e['id'] in ['src-external', 'unique', 'missing-id', 'src-local'] for e in entries.values())


def test_existing_source_mapping_and_verification_preserved(bundle):
    meta = {'type': 'Unknown', 'sources': [{'id': 'actual', 'resource': 'scope of observed requests', 'x-signal': 3}],
            'generated': {'by': 'process:original', 'at': NOW},
            'verified': {'by': 'human:actual-fixture-reviewer', 'at': NOW}}
    normalized = core.normalize_concept(bundle, 'concepts/a.md', core.render_markdown(meta, '# A\nA fact.\n'), now=NOW)
    result, _ = core.parse_markdown(normalized)
    for k, v in meta.items():
        assert result[k] == v
    assert core.validate_markdown(bundle, 'concepts/a.md', normalized) == []


@pytest.mark.parametrize('status', ['done', 'ready_for_user_verification', 'blocked'])
def test_workflow_status_separate_from_knowledge_lifecycle(bundle, status):
    text = core.render_markdown({'status': status, 'cycle': 'C4'}, '# Status\nHistorical result.\n')
    meta, _ = core.parse_markdown(core.normalize_concept(bundle, 'concepts/status.md', text))
    assert meta['workflow_status'] == status
    assert 'status' not in meta or meta['status'] in ['draft', 'stable', 'deprecated']
    assert meta['cycle'] == 'C4'


def test_no_generated_without_valid_offset_now(bundle):
    text = '# Example\nObserved fact.\n'
    for now in [None, '2026-10-02', '2026-10-02T14:00:00', '2026-02-30T14:00:00Z']:
        meta, _ = core.parse_markdown(core.normalize_concept(bundle, 'concepts/a.md', text, now=now))
        assert 'generated' not in meta


def test_historical_warm_start_is_not_new_verification(bundle):
    text = core.render_markdown({'status': 'done', 'historical': True, 'history_note': 'Explicit prior observation', 'verified': {'by': 'process:old-fixture', 'at': NOW}}, '# Historical\nPast PASS judgement.\n')
    meta, body = core.parse_markdown(core.normalize_concept(bundle, 'references/warm-start.md', text, now=NOW))
    assert meta['historical'] is True
    assert meta['verified'] == {'by': 'process:old-fixture', 'at': NOW}
    assert body == '# Historical\nPast PASS judgement.\n'


def test_wikilink_known_paths_aliases_fragments_and_code(bundle):
    body = '[[sources/target|Source]] [[target#Part|Local]] [[unique]] [[not-yet-written]]\n`[[unique]]` ``[[unique]]``\n```python\nx="[[unique]]"\n```\n> `[[unique]]`\n>     "[[unique]]"\n    [[unique]]\n'
    result = core.rewrite_wikilinks(bundle, 'concepts/current.md', body)
    assert '[Source](/sources/target.md)' in result
    assert '[Local](/concepts/target.md#Part)' in result
    assert '[unique](/sources/unique.md)' in result
    assert '[not-yet-written]' in result and 'not-yet-written' in result
    for literal in ['`[[unique]]`', '``[[unique]]``', 'x="[[unique]]"', '>     "[[unique]]"', '    [[unique]]']:
        assert literal in result
    assert core.rewrite_wikilinks(bundle, 'concepts/current.md', result) == result
    issues = core.validate_markdown(bundle, 'concepts/current.md', core.render_markdown({'type': 'Reference'}, result))
    assert any(i.startswith('warning:broken-link:') for i in issues)
    assert not any(i.startswith('error:') for i in issues)


def test_index_reserved_root_version_history_and_fixedpoint(bundle):
    text = '# Index\nDocument universe: 3. Historical 2.\n- [[unique]]\n'
    result = core.normalize_index(bundle, 'index.md', text)
    meta, body = core.parse_markdown(result)
    assert set(meta) <= {'okf_version'} and meta.get('okf_version') == '0.2'
    assert 'Document universe: 3. Historical 2.' in body
    assert '[unique](/sources/unique.md)' in body
    assert core.normalize_index(bundle, 'index.md', result) == result
    assert core.parse_markdown(core.normalize_index(bundle, 'concepts/index.md', text))[0] == {}
    assert core.validate_markdown(bundle, 'index.md', result) == []
    with pytest.raises(ValueError):
        core.normalize_concept(bundle, 'index.md', text)


def test_log_grouping_preserves_dates_actions_revisions_and_fixedpoint(bundle):
    old = '# Wiki Log\n\n> Historical append-only convention.\n\n## [2026-06-09] initialize | original\n\n- revision v1: PASS\n\n## [2026-06-12] update | newer\n\n- revision v3\n\n## [2026-06-09] lint | original\n\n- revision v2\n'
    result = core.normalize_log(old)
    assert result.index('## 2026-06-12') < result.index('## 2026-06-09')
    assert result.count('## 2026-06-09') == 1
    for s in ['initialize | original', 'update | newer', 'lint | original', 'revision v1: PASS', 'revision v2', 'revision v3', '> Historical append-only convention.']:
        assert s in result
    assert core.normalize_log(result) == result
    assert core.validate_markdown(bundle, 'log.md', result) == []


@pytest.mark.parametrize('verified', [{'by': 'process:fixture', 'at': NOW}, [{'by': 'process:fixture', 'at': NOW}]])
def test_unknown_types_optional_absence_and_verified_shapes(bundle, verified):
    assert core.validate_markdown(bundle, 'a.md', core.render_markdown({'type': 'Alien Type', 'x-unknown': {'a': 1}}, '')) == []
    assert core.validate_markdown(bundle, 'a.md', core.render_markdown({'type': 'Alien Type', 'verified': verified}, '')) == []


@pytest.mark.parametrize('meta,expected', [({}, 'type'), ({'type': 3}, 'type'), ({'type': 'R', 'sources': ['id']}, 'sources'), ({'type': 'R', 'sources': [{'id': 'x'}]}, 'resource'), ({'type': 'R', 'generated': {'by': 'process:x', 'at': '2026-06-01'}}, 'timestamp'), ({'type': 'R', 'verified': {'by': 'process:x', 'at': '2026-06-01T12:00:00'}}, 'timestamp')])
def test_structural_validation(bundle, meta, expected):
    issues = core.validate_markdown(bundle, 'a.md', core.render_markdown(meta, '# A\n'))
    assert any(i.startswith('error:') and expected in i for i in issues)


def test_reserved_roles_and_local_source_safety_separate(bundle):
    assert any('index' in i for i in core.validate_markdown(bundle, 'index.md', core.render_markdown({'type': 'R'}, '# I\n')))
    assert any('index' in i for i in core.validate_markdown(bundle, 'concepts/index.md', core.render_markdown({'okf_version': '0.2'}, '# I\n')))
    issues = core.validate_markdown(bundle, 'a.md', core.render_markdown({'type': 'R', 'sources': [{'resource': '../../outside.md'}]}, ''))
    assert any(i.startswith('safety:') for i in issues)
    assert not any(i.startswith('error:') for i in issues)


def test_normalizers_do_not_write_sources(bundle):
    before = {str(p.relative_to(bundle)): p.read_bytes() for p in bundle.rglob('*') if p.is_file()}
    core.normalize_concept(bundle, 'concepts/new.md', '# New\n[[unique]]\n', now=NOW)
    core.normalize_index(bundle, 'index.md', '# I\n[[unique]]\n')
    core.validate_markdown(bundle, 'concepts/new.md', '---\ntype: R\n---\n')
    after = {str(p.relative_to(bundle)): p.read_bytes() for p in bundle.rglob('*') if p.is_file()}
    assert before == after


@pytest.mark.parametrize('stamp', ['2026-10-02T00:00:00Z', '2026-10-02T00:00:00.123456-03:30', NOW])
def test_valid_explicit_offsets(bundle, stamp):
    text = core.render_markdown({'type': 'R', 'generated': {'by': 'process:fixture', 'at': stamp}}, '')
    assert core.validate_markdown(bundle, 'a.md', text) == []


@pytest.mark.parametrize('stamp', ['2026-10-02T00:00:00+09:99', '2026-10-02T00:00:00+24:00'])
def test_invalid_offset_is_not_normalized_into_validity(bundle, stamp):
    text = core.render_markdown({'type': 'R', 'verified': {'by': 'process:fixture', 'at': stamp}}, '')
    assert any('timestamp' in x for x in core.validate_markdown(bundle, 'a.md', text))


def test_root_path_priority_ambiguous_basename_and_quoted_examples(bundle):
    (bundle / 'target.md').write_text('# root fixture\n')
    result = core.rewrite_wikilinks(bundle, 'concepts/a.md', '[[target]] [[./target]] "[[unique]]" \'[[unique]]\'\n> ~~~md\n> [[unique]]\n> ~~~\n')
    assert '[target](/target.md)' in result
    assert '[./target](/concepts/target.md)' in result
    assert '"[[unique]]"' in result and "'[[unique]]'" in result
    assert '> [[unique]]' in result
    (bundle / 'target.md').unlink()
    unresolved = core.rewrite_wikilinks(bundle, 'other/a.md', '[[target]]')
    assert unresolved == '[target](/target)'


def test_no_metadata_loss_when_legacy_fields_conflict(bundle):
    meta = {'status': 'done', 'workflow_status': 'blocked', 'legacy_status': 'older'}
    with pytest.raises(ValueError, match='conflict'):
        core.normalize_concept(bundle, 'a.md', core.render_markdown(meta, '# A\n'))
    meta = {'type': 3, 'x-extension': {'old': True}}
    out, _ = core.parse_markdown(core.normalize_concept(bundle, 'a.md', core.render_markdown(meta, '# A\n')))
    assert out['legacy_type'] == 3 and isinstance(out['type'], str)
    assert out['x-extension'] == meta['x-extension']


def test_root_index_does_not_silently_discard_illegal_metadata(bundle):
    with pytest.raises(ValueError):
        core.normalize_index(bundle, 'index.md', core.render_markdown({'type': 'old', 'historical_count': 2}, '# I\n'))
    with pytest.raises(ValueError):
        core.normalize_index(bundle, '../index.md', core.render_markdown({'okf_version': '0.2'}, '# I\n'))


def test_duplicate_keys_rejected_without_touching_global_yaml_loader():
    import yaml
    with pytest.raises(ValueError, match='duplicate'):
        core.parse_markdown('---\ntype: first\ntype: second\n---\n')
    assert isinstance(yaml.safe_load('2026-06-09'), __import__('datetime').date)


def test_source_timestamp_and_usage_window_validation(bundle):
    meta = {'type': 'R', 'sources': [{'resource': 'population of actual requests', 'last_modified': NOW}],
            'usage_window': {'from': NOW, 'to': '2026-10-02'}}
    issues = core.validate_markdown(bundle, 'a.md', core.render_markdown(meta, ''))
    assert issues == ['error:usage_window.to:offset ISO timestamp required']


def test_external_wikilink_and_multiline_inline_code(bundle):
    text = '[[https://example.org/a|Original]]\n`example\n[[unique]]\n`\n[[unique]]\n'
    out = core.rewrite_wikilinks(bundle, 'a.md', text)
    assert '[Original](https://example.org/a)' in out
    assert '`example\n[[unique]]\n`' in out
    assert out.endswith('[unique](/sources/unique.md)\n')


def test_log_code_date_examples_preserved(bundle):
    text = '# Log\n\n## [2026-06-09] update | old\n\n```md\n## 2027-01-01\n- illustrative only\n```\n\n## [2026-06-12] lint | new\n\n- revision PASS\n'
    out = core.normalize_log(text)
    assert '```md\n## 2027-01-01\n- illustrative only\n```' in out
    assert out.index('## 2026-06-12') < out.index('## 2026-06-09')
    assert core.normalize_log(out) == out
    assert core.validate_markdown(bundle, 'log.md', out) == []


# Independent container-fence regression fixtures.
@pytest.mark.parametrize('prefix,indent', [('- ', '  '), ('1. ', '   '), ('> - ', '>   '), ('  - ', '    ')])
@pytest.mark.parametrize('fence', ['~~~', '```', '~~~~', '````'])
def test_list_fenced_graph_examples_are_byte_preserved(tmp_path,prefix,indent,fence):
    (tmp_path/'target.md').write_text('# Target\n')
    example=f'{prefix}{fence}md\n{indent}[[target]]\n{indent}{fence}\n'
    text=example+'\n[[target]]\n'
    actual=core.rewrite_wikilinks(tmp_path,'a.md',text)
    assert actual.startswith(example)
    assert actual.endswith('[target](/target.md)\n')


@pytest.mark.parametrize('fence',['~~~','```'])
def test_list_fenced_log_date_examples_are_preserved(tmp_path,fence):
    example=f'- {fence}md\n  ## 2099-01-01\n  [[target]]\n  {fence}\n'
    text='# Log\n\n## [2026-10-01] update | earlier\n\n'+example+'\n## [2026-10-02] lint | later\n\n- actual action\n'
    actual=core.normalize_log(text)
    assert example.rstrip() in actual
    assert actual.index('## 2026-10-02')<actual.index('## 2026-10-01')
    assert '\n## 2099-01-01\n' not in actual
    assert core.normalize_log(actual)==actual


@pytest.mark.parametrize('fence', ['~~~', '```'])
@pytest.mark.parametrize('prefix,indent', [('', ''), ('- ', '  '), ('123. ', '     '), ('> - ', '>   ')])
def test_overindented_marker_is_not_container_relative_closing(tmp_path, fence, prefix, indent):
    """R1-FENCE-01: four extra spaces are code, not a closing fence."""
    (tmp_path / 'target.md').write_text('# Target\n')
    example = f'{prefix}{fence}md\n{indent}    {fence}\n{indent}[[target]]\n{indent}{fence}\n'
    text = example + '\n[[target]]\n'
    assert core.rewrite_wikilinks(tmp_path, 'a.md', text) == example + '\n[target](/target.md)\n'
    # A fake top-level date must not become a real log group either.
    log_example = example.replace('[[target]]', '## 2099-01-01\n' + indent + 'illustrative only')
    log = '# Log\n\n## [2026-10-01] update | earlier\n\n' + log_example + '\n## [2026-10-02] lint | later\n\n- actual revision\n'
    actual = core.normalize_log(log)
    assert log_example.rstrip('\n') in actual
    assert actual.index('## 2026-10-02') < actual.index('## 2026-10-01')
    assert core.normalize_log(actual) == actual


@pytest.mark.parametrize('fence', ['~~~', '```'])
@pytest.mark.parametrize('prefix,indent', [('- > ', '  > '), ('1. > ', '   > '), ('> - > ', '>   > ')])
def test_ordered_composite_container_fence_protects_only_its_example(tmp_path, fence, prefix, indent):
    """R1-FENCE-02: parse list/quote prefixes in their actual order."""
    (tmp_path / 'target.md').write_text('# Target\n')
    example = f'{prefix}{fence}md\n{indent}[[target]]\n{indent}{fence}\n'
    assert core.rewrite_wikilinks(tmp_path, 'a.md', example + '\n[[target]]\n') == example + '\n[target](/target.md)\n'


@pytest.mark.parametrize('fence', ['~~~', '```'])
@pytest.mark.parametrize('prefix,indent', [('> ', '> '), ('- > ', '  > ')])
def test_quote_container_eof_ends_unclosed_fence(tmp_path, fence, prefix, indent):
    """An absent quote prefix ends the fenced block, even without a closer."""
    (tmp_path / 'target.md').write_text('# Target\n')
    example = f'{prefix}{fence}md\n{indent}[[target]]\n'
    assert core.rewrite_wikilinks(tmp_path, 'a.md', example + '\n[[target]]\n') == example + '\n[target](/target.md)\n'


@pytest.mark.parametrize('fence', ['~~~', '```'])
@pytest.mark.parametrize('extra', [0, 1, 2, 3])
def test_valid_container_relative_closing_indent(tmp_path, fence, extra):
    (tmp_path / 'target.md').write_text('# Target\n')
    example = f'- > {fence}md\n  > [[target]]\n  > {" " * extra}{fence}\n'
    assert core.rewrite_wikilinks(tmp_path, 'a.md', example + '\n[[target]]\n') == example + '\n[target](/target.md)\n'


@pytest.mark.parametrize('fence', ['~~~', '```'])
def test_parent_list_context_and_implicit_list_eof(tmp_path, fence):
    (tmp_path / 'target.md').write_text('# Target\n')
    for example in [
        f'123. parent\n\n     {fence}md\n     [[target]]\n     {fence}\n',
        f'- outer\n  - inner\n    - {fence}md\n      [[target]]\n      {fence}\n',
        f'- {fence}md\n  [[target]]\n',
    ]:
        assert core.rewrite_wikilinks(tmp_path, 'a.md', example + '\n[[target]]\n') == example + '\n[target](/target.md)\n'


@pytest.mark.parametrize("name", ["references/current.md", "references/warm-start.md", "warm_start/a.md"])
def test_generic_paths_do_not_imply_history(bundle, name):
    meta, _ = core.parse_markdown(core.normalize_concept(bundle, name, "# Current\nCurrent fact.\n", now=NOW))
    assert "historical" not in meta and "history_note" not in meta


@pytest.mark.parametrize("historic", [True, False, {"scope": "prior review"}])
def test_explicit_historical_metadata_survives(bundle, historic):
    before = {"type": "ExtensionType", "historical": historic, "history_note": "As recorded"}
    result, _ = core.parse_markdown(core.normalize_concept(bundle, "references/current.md", core.render_markdown(before, "# Current\n"), now=NOW))
    assert all(result[k] == v for k, v in before.items())


@pytest.mark.parametrize('suffix', ['.MD', '.Md', '.mD'])
def test_uppercase_markdown_targets_are_resolved_explicitly(bundle, suffix):
    (bundle / ('sources/Upper' + suffix)).write_text('# Upper\n')
    assert core.rewrite_wikilinks(bundle, 'concepts/a.md', '[[Upper]] [[sources/Upper]]') == (
        '[Upper](/sources/Upper' + suffix + ') [sources/Upper](/sources/Upper' + suffix + ')')
