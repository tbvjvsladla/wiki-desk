"""R2/R5/R6/R7 public-command regression journeys, synthetic only."""
import json
import shutil
import io
import subprocess
import sys
import tarfile
from pathlib import Path
from tests.test_release_safety import ReleaseFixtureCase
from tests.test_lifecycle import SKILL, tree


class LifecycleExtensionTests(ReleaseFixtureCase):
    def test_cli_explicit_removal_and_relocation_preserve_history_and_id(self):
        self.install()
        registry_path = self.root / '__llm-wiki/source-registry.json'
        original = json.loads(registry_path.read_bytes())
        record = next(row for row in original['sources'] if row['source_path'] == 'docs/a.md')
        (self.root / 'docs/a.md').rename(self.root / 'docs/moved.md')
        self.blocked('sync', '--apply')
        rc, result = self.cli('sync', '--relocate', 'docs/a.md=docs/moved.md')
        self.assertEqual(rc, 0, result)
        self.assertEqual(result['writes'], 0)
        self.assertEqual(self.cli('sync', '--apply', '--relocate', 'docs/a.md=docs/moved.md')[0], 0)
        moved = json.loads(registry_path.read_bytes())
        self.assertEqual(next(row for row in moved['sources'] if row['source_path'] == 'docs/moved.md')['id'], record['id'])
        self.assertEqual(self.cli('sync', '--apply')[0], 0)
        (self.root / 'docs/moved.md').unlink()
        self.blocked('sync', '--apply')
        rc, result = self.cli('sync', '--apply', '--accept-removed', 'docs/moved.md')
        self.assertEqual(rc, 0, result)
        final = json.loads(registry_path.read_bytes())
        self.assertEqual(final['archived_sources'][-1]['source']['id'], record['id'])
        self.assertEqual(self.cli('sync', '--apply')[0], 0)

    def test_literal_transition_options_refuse_without_writes(self):
        self.install()
        for option in ('docs/a.md', 'docs/a.md=../escape', 'docs/a.md=docs/new.md=extra', 'docs/a.md='):
            with self.subTest(option=option):
                self.blocked('sync', '--apply', '--relocate', option)
        self.blocked('sync', '--apply', '--accept-removed', '../escape')

    def legacy_install(self):
        legacy = self.home / 'legacy-package'
        legacy.mkdir()
        if not shutil.which('git') or not (Path(__file__).parents[1] / '.git').exists():
            self.skipTest('Real 1.0 archive regression requires source Git history; no fabricated fixture')
        self.before_legacy = tree(self.root)
        archive = subprocess.check_output(['git', '-C', str(Path(__file__).parents[1]), 'archive', 'b0631f8'])
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(legacy, filter='data')
        self.entry = legacy / 'scripts/wiki_desk.py'
        rc, result = self.cli('install', '--host', 'hermes', '--contract', self.contract, '--apply')
        self.assertEqual(rc, 0, result)
        self.entry = self.package / 'scripts/wiki_desk.py'
        return json.loads((self.root / '.wiki-desk/receipt.json').read_bytes())

    def test_migrate_real_legacy_preserves_wiki_contract_ids_preimages(self):
        old = self.legacy_install()
        wiki = tree(self.root / '__llm-wiki')
        raw = (self.root / '.wiki-desk/contract.json').read_bytes()
        initial = tree(self.root)
        rc, result = self.cli('migrate-state', '--host', 'hermes')
        self.assertEqual(rc, 0, result)
        self.assertEqual(tree(self.root), initial)
        rc, result = self.cli('migrate-state', '--host', 'hermes', '--apply')
        self.assertEqual(rc, 0, result)
        self.assertEqual(tree(self.root / '__llm-wiki'), wiki)
        self.assertEqual((self.root / SKILL / 'project/contract.json').read_bytes(), raw)
        new = json.loads((self.root / SKILL / 'project/receipt.json').read_bytes())
        self.assertEqual(new['schema_version'], 1)
        for rel, record in old['owned_files'].items():
            key = SKILL + '/project/contract.json' if rel == '.wiki-desk/contract.json' else rel
            self.assertEqual(new['owned_files'][key]['preimage'], record['preimage'])
        self.entry = self.root / SKILL / 'scripts/wiki_desk.py'
        self.assertEqual(self.cli('status')[1]['status'], 'PRESENT')
        self.assertEqual(self.cli('remove', '--apply', '--remove-unchanged-wiki')[0], 0)
        self.assertFalse((self.root / SKILL).exists())
        self.assertEqual(tree(self.root), self.before_legacy)

    def test_migrate_refuses_changed_package_collision_extra_admin(self):
        self.legacy_install()
        self.put('.wiki-desk/extra.bin', b'keep user bytes')
        self.blocked('migrate-state', '--host', 'hermes', '--apply')
        (self.root / '.wiki-desk/extra.bin').unlink()
        self.put(SKILL + '/project/contract.json', b'collision')
        self.blocked('migrate-state', '--host', 'hermes', '--apply')
        shutil.rmtree(self.root / SKILL / 'project')
        self.put(SKILL + '/SKILL.md', b'user edited package')
        self.blocked('migrate-state', '--host', 'hermes', '--apply')

    def test_migrate_keeps_sticky_user_wiki_protection(self):
        old = self.legacy_install()
        self.put('__llm-wiki/index.md', b'# User new wiki content\n')
        wiki = tree(self.root / '__llm-wiki')
        rc, result = self.cli('migrate-state', '--host', 'hermes', '--apply')
        self.assertEqual(rc, 0, result)
        self.assertEqual(tree(self.root / '__llm-wiki'), wiki)
        new = json.loads((self.root / SKILL / 'project/receipt.json').read_bytes())
        self.assertTrue(new['owned_files']['__llm-wiki/index.md']['protected_user_content'])
        self.assertEqual(new['owned_files']['__llm-wiki/index.md']['preimage'], old['owned_files']['__llm-wiki/index.md']['preimage'])
        self.entry = self.root / SKILL / 'scripts/wiki_desk.py'
        self.blocked('remove', '--apply', '--remove-unchanged-wiki')

    def test_rebuild_preserves_tracked_package_contract_and_registry(self):
        self.install()
        skill = self.root / SKILL
        registry = (self.root / '__llm-wiki/source-registry.json').read_bytes()
        (skill / 'project/receipt.json').unlink()
        shutil.rmtree(self.root / '__llm-wiki')
        tracked = tree(skill)
        before = tree(self.root)
        rc, result = self.cli('rebuild', '--host', 'hermes')
        self.assertEqual(rc, 0, result)
        self.assertEqual(result['writes'], 0)
        self.assertEqual(tree(self.root), before)
        self.assertEqual(self.cli('rebuild', '--host', 'hermes', '--apply')[0], 0)
        self.assertEqual(self.cli('status')[1]['status'], 'PRESENT')
        (skill / 'project/receipt.json').unlink()  # compare exact tracked checkout
        self.assertEqual(tree(skill), tracked)
        self.assertEqual((self.root / '__llm-wiki/source-registry.json').read_bytes(), registry)

    def test_rebuild_refuses_existing_wiki_or_receipt_or_changed_package(self):
        self.install()
        self.blocked('rebuild', '--host', 'hermes', '--apply')
        (self.root / SKILL / 'project/receipt.json').unlink()
        self.blocked('rebuild', '--host', 'hermes', '--apply')
        shutil.rmtree(self.root / '__llm-wiki')
        self.put(SKILL + '/SKILL.md', b'changed package')
        self.entry = self.package / 'scripts/wiki_desk.py'
        self.blocked('rebuild', '--host', 'hermes', '--apply')

    def test_rebuild_from_git_checkout_keeps_tracked_diff_zero(self):
        if not shutil.which('git'):
            self.skipTest('Git required for tracked-checkout acceptance')
        self.install()
        registry = (self.root / '__llm-wiki/source-registry.json').read_bytes()
        self.put('.gitignore', b'__llm-wiki/\n')
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        subprocess.run(['git', '-C', str(self.root), 'add', 'docs', '.gitignore', SKILL], check=True)
        checkout = self.home / 'tracked-checkout'
        checkout.mkdir()
        subprocess.run(['git', '-C', str(self.root), 'checkout-index', '--all',
                        '--prefix=' + str(checkout) + '/'], check=True)
        subprocess.run(['git', 'init', '-q', str(checkout)], check=True)
        subprocess.run(['git', '-C', str(checkout), 'add', 'docs', '.gitignore', SKILL], check=True)
        self.root = checkout
        self.entry = checkout / SKILL / 'scripts/wiki_desk.py'
        self.assertFalse((checkout / SKILL / 'project/receipt.json').exists())
        self.assertFalse((checkout / '__llm-wiki').exists())
        before = tree(checkout)
        self.assertEqual(self.cli('rebuild', '--host', 'hermes')[0], 0)
        self.assertEqual(tree(checkout), before)
        self.assertEqual(self.cli('rebuild', '--host', 'hermes', '--apply')[0], 0)
        result = subprocess.run(['git', '-C', str(checkout), 'diff', '--exit-code'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((checkout / '__llm-wiki/source-registry.json').read_bytes(), registry)
        self.assertEqual(self.cli('status')[1]['status'], 'PRESENT')
        self.assertFalse((checkout / '.wiki-desk').exists())

    def test_adopt_preserves_all_wiki_bytes_and_modes_and_protects(self):
        self.put('__llm-wiki/user.md', b'# User authored\r\nNo normalization.\r\n').chmod(0o640)
        self.put('__llm-wiki/binary/opaque.bin', b'\x00\xffexact').chmod(0o600)
        (self.root / '__llm-wiki/empty').mkdir(mode=0o700)
        before = tree(self.root / '__llm-wiki')
        project = tree(self.root)
        rc, result = self.cli('adopt', '--host', 'hermes', '--contract', self.contract)
        self.assertEqual(rc, 0, result)
        self.assertEqual(tree(self.root), project)
        rc, result = self.cli('adopt', '--host', 'hermes', '--contract', self.contract, '--apply')
        self.assertEqual(rc, 0, result)
        self.assertEqual(tree(self.root / '__llm-wiki'), before)
        self.entry = self.root / SKILL / 'scripts/wiki_desk.py'
        rc, result = self.cli('status')
        self.assertEqual((rc, result['status']), (0, 'PRESENT'))
        self.assertEqual(set(result['protected_user_files']), {'__llm-wiki/user.md', '__llm-wiki/binary/opaque.bin'})
        self.blocked('remove', '--apply', '--remove-unchanged-wiki')
        self.assertEqual(self.cli('remove', '--apply')[0], 0)
        self.assertEqual(tree(self.root / '__llm-wiki'), before)

    def test_adopt_rejects_proper_source_ancestor_write_zero(self):
        self.put('__llm-wiki/user.md', b'# Preserve user wiki\n')
        for host, prefix in (('hermes', '.agents'), ('claude', '.claude')):
            with self.subTest(host=host):
                source = self.root / prefix
                shutil.copytree(self.package, source)
                self.entry = source / 'scripts/wiki_desk.py'
                for flags in ((), ('--apply',)):
                    result = self.blocked('adopt', '--host', host, '--contract', self.contract, *flags)
                    self.assertIn('Source-package/destination overlap', result['error'])
                verified = subprocess.run([sys.executable, '-B', str(self.entry), 'verify-package'],
                                          capture_output=True, text=True)
                self.assertEqual(verified.returncode, 0, verified.stdout)

    def test_adopt_rejects_proper_source_descendant_write_zero(self):
        self.put('__llm-wiki/user.md', b'# Preserve user wiki\n')
        source = self.root / SKILL / 'source-package'
        shutil.copytree(self.package, source)
        self.entry = source / 'scripts/wiki_desk.py'
        for flags in ((), ('--apply',)):
            result = self.blocked('adopt', '--host', 'hermes', '--contract', self.contract, *flags)
            self.assertIn('Source-package/destination overlap', result['error'])

    def test_adopt_allows_verified_source_equal_to_installed_target(self):
        self.install()
        (self.root / SKILL / 'project/receipt.json').unlink()
        before = tree(self.root / '__llm-wiki')
        initial = tree(self.root)
        self.assertEqual(self.cli('adopt', '--host', 'hermes', '--contract', self.contract)[0], 0)
        self.assertEqual(tree(self.root), initial)
        self.assertEqual(self.cli('adopt', '--host', 'hermes', '--contract', self.contract, '--apply')[0], 0)
        self.assertEqual(tree(self.root / '__llm-wiki'), before)
        self.assertEqual(self.cli('status')[1]['status'], 'PRESENT')

    def test_scan_existing_wiki_is_write_zero(self):
        self.install()
        before = tree(self.root)
        rc, result = self.cli('scan', '--contract', self.contract)
        self.assertEqual(rc, 0, result)
        self.assertTrue(result['wiki_exists'])
        self.assertEqual(result['scaffold_paths'], [])
        self.assertEqual(result['source_count'], 2)
        self.assertEqual(result['writes'], 0)
        self.assertEqual(tree(self.root), before)

    def test_query_empty_has_opt_in_exit_three_and_failures_json(self):
        self.install()
        rc, result = self.cli('query', '--terms', 'NONEXISTENTZZZ')
        self.assertEqual((rc, result['matched_count']), (0, 0))
        rc, result = self.cli('query', '--terms', 'NONEXISTENTZZZ', '--fail-on-empty')
        self.assertEqual((rc, result['matched_count']), (3, 0))
        rc, result = self.cli('query', '--terms', 'Allowed', '--fail-on-empty')
        self.assertEqual(rc, 0, result)
        self.assertGreater(result['matched_count'], 0)
        rc, result = self.cli('query', '--terms', 'Allowed', '--limit', '0', '--fail-on-empty')
        self.assertEqual((rc, result['status']), (2, 'BLOCKED'))
