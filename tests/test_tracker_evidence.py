"""Boundary tests for the public evidence export, using synthetic private data."""
import copy
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import tempfile
import unittest

from tools import export_tracker_evidence as exporter


class Links(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links, self.tags = [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.links.extend(value for key, value in attrs if key in ('href', 'src'))


class PublicEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = 'docs/evidence/straw-fringe-authored.json'
        self.asset_id = 'CAB-8923bd833c4171316cf3c761b642c1c8:7569662044289518567'
        self.data = {
            'authored': True,
            'candidate': {'dimensions': [512, 512], 'alpha_extrema': [0, 255],
                          'cutoff': 0.69, 'coverage': 0.5492820739746094},
            'original_dimensions': [64, 64], 'original_game_pixels': False,
            'original_masks_used': False,
            'scope': '/home/private/person@example.com secret-token-123',
            'evidence': {'private/source': 'credential'},
            'artifacts': {'local/extracted.obj': {'vertices': [1, 2, 3]}},
        }
        self.record = {'id': 'straw-fringe-authored', 'path': self.path,
                       'title': 'Straw <b> & "review"',
                       'scope': 'Authored candidate only; native and game checks pending.',
                       'targets': [{'asset_id': self.asset_id, 'stages': ['authored']}]}
        self.write_source()

    def write_source(self):
        content = json.dumps(self.data).encode()
        path = self.root / self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        self.record['sha256'] = hashlib.sha256(content).hexdigest()

    def page(self):
        return exporter.evidence_page(self.root, self.record, '2026-09-12T19:28:00Z')

    def test_only_allowlisted_metadata_is_published_with_exact_targets(self):
        page = self.page()
        for private in ('/home/', 'person@example.com', 'secret-token', 'credential',
                        'extracted.obj', 'vertices', 'private/source'):
            self.assertNotIn(private, page)
        self.assertIn(self.record['sha256'], page)
        self.assertIn(self.asset_id, page)
        self.assertIn('authored', page)
        self.assertIn('512', page)
        self.assertIn('54.9282%', page)
        self.assertNotIn('native_validated', page)

    def test_html_text_escaped_and_only_root_backlink(self):
        page = self.page()
        parsed = Links(page)
        self.assertEqual(parsed.links, ['../'])
        self.assertNotIn('b', parsed.tags)
        self.assertNotIn('script', parsed.tags)
        self.assertIn('Straw &lt;b&gt; &amp; &quot;review&quot;', page)

    def test_false_validation_is_reported_as_failure_not_silently_passed(self):
        self.data['original_masks_used'] = True
        self.write_source()
        page = self.page()
        self.assertIn('No original game masks used', page)
        self.assertIn('FAIL', page)

    def test_changed_evidence_or_symlink_cannot_be_certified(self):
        original = (self.root / self.path).read_bytes()
        (self.root / self.path).write_bytes(original + b' ')
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.page()
        destination = self.root / 'private.json'
        destination.write_bytes(original)
        (self.root / self.path).unlink()
        (self.root / self.path).symlink_to(destination)
        with self.assertRaisesRegex(ValueError, 'linked'):
            self.page()

    def test_allowlisted_scalar_cannot_smuggle_text_or_boolean_as_number(self):
        for value in ('/home/private/image.png', True, float('nan')):
            with self.subTest(value=value):
                self.data['candidate']['coverage'] = value
                self.write_source()
                with self.assertRaises(ValueError):
                    self.page()

    def test_private_manifest_strings_and_malformed_targets_are_rejected(self):
        valid = copy.deepcopy(self.record)
        for value in ('/home/private', 'C:\\private', 'person@example.com',
                      'https://private.example/token', 'local/extracted.png',
                      'token=secret', 'Bearer abcdef', 'a\nprivate line'):
            with self.subTest(value=value):
                self.record = copy.deepcopy(valid)
                self.record['scope'] = value
                with self.assertRaises(ValueError):
                    self.page()
        for target in ({'asset_id': 'not-an-identity', 'stages': ['authored']},
                       {'asset_id': self.asset_id, 'stages': ['unknown']},
                       {'asset_id': self.asset_id, 'stages': ['authored', 'authored']}):
            self.record = copy.deepcopy(valid)
            self.record['targets'] = [target]
            with self.assertRaises(ValueError):
                self.page()

    def test_reference_target_does_not_gain_completion(self):
        self.record['targets'][0]['stages'] = []
        page = self.page()
        self.assertIn('Reference only', page)
        self.assertNotIn('<td>authored</td>', page)

    def test_legacy_straw_cannot_claim_native_or_approved_stages(self):
        self.data.update(native_validated=False, approved=False)
        self.write_source()
        self.record['targets'][0]['stages'] = ['authored', 'native_validated', 'approved']
        with self.assertRaisesRegex(ValueError, 'legacy'):
            self.page()

    def test_legacy_source_stage_false_cannot_support_its_baseline_claim(self):
        self.data['authored'] = False
        self.write_source()
        with self.assertRaisesRegex(ValueError, 'contradict'):
            self.page()

    def test_old_uv_fixture_cannot_be_attached_to_an_unrelated_known_asset(self):
        path = 'docs/evidence/game-mesh-uv.json'
        source_root = Path(__file__).resolve().parents[1]
        self.data = json.loads((source_root / path).read_bytes())
        self.path = path
        self.record['path'] = path
        self.record['targets'] = [{'asset_id': self.asset_id, 'stages': ['uv_reviewed']}]
        self.write_source()
        with self.assertRaisesRegex(ValueError, 'legacy'):
            self.page()

    def test_filename_contract_and_unknown_source_refusal(self):
        self.assertEqual(exporter.output_filename(self.path),
                         'docs__evidence__straw-fringe-authored.json.html')
        for path in ('../private.json', 'docs/evidence/new.json', '/home/private.json'):
            with self.subTest(path=path):
                self.record['path'] = path
                with self.assertRaises(ValueError):
                    self.page()

    def test_cutout_only_recognized_check_names_can_be_published(self):
        self.path = 'docs/evidence/cutout-binding-native.json'
        self.record['path'] = self.path
        self.record['targets'] = []
        self.data = {'completed': True, 'passed': True, 'cleanupPending': False,
                     'checks': [{'name': 'cutout shutdown reaches acknowledged zero native ownership after restoration', 'passed': True}],
                     'samples': [{'pending': 0, 'resident': 0, 'retiring': 0, 'leases': 0}],
                     'source_hashes': {'/home/private/source': 'secret'},
                     'error': 'person@example.com'}
        self.write_source()
        page = self.page()
        self.assertIn('cutout shutdown reaches acknowledged zero native ownership after restoration', page)
        self.assertNotIn('person@example.com', page)
        self.assertNotIn('/home/', page)
        self.data['checks'][0]['name'] = '/home/private/debug-data'
        self.write_source()
        with self.assertRaises(ValueError):
            self.page()


class CompleteExportTests(unittest.TestCase):
    """Run the real exporter against a copied, pinned metadata snapshot."""
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        source_root = Path(__file__).resolve().parents[1]
        self.manifest_path = self.root / 'assets/status/manifest.json'
        self.manifest = json.loads((source_root / 'assets/status/manifest.json').read_bytes())
        self.copy_inputs(source_root)
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.write_manifest()
        self.output = self.root / 'local/tracker-public-evidence'

    def copy_inputs(self, source_root):
        paths = {record['path']: record['sha256'] for record in self.manifest['evidence']}
        paths.update({path: document['sha256'] for path, document in exporter.DOCUMENTS.items()})
        paths['assets/status/catalog.json'] = self.manifest['catalog_sha256']
        paths.setdefault('assets/provenance.json', None)
        content = {path: exporter.read_source(source_root, path, expected) for path, expected in paths.items()}
        for record in self.manifest['evidence']:
            if exporter.contribution_path(record['path']):
                review = exporter.validate_contribution(source_root, record)
                for artifact in review['artifacts']:
                    data = (source_root / artifact['path']).read_bytes()
                    self.assertEqual(hashlib.sha256(data).hexdigest(), artifact['sha256'])
                    content[artifact['path']] = data
        for path, data in content.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def write_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest))

    def export(self):
        return exporter.export_pages(self.root, self.manifest_path, self.output)

    def test_every_pinned_source_has_reproducible_private_free_page(self):
        first = self.export()
        contents = {p.name: p.read_bytes() for p in self.output.iterdir()}
        self.assertEqual(first['pages'], len(self.manifest['evidence']) + len(exporter.DOCUMENTS))
        expected = {e['path'].replace('/', '__') + '.html' for e in self.manifest['evidence']}
        expected.update(path.replace('/', '__') + '.html' for path in exporter.DOCUMENTS)
        self.assertEqual(set(contents), expected)
        for name, data in contents.items():
            page = data.decode()
            self.assertEqual(Links(page).links, ['../'], name)
            self.assertIsNone(re.search(r'(?i)/home/|local/|steamapps|valheim_Data|\.resS|src/|tools/|source_hashes|renderPath|[\w.+-]+@[\w.-]+', page), name)
        for evidence in self.manifest['evidence']:
            page = contents[evidence['path'].replace('/', '__') + '.html'].decode()
            self.assertIn(evidence['sha256'], page)
            for target in evidence['targets']:
                self.assertIn(target['asset_id'], page)
                for stage in target['stages']:
                    self.assertIn(stage, page)
        self.assertEqual(self.export(), first)
        self.assertEqual({p.name: p.read_bytes() for p in self.output.iterdir()}, contents)

    def test_changed_evidence_preserves_entire_previous_export(self):
        self.export()
        previous = {p.name: p.read_bytes() for p in self.output.iterdir()}
        source = self.root / self.manifest['evidence'][-1]['path']
        source.write_bytes(source.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.export()
        self.assertEqual({p.name: p.read_bytes() for p in self.output.iterdir()}, previous)

    def test_changed_curated_document_and_duplicate_evidence_are_rejected(self):
        document = self.root / 'docs/MOD_PROFILES.md'
        original = document.read_bytes()
        document.write_bytes(original + b'Private changed prose')
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.export()
        self.assertFalse(self.output.exists())
        document.write_bytes(original)
        self.manifest['evidence'].append(self.manifest['evidence'][0])
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.export()
        self.assertFalse(self.output.exists())

    def test_symlink_output_and_unexpected_old_files_cannot_be_published(self):
        external = self.root / 'outside'
        external.mkdir()
        self.output.parent.mkdir()
        self.output.symlink_to(external, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.export()
        self.assertEqual(list(external.iterdir()), [])
        self.output.unlink()
        self.output.mkdir()
        private = self.output / 'old-private-source.json'
        private.write_bytes(b'private stale document')
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            self.export()
        self.assertEqual(list(self.output.iterdir()), [private])
        self.assertEqual(private.read_bytes(), b'private stale document')

    def test_check_mode_detects_stale_site_output_without_writing(self):
        self.output = self.root / 'status-site/public/evidence'
        with self.assertRaisesRegex(ValueError, 'stale'):
            exporter.export_pages(self.root, self.manifest_path, self.output, check=True)
        self.assertFalse(self.output.exists())
        self.export()
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.output.iterdir()}
        exporter.export_pages(self.root, self.manifest_path, self.output, check=True)
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.output.iterdir()}, before)
        changed = next(iter(before))
        changed.write_bytes(b'stale page')
        with self.assertRaisesRegex(ValueError, 'stale'):
            exporter.export_pages(self.root, self.manifest_path, self.output, check=True)
        self.assertEqual(changed.read_bytes(), b'stale page')

    def test_next_contribution_copies_required_inputs_and_exports_fourteenth_page(self):
        # Build a real source fixture containing one new authored review, then
        # copy it through the same setup path used by future repository tests.
        repository = Path(__file__).resolve().parents[1]
        catalog_path = self.root / 'assets/status/catalog.json'
        catalog_path.write_bytes((repository / 'assets/status/catalog.json').read_bytes())
        artifact_path = 'assets/authored/contributor-fixture.png'
        artifact = self.root / artifact_path
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b'owned artwork fixture content')
        artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
        provenance_path = self.root / 'assets/provenance.json'
        provenance = json.loads(provenance_path.read_bytes())
        provenance['assets'].append({'dest': artifact_path, 'sha256': artifact_hash, 'original_game_pixels': False})
        provenance_path.write_text(json.dumps(provenance))
        for record in self.manifest['evidence']:
            if record['path'] == 'assets/provenance.json':
                record['sha256'] = hashlib.sha256(provenance_path.read_bytes()).hexdigest()
        exact_id = json.loads(catalog_path.read_bytes())['assets'][0]['id']
        review = {'schema_version': 1, 'kind': 'asset-review',
                  'targets': [{'asset_id': exact_id, 'stages': ['authored']}],
                  'checks': [{'name': 'Artwork checks passed', 'passed': True}],
                  'artifacts': [{'path': artifact_path, 'sha256': artifact_hash}]}
        review_path = 'docs/evidence/contributions/contributor-fixture.json'
        source = self.root / review_path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(json.dumps(review))
        # Keep this regression at the first contribution boundary even after
        # additional contributor records are added to the real repository.
        self.manifest['evidence'] = [record for record in self.manifest['evidence']
                                     if not exporter.contribution_path(record['path'])]
        self.manifest['evidence'].append({'id': 'contributor-fixture', 'path': review_path,
                                         'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                                         'title': 'Contributor fixture', 'scope': 'One exact authored target.',
                                         'targets': review['targets']})
        source_root = self.root
        self.root = source_root / 'copied-contributor-workspace'
        self.copy_inputs(source_root)
        self.manifest_path = self.root / 'assets/status/manifest.json'
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.write_manifest()
        self.output = self.root / 'local/tracker-public-evidence'
        result = self.export()
        self.assertEqual(result['pages'], 14)
        page = self.output / 'docs__evidence__contributions__contributor-fixture.json.html'
        self.assertTrue(page.is_file())
        self.assertIn(exact_id, page.read_text())
        self.assertEqual((self.root / artifact_path).read_bytes(), b'owned artwork fixture content')
        self.assertEqual(exporter.export_pages(self.root, self.manifest_path, self.output, check=True),
                         {'pages': 14, 'current': True})


class ContributionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(exporter, 'validate_contribution'), 'contributor evidence adapter is required')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.asset_id = 'CAB-11111111111111111111111111111111:1'
        self.source_path = 'docs/evidence/contributions/roof-review.json'
        self.artifact = self.root / 'assets/authored/roof.png'
        self.artifact.parent.mkdir(parents=True)
        self.artifact.write_bytes(b'original artwork fixture')
        self.artifact_hash = hashlib.sha256(self.artifact.read_bytes()).hexdigest()
        self.source = {'schema_version': 1, 'kind': 'asset-review',
                       'targets': [{'asset_id': self.asset_id, 'stages': ['authored']}],
                       'checks': [{'name': 'UV <edges> & cutoff check', 'passed': True}],
                       'artifacts': [{'path': 'assets/authored/roof.png', 'sha256': self.artifact_hash}]}
        self.record = {'id': 'roof-review', 'path': self.source_path, 'title': 'Contributor roof review',
                       'scope': 'One original artwork candidate.', 'targets': copy.deepcopy(self.source['targets'])}
        catalog = {'schema_version': 1, 'inventory_sha256': 'a'*64, 'assets': [
            {'id': self.asset_id, 'kind': 'texture', 'source_name': 'roof', 'object_name': 'roof',
             'category': 'building', 'dimensions': [64, 64], 'container_paths': ['Assets/Pieces/roof.png']}]}
        (self.root / 'assets/status').mkdir()
        (self.root / 'assets/status/catalog.json').write_text(json.dumps(catalog))
        self.provenance = {'schema_version': 1, 'assets': [
            {'dest': 'assets/authored/roof.png', 'sha256': self.artifact_hash, 'original_game_pixels': False}]}
        self.write()

    def write(self):
        path = self.root / self.source_path
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(self.source).encode()
        path.write_bytes(content)
        self.record['sha256'] = hashlib.sha256(content).hexdigest()
        (self.root / 'assets/provenance.json').write_text(json.dumps(self.provenance))

    def page(self):
        self.write()
        return exporter.evidence_page(self.root, self.record, '2026-09-12T19:00:00Z')

    def test_generic_review_has_escaped_checks_and_exact_manifest_targets(self):
        page = self.page()
        self.assertIn('UV &lt;edges&gt; &amp; cutoff check', page)
        self.assertIn(self.asset_id, page)
        self.assertIn('authored', page)
        self.assertEqual(Links(page).links, ['../'])
        self.assertIn('Human approval', page)
        self.assertEqual(exporter.output_filename(self.source_path),
                         'docs__evidence__contributions__roof-review.json.html')

    def test_targets_cannot_promote_beyond_exact_manifest_claims(self):
        self.source['targets'][0]['stages'].append('approved')
        with self.assertRaisesRegex(ValueError, 'target'):
            self.page()
        self.source['targets'] = copy.deepcopy(self.record['targets'])
        self.source['targets'][0]['asset_id'] = 'CAB-22222222222222222222222222222222:1'
        self.record['targets'] = copy.deepcopy(self.source['targets'])
        with self.assertRaisesRegex(ValueError, 'Unknown asset'):
            self.page()

    def test_contribution_requires_explicit_unchanged_source_hash(self):
        del self.record['sha256']
        with self.assertRaisesRegex(ValueError, 'hash'):
            exporter.validate_contribution(self.root, self.record)
        self.write()
        path = self.root / self.source_path
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'hash'):
            exporter.validate_contribution(self.root, self.record)

    def test_completion_requires_explicit_nonempty_all_passing_checks(self):
        for checks in ([], [{'name': 'measured', 'passed': False}], [{'name': 'measured', 'passed': 1}],
                       [{'name': '/home/private', 'passed': True}], [{'name': 'x'*201, 'passed': True}]):
            with self.subTest(checks=checks):
                self.source['checks'] = checks
                with self.assertRaises(ValueError):
                    self.page()

    def test_authored_requires_hashed_owned_artifact(self):
        self.source['artifacts'] = []
        with self.assertRaisesRegex(ValueError, 'artifact'):
            self.page()
        self.source['targets'][0]['stages'] = ['uv_reviewed']
        self.record['targets'] = copy.deepcopy(self.source['targets'])
        self.assertIn('uv_reviewed', self.page())

    def test_ambiguous_or_original_artifact_provenance_and_changed_hash_fail(self):
        valid = copy.deepcopy(self.provenance)
        for records in ([], valid['assets'] * 2,
                        [dict(valid['assets'][0], original_game_pixels=True)],
                        [dict(valid['assets'][0], original_game_pixels=0)],
                        [dict(valid['assets'][0], original_masks_used=True)],
                        [dict(valid['assets'][0], sha256='b'*64)]):
            with self.subTest(records=records):
                self.provenance['assets'] = records
                with self.assertRaisesRegex(ValueError, 'provenance'):
                    self.page()
        self.provenance = valid
        self.artifact.write_bytes(b'changed content')
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.page()

    def test_artifacts_cannot_escape_or_follow_links(self):
        for path in ('local/reference.png', 'assets/../private.png', '/home/private.png', 'assets/reference.resS'):
            with self.subTest(path=path):
                self.source['artifacts'][0]['path'] = path
                with self.assertRaises(ValueError):
                    self.page()
        self.source['artifacts'][0]['path'] = 'assets/authored/roof.png'
        saved = self.root / 'original.png'
        self.artifact.rename(saved)
        self.artifact.symlink_to(saved)
        with self.assertRaisesRegex(ValueError, 'linked'):
            self.page()

    def test_unknown_fields_kind_version_and_reviewer_identity_fail_closed(self):
        valid = copy.deepcopy(self.source)
        for key, value in [('pixels', [1, 2]), ('reviewer', 'person@example.com'), ('kind', 'unknown'),
                           ('schema_version', True), ('schema_version', 2)]:
            with self.subTest(key=key):
                self.source = copy.deepcopy(valid)
                self.source[key] = value
                with self.assertRaises(ValueError):
                    self.page()


if __name__ == '__main__':
    unittest.main()
