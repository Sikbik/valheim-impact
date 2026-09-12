"""Export reviewed public evidence summaries, never private source documents.

Only known evidence schemas have adapters. Source strings, artifact records and
provenance records are not rendered. The status manifest supplies reviewed titles,
scope and exact target-stage claims. Source bytes must match its pinned SHA-256.
Known prose summaries are separately hash-pinned, so changed documents need review.
The tracker owner handles publishing. Check mode compares output without writes.
"""
import argparse
from datetime import datetime
import hashlib
from html import escape
import json
import math
import os
from pathlib import Path
import re
import tempfile

try:
    from .export_status import catalog_to_inventory
except ImportError:
    from export_status import catalog_to_inventory

ROOT = Path(__file__).resolve().parents[1]
STAGES = ('authored', 'uv_reviewed', 'native_validated', 'game_fixture_validated', 'approved')
MAX_BYTES = 16 * 1024 * 1024
MAX_TARGETS = 100000
BIOME_NAMES = {'meadows': 'Meadows', 'black-forest': 'Black Forest', 'swamp': 'Swamp',
               'mountains': 'Mountains', 'plains': 'Plains', 'mistlands': 'Mistlands',
               'ashlands': 'Ashlands', 'deep-north': 'Deep North', 'ocean': 'Ocean'}
BIOME_GATES = ('scope_complete', 'world_visual_review', 'weather_and_lod',
               'performance_review', 'final_art_approval')
