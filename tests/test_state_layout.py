"""R1/R3 installed-state regressions, exercised with actual CLI copies."""
import json
import shutil
import subprocess
import sys
from pathlib import Path
from tests.test_release_safety import ReleaseFixtureCase
from tests.test_lifecycle import SKILL, tree
import package_manifest as manifest
import wiki_desk as desk


class StateLayoutTests(ReleaseFixtureCase):
    def test_fresh_state_is_in_skill_and_installed_package_verifies(self):
        self.install()
        self.assertFalse((self.root / '.wiki-desk').exists())
        self.assertTrue((self.root / SKILL / 'project/contract.json').is_file())
        self.assertTrue((self.root / SKILL / 'project/receipt.json').is_file())
        result = subprocess.run([sys.executable, '-B', str(self.entry), 'verify-package'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue(json.loads(result.stdout)['verified'])

    def test_legacy_state_is_explicitly_blocked(self):
        self.install()
        self.put('.wiki-desk/contract.json', b'{}')
        for action, args in [('status', []), ('sync', []), ('check', []), ('query', ['--terms', 'source'])]:
            with self.subTest(action=action):
                self.assertIn('Legacy 1.0.x', self.blocked(action, *args)['error'])

    def test_source_reader_requires_exactly_one_unique_host_destination(self):
        self.install()
        self.entry = self.package / 'scripts/wiki_desk.py'
        self.assertEqual(self.cli('status')[1]['status'], 'PRESENT')
        shutil.copytree(self.root / SKILL / 'project', self.root / desk.HOSTS['claude'] / 'project')
        self.assertIn('exactly one', self.blocked('status')['error'])

    def test_plain_remove_preserves_state_and_wiki(self):
        self.install()
        before = tree(self.root / '__llm-wiki')
        self.assertEqual(self.cli('remove', '--apply')[0], 0)
        self.assertEqual(before, tree(self.root / '__llm-wiki'))
        self.assertTrue((self.root / SKILL / 'project/contract.json').is_file())
        self.assertTrue((self.root / SKILL / 'project/receipt.json').is_file())
        self.entry = self.package / 'scripts/wiki_desk.py'
        self.assertFalse(self.cli('status')[1]['installed'])

    def test_ordinary_permission_difference_is_not_drift_or_protection(self):
        self.install()
        (self.root / SKILL / 'SKILL.md').chmod(0o664)
        self.assertEqual(self.cli('status')[1]['status'], 'PRESENT')
        self.assertEqual(self.cli('sync', '--apply')[0], 0)
        receipt = json.loads((self.root / SKILL / 'project/receipt.json').read_bytes())
        self.assertFalse(receipt['owned_files'][SKILL + '/SKILL.md'].get('protected_user_content'))
        self.assertEqual(self.cli('remove', '--apply', '--remove-unchanged-wiki')[0], 0)

    def test_executable_or_content_difference_remains_drift(self):
        self.install()
        target = self.root / SKILL / 'SKILL.md'
        target.chmod(0o755)
        self.assertEqual(self.cli('status')[1]['status'], 'DRIFT')
        target.chmod(0o644)
        target.write_bytes(b'user changed package')
        self.assertEqual(self.cli('status')[1]['status'], 'DRIFT')

    def test_only_top_level_project_is_excluded(self):
        self.assertTrue(manifest.excluded('project/contract.json'))
        self.assertFalse(manifest.excluded('support/project/contract.json'))

    def test_gitignore_tracks_contract_but_ignores_receipt(self):
        subprocess.run(['git', 'init', '-q', str(self.package)], check=True)
        result = subprocess.run(['git', '-C', str(self.package), 'check-ignore', '--no-index', 'project/contract.json', 'project/receipt.json'], capture_output=True, text=True)
        self.assertEqual(result.stdout.splitlines(), ['project/receipt.json'])
