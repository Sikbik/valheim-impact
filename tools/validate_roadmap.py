"""Validate explicit biome approval and report counts within declared scopes.

Passing validation does not grant human approval. The pull-request and code-owner
review process must approve the evidence and scope. Shared assets can participate
in multiple biome scopes; their work counts must not be added as global progress.
"""
import argparse
import json
from pathlib import Path
import re

try:
    from .export_status import STAGES, build_catalog_status
    from .export_tracker_evidence import (BIOME_GATES, BIOME_NAMES, MAX_TARGETS, contribution_path,
                                         parse_json, public_text, read_source, sequence,
                                         targets, validate_contribution)
except ImportError:
    from export_status import STAGES, build_catalog_status
    from export_tracker_evidence import (BIOME_GATES, BIOME_NAMES, MAX_TARGETS, contribution_path,
                                        parse_json, public_text, read_source, sequence,
                                        targets, validate_contribution)

ROOT = Path(__file__).resolve().parents[1]


def validate_roadmap(roadmap, snapshot, manifest, root):
    """Check a roadmap against a freshly evidence-validated asset snapshot."""
    if (not isinstance(roadmap, dict) or set(roadmap) != {'schema_version', 'scope', 'biomes'} or
            type(roadmap['schema_version']) is not int or roadmap['schema_version'] != 1):
        raise ValueError('Unknown roadmap schema or fields')
    scope = public_text(roadmap['scope'])
    assets = {}
    for asset in sequence(snapshot.get('assets'), 100000):
        if not isinstance(asset, dict):
            raise ValueError('Invalid snapshot asset')
        identity, stages = asset.get('id'), asset.get('stages')
        targets({'targets': [{'asset_id': identity, 'stages': []}]})
        if identity in assets:
            raise ValueError('Snapshot has duplicate asset identity')
        if (asset.get('kind') not in ('texture', 'mesh') or not isinstance(stages, dict) or
                set(stages) != set(STAGES) or any(type(value) is not bool for value in stages.values())):
            raise ValueError('Snapshot requires explicit known asset stages')
        assets[identity] = asset
    evidence, reviews, approved_claims = {}, {}, set()
    for record in sequence(manifest.get('evidence'), 1000):
        if not isinstance(record, dict):
            raise ValueError('Invalid manifest evidence')
        identity = record.get('id')
        if not isinstance(identity, str) or re.fullmatch('[a-z0-9][a-z0-9-]*', identity) is None or identity in evidence:
            raise ValueError('Invalid or duplicate manifest evidence ID')
        evidence[identity] = record
        for asset_id, _ in targets(record):
            if asset_id not in assets:
                raise ValueError('Unknown asset in manifest evidence')
        approved_claims.update(row['asset_id'] for row in record['targets'] if 'approved' in row['stages'])
        if contribution_path(record.get('path')):
            reviews[identity] = validate_contribution(root, record, known_ids=set(assets))
    rows = sequence(roadmap['biomes'], 9)
    if len(rows) != 9:
        raise ValueError('Roadmap requires all nine fixed biomes')
    result, seen = {}, set()
    for biome in rows:
        if not isinstance(biome, dict) or set(biome) != {'id', 'name', 'state', 'asset_ids', 'approval_evidence'}:
            raise ValueError('Unknown biome fields')
        identity = biome['id']
        if (not isinstance(identity, str) or identity not in BIOME_NAMES or identity in seen or
                biome['name'] != BIOME_NAMES[identity]):
            raise ValueError('Unknown or duplicate biome identity/name')
        seen.add(identity)
        state = biome['state']
        if state not in ('planned', 'active', 'approved'):
            raise ValueError('Unknown biome state')
        scoped = sequence(biome['asset_ids'], MAX_TARGETS)
        scoped_set = set()
        for asset_id in scoped:
            if not isinstance(asset_id, str) or asset_id not in assets:
                raise ValueError('Unknown asset in biome scope')
            if asset_id in scoped_set:
                raise ValueError('Biome scope contains duplicate asset IDs')
            scoped_set.add(asset_id)
        approvals = sequence(biome['approval_evidence'], 100)
        seen_approvals = set()
        for approval in approvals:
            if (not isinstance(approval, str) or re.fullmatch('[a-z0-9][a-z0-9-]*', approval) is None or
                    approval in seen_approvals):
                raise ValueError('Invalid or duplicate biome approval evidence')
            seen_approvals.add(approval)
        if state != 'approved' and approvals:
            raise ValueError('Nonapproved biomes cannot claim approval evidence')
        if state == 'approved':
            if not scoped or not approvals:
                raise ValueError('An approved biome requires nonempty scope and explicit approval evidence')
            if any(not assets[asset_id]['stages']['approved'] or asset_id not in approved_claims for asset_id in scoped):
                raise ValueError('Every scoped asset must have an explicit approved stage')
            for approval in approvals:
                if approval not in evidence:
                    raise ValueError('Unknown biome approval evidence')
                review = reviews.get(approval)
                if review is None or review['kind'] != 'biome-review' or review['biome_id'] != identity:
                    raise ValueError('Approval evidence must be an explicit matching biome-review')
                if {row['asset_id'] for row in review['targets']} != scoped_set:
                    raise ValueError('Biome review targets must exactly cover the declared scope')
                if any(review['gates'][gate] is not True for gate in BIOME_GATES):
                    raise ValueError('Biome approval requires all five review gates')
                if not review['checks'] or not all(check['passed'] for check in review['checks']):
                    raise ValueError('Biome approval requires all-passing recorded checks')
        result[identity] = {
            'id': identity, 'name': BIOME_NAMES[identity], 'state': state,
            'scoped_assets': len(scoped),
            'stage_counts': {stage: sum(assets[asset_id]['stages'][stage] for asset_id in scoped) for stage in STAGES},
        }
    return {'schema_version': 1, 'scope': scope, 'biomes': [result[identity] for identity in BIOME_NAMES],
            'approval_semantics': 'Approval is explicitly recorded through human review. Passing checks does not grant approval. Work counts are scoped by biome and are separate from global inventory progress.'}


def validate_file(root=ROOT):
    root = Path(root)
    manifest_bytes = read_source(root, 'assets/status/manifest.json')
    snapshot = build_catalog_status(read_source(root, 'assets/status/catalog.json'), manifest_bytes, root)
    return validate_roadmap(parse_json(read_source(root, 'assets/status/roadmap.json')),
                            snapshot, parse_json(manifest_bytes), root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(validate_file(args.root), ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