EVIDENCE_PATHS = {
    'assets/coverage.json', 'assets/provenance.json',
    'docs/evidence/game-mesh-uv.json', 'docs/evidence/roof-uv-review.json',
    'docs/evidence/native-validation.json', 'docs/evidence/game-menu-binding.json',
    'docs/evidence/roof-menu-source.json', 'docs/evidence/default-roof-layout.json',
    'docs/evidence/straw-fringe-authored.json',
    'docs/evidence/cutout-binding-native.json',
}
# Legacy documents support only these already reviewed serialized identities and
# stages. New targets or further completion claims require contributor reviews.
LEGACY_CAB = 'CAB-8923bd833c4171316cf3c761b642c1c8:'
LEGACY_TARGETS = {
    'assets/coverage.json': (None, ()),
    'assets/provenance.json': ('authored', ('3915711535683601241', '-8477877035390755812', '2604212865869356004')),
    'docs/evidence/game-mesh-uv.json': ('uv_reviewed', ('3915711535683601241', '-8477877035390755812', '-8605274158951166907', '5074722651943391187')),
    'docs/evidence/roof-uv-review.json': ('uv_reviewed', ('2604212865869356004', '5860067156705892813', '2790173395324991560', '6499687211232451560')),
    'docs/evidence/native-validation.json': ('native_validated', ('3915711535683601241', '-8477877035390755812', '2604212865869356004')),
    'docs/evidence/game-menu-binding.json': ('game_fixture_validated', ('3915711535683601241', '-8477877035390755812', '2604212865869356004', '5860067156705892813')),
    'docs/evidence/roof-menu-source.json': (None, ('5860067156705892813',)),
    'docs/evidence/default-roof-layout.json': (None, ('7569662044289518567', '5625371641502064416', '-6155225557725131527', '-7768300691103960695', '4913270748202539969')),
    'docs/evidence/straw-fringe-authored.json': ('authored', ('7569662044289518567',)),
    'docs/evidence/cutout-binding-native.json': (None, ()),
}
LEGACY_SUCCESS_FLAGS = {
    'docs/evidence/native-validation.json': 'gpu_base_mip_validation',
    'docs/evidence/game-menu-binding.json': 'threePairProbePassed',
    'docs/evidence/straw-fringe-authored.json': 'authored',
}
CUTOUT_CHECK_NAMES = {
    'worker validated enabled installed profile, explicit rules and mapped owned archive hashes',
    'renderer discovery acquires exact demand for both shared material slots without starting a load',
    'exact identity demand returns immediately, keeps originals and rejects Instance-name mismatch',
    'native async apply shares one owned texture across both renderer material slots and preserves the exact-name miss',
    'opaque eligibility is rechecked before apply and transparent pending demand releases without a write',
    'apply preserves shader, original UV scale and offset, and unrelated texture channel',
    'foreign material change is preserved and releases only its own demand',
    'alpha keyword change after apply restores the owned slot, preserves the foreign keyword and releases demand',
    'disable restores both shared slots before releasing leases and retains deferred-destruction reservation',
    'disable preserves captured UV transforms and unrelated material channel',
    'disable finishes after native release acknowledgement with zero owned allocations and valid originals',
    '1056 distinct surviving materials reclaim unseen records after renderer churn without exhausting the 1024-record cap',
    'new renderer demand remains admitted after more than one registry capacity of material churn',
    'churn fixture shutdown releases all queued demand without native allocation leftovers',
    '2048-slot renderer keeps first-slot demand, avoids material-list expansion and emits one bounded fallback warning',
    'oversized renderer demand cancels without starting a native load',
    'missing material-count capability retains first-slot coverage with one warning',
    'throwing material-count capability falls back once and retains first-slot coverage',
    'eight-slot discovery reaches 128 distinct materials while admitting at most 64 material observations per frame budget',
    'bounded multi-slot discovery releases all fixture-only queued demand without native allocations',
    'process quit restores originals and preserves foreign changes before releasing leases, without claiming native drain',
    'normal process quit suppresses unexpected-removal errors while reporting the remaining owned allocation honestly',
    'dynamic host removal still reports undrained ownership when no process-quit callback occurred',
    'simulated quit fixture finishes its separately pumped native drain with zero retained owned allocations',
    'native material presence/getter APIs expose stored mode blend and depth floats absent from ShaderLab without missing-value reads',
    'alpha-test mutation is a declared and enabled native shader keyword before testing its rejection',
    'alpha-blend mutation is a declared and enabled native shader keyword before testing its rejection',
    'alpha-premultiply mutation is a declared and enabled native shader keyword before testing its rejection',
    'cutout opt-in accepts one exact state and rejects default opaque admission, missing floats and every blended or changed state before demand; matched=1, leases=1',
    'exact cutout discovery retains originals and only queues asynchronous owned demand',
    'native cutout adoption shares one owned texture while preserving cutoff cull saved blend depth values keywords UVs and companion channel',
    'cutoff change during asynchronous preparation rejects adoption and releases pending demand without overwriting the change',
    'applied cutout cull and keyword changes restore only owned texture slots while a foreign texture remains untouched',
    'cutout disable restores the original before releasing its lease and retains deferred native retirement accounting',
    'cutout shutdown reaches acknowledged zero native ownership after restoration',
}
DOCUMENTS = {
    'docs/MOD_PROFILES.md': {
        'sha256': '711715bce0fbda9fcd8e5f8b516670e3e9b3579d69c56810a7f7ab0a1145fc31',
        'title': 'Reversible local mod isolation',
        'scope': 'Recorded development workflow for isolating legacy plugins and restoring them through a journal. This is separate from the public installer.',
        'facts': [
            'The profile tool preserves the existing plugin tree and refuses a running game. It never stops a game process.',
            'Restoration requires the recorded empty active directory and matching saved inventory. It refuses collisions and ambiguous recovery state.',
            'Temporary-directory tests exercise symlinks, sparse packs, collisions, process refusal and interrupted-operation recovery.',
            'Large resource packs receive metadata checks rather than complete content hashes. These tests do not establish live compatibility or performance.',
        ],
        'metrics': [], 'related': None,
    },
    'docs/MILESTONE_03.md': {
        'sha256': '91b7565f72898514d8be9bf87523a6b57f825d2086f432e30f3ebb218480e1fa',
        'title': 'Roof atlas and material-slot milestone',
        'scope': 'Recorded candidate 4 milestone: bounded material-slot discovery and guarded main-menu stone, timber and roof fixtures. No public binary release or placed-world approval.',
        'facts': [
            'The installer updated five files and retained 20 prior texture bundles. Existing mods remained reversibly isolated.',
            'The full roof fixture retained companion materials and original geometry. The original straw cutout still covers much of the top face.',
            'These are dated milestone checks, not the latest test-suite total or a hardware benchmark. Weather, LOD transitions and final art approval remain open.',
        ],
        'metrics': [('Python tests passed at milestone', 107), ('Opt-in GUI tests skipped', 1),
                    ('Runtime assertions passed', 166), ('Native binding checks passed', 24),
                    ('Native textures checked', 22), ('BC3 mip levels checked', 216),
                    ('Owned installed files verified', 28)],
        'related': 'docs/evidence/game-menu-binding.json',
    },
    'docs/ROOF_ATLAS.md': {
        'sha256': 'be7383831b266da1b2b9a6c83ffa8492a002b94f8ba93cbb3e70141d04e13279',
        'title': 'Authored 67-degree roof atlas',
        'scope': 'Atlas fitting and isolated albedo review for the 67-degree roof material family. Default and 45-degree straw materials require separate work.',
        'facts': [
            'Original authored thatch and timber are fitted to measured material regions. The selected atlas submeshes retain original UVs and geometry.',
            'The authored atlas is fully opaque. Three selected submeshes were reviewed in Blender; this is not an assembled building or native shader approval.',
            'Subsequent menu fixtures retain the original companion cutout. A newly authored standard-fringe candidate remains unbound in the installed game.',
            'GPU base-mip checks and serialized mip counts do not measure total VRAM, route performance or the 6 GB hardware target.',
        ],
        'metrics': [('Authored atlas dimensions', '1024 × 1024'), ('Alpha range', '255 to 255'),
                    ('Inspected mesh layouts', 8), ('Selected triangles', 1274),
                    ('Selected layout face corners', 3822), ('Rendered UV face corners', 942),
                    ('Local review dimensions', '3840 × 2160')],
        'related': 'docs/evidence/roof-uv-review.json',
    },
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def public_text(value):
    """Manifest prose only. No source prose is admitted by evidence adapters."""
    if not isinstance(value, str) or not 1 <= len(value) <= 1500:
        raise ValueError('Invalid public text')
    if any(ord(c) < 32 for c in value) or '\\' in value:
        raise ValueError('Private or unsafe public text')
    patterns = (r'(?:^|[\s\"\'(=:>])(?:/|~/|[A-Za-z]:/|local/|build/|reference/|src/|tools/)',
                r'(?i)(?:https?://|file:|steamapps|valheim_Data|\.resS\b|[\w.+-]+@[\w.-]+)',
                r'(?i)(?:\bBearer\s|\b(?:token|password|secret|api_key|apikey)\s*[=:]|gh[pousr]_[A-Za-z0-9]|github_pat_|sk-[A-Za-z0-9])')
    if any(re.search(pattern, value) for pattern in patterns):
        raise ValueError('Private or unsafe public text')
    return value


def output_filename(source_path):
    if source_path not in EVIDENCE_PATHS | DOCUMENTS.keys() and not contribution_path(source_path):
        raise ValueError('No reviewed public adapter for evidence path')
    return source_path.replace('/', '__') + '.html'


def contribution_path(path):
    return isinstance(path, str) and re.fullmatch(r'docs/evidence/contributions/[a-z0-9][a-z0-9_-]{0,100}\.json', path) is not None


def read_source(root, relative, expected_hash=None):
    path = root / relative
    if (not path.is_file() or not path.resolve().is_relative_to(root.resolve()) or
            any(parent.is_symlink() for parent in [path, *path.parents])):
        raise ValueError('Source missing or linked')
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Source metadata exceeds size limit')
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise ValueError('Source metadata exceeds size limit')
    if expected_hash is not None and (not isinstance(expected_hash, str) or
            re.fullmatch('[a-f0-9]{64}', expected_hash) is None or digest(data) != expected_hash):
        raise ValueError('Source evidence hash mismatch')
    return data


def parse_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate metadata key')
            result[key] = value
        return result
    def invalid_constant(_):
        raise ValueError('Non-finite metadata number')
    result = json.loads(data, object_pairs_hook=pairs, parse_constant=invalid_constant)
    if not isinstance(result, dict):
        raise ValueError('Expected metadata object')
    return result


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', value):
        raise ValueError('Expected pinned UTC timestamp')
    datetime.fromisoformat(value.replace('Z', '+00:00'))
    return value


def targets(record):
    result, seen = [], set()
    values = record.get('targets')
    if not isinstance(values, list) or len(values) > MAX_TARGETS:
        raise ValueError('Invalid evidence targets')
    for value in values:
        if not isinstance(value, dict) or set(value) != {'asset_id', 'stages'}:
            raise ValueError('Invalid evidence target fields')
        identity, stages = value['asset_id'], value['stages']
        if (not isinstance(identity, str) or
                not re.fullmatch(r'CAB-[0-9a-f]{32}:(?:0|[1-9][0-9]{0,18}|-[1-9][0-9]{0,18})', identity) or
                not -(2**63) <= int(identity.split(':')[1]) < 2**63 or
                identity in seen or not isinstance(stages, list) or
                any(stage not in STAGES for stage in stages) or len(set(stages)) != len(stages)):
            raise ValueError('Invalid, duplicate or unknown asset target/stage')
        seen.add(identity)
        result.append((identity, ', '.join(stage for stage in STAGES if stage in stages) or 'Reference only'))
    return sorted(result)


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('Expected finite nonnegative numeric metadata')
    return value


def sequence(value, limit=1000):
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError('Expected bounded metadata list')
    return value


def dimensions(value):
    if len(sequence(value, 3)) != 2 or any(type(v) is not int or not 1 <= v <= 65536 for v in value):
        raise ValueError('Invalid image dimensions')
    return ' × '.join(map(str, value))


def alpha_range(value):
    if len(sequence(value, 2)) != 2 or any(type(v) is not int or not 0 <= v <= 255 for v in value) or value[0] > value[1]:
        raise ValueError('Invalid alpha extrema')
    return f'{value[0]} to {value[1]}'


def percent(value):
    if number(value) > 1:
        raise ValueError('Invalid coverage fraction')
    return f'{value * 100:.4f}%'


class Summary:
    def __init__(self):
        self.metrics, self.checks, self.notes = [], [], []

    def metric(self, label, value, formatter=number):
        self.metrics.append((label, str(formatter(value))))

    def check(self, label, value, expected=True):
        if type(value) is not bool:
            raise ValueError('Expected explicit validation boolean')
        self.checks.append((label, 'PASS' if value is expected else 'FAIL'))


def catalog_asset_ids(root, expected_hash=None):
    catalog = parse_json(read_source(Path(root), 'assets/status/catalog.json', expected_hash))
    inventory = catalog_to_inventory(catalog)
    return {asset['id'] for rows in inventory.values() for asset in rows}


def _artifact_digest(root, relative):
    if (not isinstance(relative, str) or not relative.startswith('assets/') or
            any(part in ('', '.', '..') for part in relative.split('/')) or
            '\\' in relative or ':' in relative or relative.lower().endswith('.ress')):
        raise ValueError('Contributor artifacts must be owned assets-relative files')
    public_text(relative)
    path = Path(root) / relative
    if (not path.is_file() or not path.resolve().is_relative_to(Path(root).resolve()) or
            any(parent.is_symlink() for parent in [path, *path.parents])):
        raise ValueError('Contributor artifact missing or linked')
    limit, count, hashed = 64 * 1024 * 1024, 0, hashlib.sha256()
    if path.stat().st_size > limit:
        raise ValueError('Contributor artifact exceeds bounded size')
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            count += len(block)
            if count > limit:
                raise ValueError('Contributor artifact exceeds bounded size')
            hashed.update(block)
    return hashed.hexdigest()


def validate_contribution(root, record, *, known_ids=None):
    """Validate recorded contributor claims, without granting human approval."""
    if not contribution_path(record.get('path')):
        raise ValueError('Contributor review must use the contributions metadata directory')
    expected = record.get('sha256')
    if not isinstance(expected, str) or re.fullmatch('[a-f0-9]{64}', expected) is None:
        raise ValueError('Contributor evidence requires an explicit pinned hash')
    data = parse_json(read_source(Path(root), record['path'], expected))
    kind = data.get('kind')
    fields = {'schema_version', 'kind', 'targets', 'checks', 'artifacts'}
    if kind == 'biome-review':
        fields |= {'biome_id', 'gates'}
    if (kind not in ('asset-review', 'biome-review') or set(data) != fields or
            type(data.get('schema_version')) is not int or data['schema_version'] != 1):
        raise ValueError('Unknown contributor evidence schema or fields')
    source_targets, manifest_targets = targets(data), targets(record)
    if source_targets != manifest_targets:
        raise ValueError('Contributor targets differ from exact manifest target-stage pairs')
    if known_ids is None:
        known_ids = catalog_asset_ids(root)
    if any(identity not in known_ids for identity, _ in source_targets):
        raise ValueError('Unknown asset in contributor targets')
    checks = sequence(data['checks'], 100)
    names = set()
    for check in checks:
        if not isinstance(check, dict) or set(check) != {'name', 'passed'}:
            raise ValueError('Invalid contributor check fields')
        name = public_text(check['name'])
        if len(name) > 200 or name in names or type(check['passed']) is not bool:
            raise ValueError('Invalid or duplicate contributor check')
        names.add(name)
    claims_completion = any(row['stages'] for row in data['targets'])
    if claims_completion and (not checks or not all(check['passed'] for check in checks)):
        raise ValueError('Completion claims require nonempty all-passing checks')
    if kind == 'biome-review':
        if not isinstance(data['biome_id'], str) or data['biome_id'] not in BIOME_NAMES:
            raise ValueError('Unknown review biome')
        if (not isinstance(data['gates'], dict) or set(data['gates']) != set(BIOME_GATES) or
                any(type(value) is not bool for value in data['gates'].values())):
            raise ValueError('Biome review requires all explicit boolean gates')
    artifacts = sequence(data['artifacts'], 100)
    if any('authored' in row['stages'] for row in data['targets']) and not artifacts:
        raise ValueError('Authored claims require a verified owned artifact')
    if artifacts:
        provenance = parse_json(read_source(Path(root), 'assets/provenance.json'))
        registry = sequence(provenance.get('assets'), 10000)
        seen = set()
        for artifact in artifacts:
            if not isinstance(artifact, dict) or set(artifact) != {'path', 'sha256'}:
                raise ValueError('Invalid contributor artifact fields')
            path, expected = artifact['path'], artifact['sha256']
            if not isinstance(path, str) or path in seen:
                raise ValueError('Invalid or duplicate contributor artifact')
            seen.add(path)
            if not isinstance(expected, str) or re.fullmatch('[a-f0-9]{64}', expected) is None:
                raise ValueError('Invalid contributor artifact hash')
            actual = _artifact_digest(root, path)
            if actual != expected:
                raise ValueError('Contributor artifact hash mismatch')
            records = [row for row in registry if isinstance(row, dict) and row.get('dest') == path]
            if (len(records) != 1 or records[0].get('sha256') != expected or
                    records[0].get('original_game_pixels') is not False or
                    ('original_masks_used' in records[0] and records[0]['original_masks_used'] is not False)):
                raise ValueError('Contributor artifact provenance is absent, ambiguous or not original artwork')
    return data


def contribution_summary(data):
    summary = Summary()
    summary.metric('Verified owned artifacts', len(data['artifacts']))
    for row in data['checks']:
        summary.check(row['name'], row['passed'])
    if data['kind'] == 'biome-review':
        for gate in BIOME_GATES:
            summary.check(gate.replace('_', ' ').capitalize(), data['gates'][gate])
        summary.notes.append('Declared biome: ' + BIOME_NAMES[data['biome_id']] + '.')
    summary.notes.append('Human approval remains a contributor review decision recorded through the pull request and code-owner process. Passing CI verifies the record and its artifacts; it does not independently approve artwork or a biome.')
    return summary


def validate_legacy_claims(path, record, data):
    targets(record)
    stage, path_ids = LEGACY_TARGETS[path]
    permitted = {LEGACY_CAB + path_id for path_id in path_ids}
    for row in record['targets']:
        if row['asset_id'] not in permitted or any(claim != stage for claim in row['stages']):
            raise ValueError('Unsupported legacy target or stage; new claims require contributor evidence')
        for claim in row['stages']:
            if claim in data and data[claim] is not True:
                raise ValueError('Legacy source flag contradicts the requested stage')
            success_flag = LEGACY_SUCCESS_FLAGS.get(path)
            if success_flag and data.get(success_flag) is not True:
                raise ValueError('Legacy success flag contradicts the requested stage')


def summarize(path, data):
    """Every copied value is selected here, with fixed labels and strict types."""
    s = Summary()
    if path == 'assets/coverage.json':
        for key, label in [('bundles_scanned', 'Serialized bundles scanned'), ('serialized_materials', 'Materials'),
                           ('serialized_meshes', 'Meshes'), ('serialized_renderers', 'Renderer records'),
                           ('serialized_shaders', 'Shaders'), ('maintex_linked_textures_total', 'Main-texture linked identities'),
                           ('surface_candidate_pool_without_validated_binding_record', 'Heuristic surface candidate pool')]:
            s.metric(label, data[key])
        types = data['serialized_texture_objects_by_type']
        for key in ('Texture2D', 'Texture3D', 'Cubemap', 'Texture2DArray'):
            s.metric(key + ' objects', types[key])
        s.check('Repeated inventory metadata byte-identical', data['repeatability_validation']['metadata_byte_identical'])
        s.notes.append('Serialized counts and filename-based candidate estimates do not measure visible replacement coverage.')
    elif path == 'assets/provenance.json':
        # Deliberately do not traverse or summarize individual provenance records.
        sequence(data['assets'])
        s.notes.append('Authorship progress below comes only from exact target mappings reviewed in the status manifest. Private generation records, prompts and source pointers are omitted.')
    elif path == 'docs/evidence/game-mesh-uv.json':
        s.metric('Review dimensions', data['resolution'], dimensions)
        s.check('Original scene preserved', data['originalScenePreserved'])
        s.check('Original pixels excluded from tracked source', data['trackedOriginalPixels'], False)
        for index, row in enumerate(sequence(data['uvChecks'], 10), 1):
            for key, label in [('original_uv_loops', 'source face corners'), ('blender_uv_loops', 'review face corners'), ('max_uv_error', 'maximum UV error')]:
                s.metric(f'Sample {index}: {label}', row[key])
        for key, label in [('rock_authored', 'Authored stone'), ('timber_authored', 'Authored timber')]:
            row = data['textureChecks'][key]
            s.metric(label + ' dimensions', row['dimensions'], dimensions)
            s.metric(label + ' alpha range', row['alpha_extrema'], alpha_range)
            s.check(label + ' periodic rows', row['periodic_rgb_rows_equal'])
            s.check(label + ' periodic columns', row['periodic_rgb_columns_equal'])
        s.notes.append('Original geometry is retained. Blender albedo review does not validate native shaders, weather, moss, normals or LOD transitions.')
    elif path == 'docs/evidence/roof-uv-review.json':
        s.metric('Review dimensions', data['render_size'], dimensions)
        s.metric('Selected UV face corners', data['selected_uv_face_corners'])
        s.metric('Maximum UV error', data['max_uv_error'])
        s.metric('Authored atlas dimensions', data['texture_checks']['authored_albedo']['size'], dimensions)
        s.metric('Authored atlas alpha range', data['texture_checks']['authored_albedo']['alpha_extrema'], alpha_range)
        s.check('Original scenes preserved', data['original_scenes_preserved'])
        s.check('Open document preserved', data['open_document_path_preserved'])
        s.check('Original reference artifacts excluded from tracked source', data['originalReferenceArtifactsTracked'], False)
        s.notes.append('Three isolated material submeshes were reviewed with Blender base-level sampling. The assembled roof, native mips, weather and LOD transitions need separate evidence.')
    elif path == 'docs/evidence/native-validation.json':
        rows = sequence(data['textures'], 1000)
        s.metric('Texture records checked', len(rows))
        s.check('GPU base-mip validation', data['gpu_base_mip_validation'])
        for index, row in enumerate(rows, 1):
            s.metric(f'Texture {index}: dimensions', [row['width'], row['height']], dimensions)
            s.metric(f'Texture {index}: maximum GPU error, 0 to 255 scale', row['gpu_sampling']['max_error'])
            s.check(f'Texture {index}: serialized payload verified', row['stream_payload_verified'])
            s.check(f'Texture {index}: CPU readback copy disabled', row['cpu_readable'], False)
        s.notes.append('The GPU test covers base mips. This evidence does not independently establish game appearance, native model streaming, total VRAM or frame-time performance.')
    elif path == 'docs/evidence/game-menu-binding.json':
        s.metric('Expected fixture pairs', data['expectedPairs'])
        s.metric('Built fixture pairs', data['builtPairs'])
        s.check('Three-pair menu probe', data['threePairProbePassed'])
        for key, label in [('dontSaveAnything', 'Saving disabled'), ('expectedPluginsOnly', 'Only expected plugins enabled'), ('createdObjectsCleaned', 'Created fixture objects cleaned')]:
            s.check(label, data['menuGuard'][key])
        for index, row in enumerate(sequence(data['pairs'], 10), 1):
            s.metric(f'Pair {index}: replacement dimensions', [row['actualWidth'], row['actualHeight']], dimensions)
            for key, label in [('visiblePixels', 'visible fixture pixels'), ('changedPixels', 'changed fixture pixels'),
                               ('selectedSlot', 'selected slot'), ('materialSlotCount', 'material slots'), ('meshSubmeshes', 'submeshes')]:
                s.metric(f'Pair {index}: {label}', row[key])
            for key, label in [('applied', 'replacement applied'), ('referencePreserved', 'original reference preserved'),
                               ('companionSlotsPreserved', 'companion slots preserved'), ('slotAssignmentsPreserved', 'slot assignments preserved'), ('allSubmeshesPreserved', 'all submeshes preserved')]:
                s.check(f'Pair {index}: {label}', row[key])
        for key, label in [('temporaryProbeRemoved', 'Temporary probe removed'), ('onlyProductionPluginEnabled', 'Production plugin isolated')]:
            s.check(label, data['cleanup'][key])
        s.check('Existing save-tree metadata unchanged', data['preservation']['existingLocalSaveTreeMetadataUnchanged'])
        s.check('No character or world opened', data['preservation']['characterOrWorldOpened'], False)
        for key, label in [('materialLeases', 'Material leases at exit'), ('residentBytes', 'Resident texture bytes at exit'),
                           ('pendingBytes', 'Pending texture bytes at exit'), ('retiringBytes', 'Retiring texture bytes at exit'), ('loaderErrors', 'Loader errors')]:
            s.metric(label, data['exitPayload'][key])
        s.notes.append('This is a guarded menu fixture using retained original geometry. Original roof fringe remains visible. Normal exit is not an asynchronous drain proof. No world-route, hardware or final art approval is implied.')
    elif path == 'docs/evidence/roof-menu-source.json':
        s.metric('Original mesh vertices', data['vertices'])
        s.metric('Selected material slot', data['selected_slot'])
        for index, value in enumerate(sequence(data['submesh_triangles'], 8)):
            s.metric(f'Submesh {index}: triangles', value)
        s.notes.append('This metadata maps the retained original roof mesh to its serialized identity. It does not author a model or prove native model streaming.')
    elif path == 'docs/evidence/default-roof-layout.json':
        for index, row in enumerate(sequence(data['textures'], 3), 1):
            s.metric(f'Original reference {index}: dimensions', row['dimensions'], dimensions)
            alpha = row['decoded_rgba_alpha']
            s.metric(f'Original reference {index}: alpha range', alpha['alpha_extrema'], alpha_range)
            for key, label in [('pixels', 'texels'), ('alpha_zero', 'zero-alpha texels'), ('alpha_255', 'opaque texels'), ('alpha_intermediate', 'intermediate-alpha texels')]:
                s.metric(f'Original reference {index}: {label}', alpha[key])
            s.metric(f'Original reference {index}: coverage at cutoff 0.69', alpha['coverage_at_saved_cutoff_0_69'], percent)
        s.check('Original reference artifacts excluded from tracked source', data['originalReferenceArtifactsTracked'], False)
        s.notes.append('Whole-image alpha and UV preparation only. Material-specific texture assignment leaves sibling opaque or fringe slots untouched. Coverage measures texels, not visible screen coverage.')
    elif path == 'docs/evidence/straw-fringe-authored.json':
        s.metric('Original dimensions', data['original_dimensions'], dimensions)
        candidate = data['candidate']
        s.metric('Authored candidate dimensions', candidate['dimensions'], dimensions)
        s.metric('Candidate alpha range', candidate['alpha_extrema'], alpha_range)
        s.metric('Alpha cutoff', candidate['cutoff'])
        s.metric('Candidate base-level passing coverage', candidate['coverage'], percent)
        s.check('No original game pixels used', data['original_game_pixels'], False)
        s.check('No original game masks used', data['original_masks_used'], False)
        s.notes.append('This historical review measured ordinary mips of the initial standard candidate. The 2 × 2 and 1 × 1 levels had zero passing texels at cutoff 0.69. Later material evidence is recorded separately; this record grants only the initial authored stage.')
    elif path == 'docs/evidence/cutout-binding-native.json':
        s.check('Staged fixture completed', data['completed'])
        s.check('Staged fixture passed', data['passed'])
        s.check('No cleanup pending', data['cleanupPending'], False)
        rows = sequence(data['checks'], 100)
        s.metric('Recognized fixture checks', len(rows))
        seen = set()
        for row in rows:
            name = row['name']
            if not isinstance(name, str) or name not in CUTOUT_CHECK_NAMES or name in seen:
                raise ValueError('Unknown or duplicate validation check name')
            seen.add(name)
            s.check(name, row['passed'])
        samples = sequence(data['samples'], 10000)
        if not samples:
            raise ValueError('Final native sample missing')
        for key, label in [('pending', 'Final pending texture bytes'), ('resident', 'Final resident texture bytes'),
                           ('retiring', 'Final retiring texture bytes'), ('leases', 'Final material leases')]:
            s.metric(label, samples[-1][key])
        s.notes.append('Staging-only material and native-loader fixtures. Installed candidate 4 and its allowlist remain unchanged. This is not validation of the authored fringe, original game shaders, UVs, a world scene or representative hardware.')
    return s


STYLE = '''body{margin:0;background:#f7f3e8;color:#223d39;font:16px/1.6 system-ui,sans-serif}main{max-width:960px;margin:auto;padding:32px 24px 64px}a{color:#52633b}h1,h2{color:#123e3a;line-height:1.2}h1{font-size:clamp(1.8rem,5vw,2.6rem)}h2{margin-top:2rem;font-size:1.25rem}table{border-collapse:collapse;width:100%;background:#fffdf6;margin:16px 0}th,td{text-align:left;vertical-align:top;padding:10px 12px;border-bottom:1px solid #d6d8c5;overflow-wrap:anywhere}th{color:#384b2f}.meta{overflow-wrap:anywhere;color:#506156}.note{border-left:4px solid #7c8851;padding-left:16px}code{overflow-wrap:anywhere;font-size:.88em}@media(max-width:600px){main{padding:20px 14px}th,td{padding:8px}table{font-size:.9rem}}'''


def table(headers, rows):
    if not rows:
        return '<p>No completion targets recorded for this summary.</p>'
    return '<table><thead><tr>' + ''.join('<th scope="col">' + escape(str(v)) + '</th>' for v in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + escape(str(v)) + '</td>' for v in row) + '</tr>' for row in rows) + '</tbody></table>'


