"""Regression for default no-excerpt and one source exclusion policy."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import json
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import okf_bundle as core
import wiki_runtime as runtime


def contract(source='docs'):
    return {'schema_version': 1, 'project_name': 'Synthetic privacy fixture',
            'wiki_dir': '__llm-wiki', 'source_roots': [source], 'excluded_roots': [],
            'authority_rules': [], 'fallback': {'document_type': 'reference', 'authority_rank': 0, 'role': 'reference'},
            'copy_policy': 'path_reference'}


def put(root, path, text):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding='utf-8')


def test_absent_description_does_not_copy_prose(tmp_path):
    before = '# Private wiki\n\nCONFIDENTIAL_SYNTHETIC_FIRST_PROSE\n\nOther text.\n'
    after = core.normalize_concept(tmp_path, 'concepts/user.md', before, now='2026-01-01T00:00:00+00:00')
    meta, body = core.parse_markdown(after)
    assert meta.get('description') != 'CONFIDENTIAL_SYNTHETIC_FIRST_PROSE'
    assert 'CONFIDENTIAL_SYNTHETIC_FIRST_PROSE' not in json.dumps(meta)
    assert body == before


def test_explicit_description_preserved_without_new_excerpt(tmp_path):
    before = '---\ntype: Custom\ndescription: Explicit producer description\ncustom: {nested: keep}\n---\n# Title\n\nPRIVATE_SYNTHETIC_OTHER_PROSE\n'
    after = core.normalize_concept(tmp_path, 'concepts/user.md', before)
    meta, body = core.parse_markdown(after)
    assert meta['description'] == 'Explicit producer description'
    assert meta['custom'] == {'nested': 'keep'}
    assert 'PRIVATE_SYNTHETIC_OTHER_PROSE' not in json.dumps(meta)
    assert body == core.parse_markdown(before)[1]


def test_private_prose_is_not_spread_to_directory_listing(tmp_path):
    (tmp_path / 'docs').mkdir()
    c = contract()
    for rel, data in runtime.scaffold_files(tmp_path, c, now='2026-01-01T00:00:00+00:00').items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    put(tmp_path, '__llm-wiki/concepts/user.md', '# Private wiki\n\nPRIVATE_PROSE_NO_METADATA_COPY\n')
    result = runtime.format_plan(tmp_path, c, now='2026-01-01T00:00:00+00:00')
    assert result['report']['error_count'] == 0
    assert b'PRIVATE_PROSE_NO_METADATA_COPY' not in result['outputs']['__llm-wiki/concepts/index.md']
    meta, body = core.parse_markdown(result['outputs']['__llm-wiki/concepts/user.md'].decode())
    assert 'PRIVATE_PROSE_NO_METADATA_COPY' not in json.dumps(meta)
    assert 'PRIVATE_PROSE_NO_METADATA_COPY' in body


@pytest.mark.parametrize('source', ['.', 'docs', 'docs/allowed.md'])
def test_shared_source_exclusions_prune_before_snapshot(tmp_path, source):
    put(tmp_path, 'docs/allowed.md', '# Synthetic allowed source\n')
    secret_names = ['.env', 'docs/.env', 'docs/.env.local', 'docs/credentials.json',
                    'docs/cert.key', 'docs/secrets/password.md', 'docs/generated/hidden.md',
                    '.hermes/private.md', '.codex/private.md']
    for name in secret_names:
        put(tmp_path, name, 'SYNTHETIC_NOT_A_REAL_SECRET\n')
    c = contract(source)
    exclusions = runtime.source_exclusions(tmp_path, c)
    assert isinstance(exclusions, tuple)
    for name in secret_names:
        if source != '.' and not (name == source or name.startswith(source + '/')):
            continue
        assert any(name == p or name.startswith(p + '/') for p in exclusions), (name, exclusions)
    assert not any('docs/allowed.md' == p or 'docs/allowed.md'.startswith(p + '/') for p in exclusions)
    assert (tmp_path / '.env').read_text() == 'SYNTHETIC_NOT_A_REAL_SECRET\n'


def test_shared_exclusion_policy_rejects_visible_symlink(tmp_path):
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'outside').mkdir()
    (tmp_path / 'docs/secrets').symlink_to(tmp_path / 'outside', target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        runtime.source_exclusions(tmp_path, contract())
