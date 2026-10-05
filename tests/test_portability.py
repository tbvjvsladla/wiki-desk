"""R9 host-neutral test invocation plus multilingual skill metadata."""
import os
from pathlib import Path
import subprocess
import sys

import yaml

PACKAGE = Path(__file__).resolve().parents[1]


def test_unittest_module_import_and_temp_default_are_host_neutral(tmp_path):
    home = tmp_path / 'clean-home'
    home.mkdir()
    env = dict(os.environ, HOME=str(home))
    env.pop('WIKI_DESK_TEST_TMPDIR', None)
    # tempfile uses the caller's TMPDIR; tests must not manufacture a Hermes HOME.
    result = subprocess.run(
        [sys.executable, '-B', '-m', 'unittest',
         'tests.test_release_safety.ReleaseSafetyTests.test_receipt_protection_flag_must_be_boolean_and_status_guarded'],
        cwd=PACKAGE, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Ran 1 test' in result.stderr
    assert not (home / '.hermes').exists()


def test_skill_description_and_version_are_consistent():
    raw = (PACKAGE / 'SKILL.md').read_text(encoding='utf-8')
    metadata = yaml.safe_load(raw.split('---', 2)[1])
    assert metadata['name'] == 'wiki-desk'
    assert metadata['description'].startswith('Use when querying or indexing project knowledge.')
    assert all(term in metadata['description'] for term in ('위키 조회', '근거 문서', '이전에 뭐 했는지'))
    assert metadata['metadata']['version'] == (PACKAGE / 'VERSION').read_text().strip()
    assert 'unittest 사례를 포함한 pytest' in (PACKAGE / 'requirements.txt').read_text()