def render(title, scope, source_hash, snapshot, target_rows, summary):
    title, scope = public_text(title), public_text(scope)
    body = '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + escape(title) + ' | Valheim Impact evidence</title><style>' + STYLE + '</style></head><body><main><nav><a href="../">Back to the project tracker</a></nav><h1>' + escape(title) + '</h1><p>' + escape(scope) + '</p>'
    body += '<p class="meta">Reviewed snapshot: ' + escape(snapshot) + '<br>Source metadata SHA-256: <code>' + escape(source_hash) + '</code></p>'
    body += '<h2>Exact target claims</h2>' + table(('Serialized asset ID', 'Recorded stages'), target_rows)
    if summary.metrics:
        body += '<h2>Recorded measurements</h2>' + table(('Measurement', 'Value'), summary.metrics)
    if summary.checks:
        body += '<h2>Recognized validation checks</h2>' + table(('Check', 'Recorded result'), summary.checks)
    body += '<h2>Scope and limits</h2>' + ''.join('<p class="note">' + escape(note) + '</p>' for note in summary.notes)
    body += '<p>Stages are independent and limited to the stated evidence. Retained original geometry is not an authored model. Inventory counts do not measure visible overhaul coverage. This public summary contains no original imagery, geometry or private source documents.</p></main></body></html>\n'
    return body


def evidence_page(root, record, snapshot, *, known_ids=None):
    path = record.get('path')
    if contribution_path(path):
        data = validate_contribution(root, record, known_ids=known_ids)
        return render(record['title'], record['scope'], record['sha256'], timestamp(snapshot),
                      targets(record), contribution_summary(data))
    if path not in EVIDENCE_PATHS:
        raise ValueError('No reviewed public adapter for evidence path')
    data = parse_json(read_source(Path(root), path, record.get('sha256')))
    validate_legacy_claims(path, record, data)
    try:
        summary = summarize(path, data)
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError('Evidence schema differs from reviewed adapter') from error
    scope = public_text(record['scope'])
    if path == 'docs/evidence/straw-fringe-authored.json':
        scope = 'Historical initial 512 RGBA candidate for the standard straw-fringe material. No copied game pixels or masks. This record predates the separate UV and native sampling review.'
    return render(record['title'], scope, record['sha256'], timestamp(snapshot), targets(record), summary)


def build_pages(root, manifest):
    if type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1:
        raise ValueError('Unsupported status manifest schema')
    snapshot = timestamp(manifest.get('snapshot_at'))
    pages, paths, ids = {}, {}, set()
    known_ids = None
    if any(contribution_path(record.get('path')) for record in sequence(manifest.get('evidence'), 1000)):
        expected = manifest.get('catalog_sha256')
        if not isinstance(expected, str) or re.fullmatch('[a-f0-9]{64}', expected) is None:
            raise ValueError('Contributor export requires pinned catalog_sha256')
        known_ids = catalog_asset_ids(root, expected)
    for record in sequence(manifest.get('evidence'), 1000):
        identity, path = record.get('id'), record.get('path')
        if (not isinstance(identity, str) or not re.fullmatch('[a-z0-9][a-z0-9-]*', identity)
                or identity in ids or path in paths):
            raise ValueError('Invalid or duplicate evidence identity/path')
        ids.add(identity)
        pages[output_filename(path)] = evidence_page(root, record, snapshot, known_ids=known_ids)
        paths[path] = record
    for path, doc in DOCUMENTS.items():
        read_source(Path(root), path, doc['sha256'])
        summary = Summary()
        summary.metrics, summary.notes = doc['metrics'], list(doc['facts'])
        related = doc['related']
        if related is not None and related not in paths:
            raise ValueError('Required milestone target evidence missing')
        rows = targets(paths[related]) if related else []
        if related:
            summary.notes.append('The exact target stages above refer to the related pinned validation record in this snapshot. The milestone summary adds no independent asset completion claims.')
        pages[output_filename(path)] = render(doc['title'], doc['scope'], doc['sha256'], snapshot, rows, summary)
    return dict(sorted(pages.items()))


def export_pages(root, manifest_path, output, *, check=False):
    root, manifest_path, output = map(Path, (root, manifest_path, output))
    # Validate every input and render every page before changing existing output.
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    try:
        relative = str(manifest_path.relative_to(root))
    except ValueError as error:
        raise ValueError('Manifest must be within repository') from error
    pages = build_pages(root, parse_json(read_source(root, relative)))
    if not output.is_absolute():
        output = root / output
    resolved = output.resolve()
    site_output = root.resolve() / 'status-site/public/evidence'
    if ((not resolved.is_relative_to((root / 'local').resolve()) and resolved != site_output) or
            resolved == (root / 'local').resolve() or
            any(path.is_symlink() for path in [output, *output.parents])):
        raise ValueError('Output must be an unlinked local directory or the tracker evidence directory')
    if any(parent.exists() and not parent.is_dir() for parent in output.parents):
        raise ValueError('Output parent is not a directory')
    if output.exists() and (not output.is_dir() or any(path.name not in pages or not path.is_file() or path.is_symlink() for path in output.iterdir())):
        raise ValueError('Unexpected or linked files in output directory')
    if check:
        for filename, html in pages.items():
            path = output / filename
            if not path.is_file() or path.read_bytes() != html.encode('utf-8'):
                raise ValueError('Public evidence summary is stale: ' + filename)
        return {'pages': len(pages), 'current': True}
    output.mkdir(parents=True, exist_ok=True)
    for filename, html in pages.items():
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=output, prefix='.evidence-', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(html.encode('utf-8'))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, output / filename)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
    return {'pages': len(pages), 'bytes': sum(len(value.encode('utf-8')) for value in pages.values()),
            'files': [{'name': key, 'sha256': digest(value.encode('utf-8'))} for key, value in pages.items()]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--manifest', type=Path, default=Path('assets/status/manifest.json'))
    parser.add_argument('--output', type=Path, default=Path('local/tracker-public-evidence'))
    parser.add_argument('--check', action='store_true', help='Read-only comparison against the requested output directory')
    args = parser.parse_args()
    print(json.dumps(export_pages(args.root.resolve(), args.manifest, args.output, check=args.check), sort_keys=True))


if __name__ == '__main__':
    main()
