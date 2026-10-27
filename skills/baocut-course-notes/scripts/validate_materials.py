#!/usr/bin/env python3
"""Check declared reading provenance and note integration, never certify actual reading."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def validate(data, root):
    errors, pending, seen = [], [], set()
    expected = data.get('expected_material_ids')
    if not isinstance(expected, list) or len(expected) != len(set(expected)):
        errors.append('Explicit unique expected_material_ids required from source inventory')
    for material in data.get('materials', []):
        ident = material.get('id')
        if not ident or ident in seen:
            errors.append('Missing or duplicate material ID')
        seen.add(ident)
        status = material.get('reading_status')
        if material.get('recommendation_kind') == 'explicit_recommendation' and not material.get('required', True) and not material.get('scope_reason'):
            errors.append(f'{ident}: explicit recommendation excluded without scope reason')
        if status not in {'unread', 'abstract_only', 'partial', 'full', 'blocked', 'out_of_scope'}:
            errors.append(f'{ident}: invalid reading status')
        if material.get('required', True) and status != 'full':
            pending.append(ident)
        if material.get('required', True) and status == 'full' and not material.get('contributions'):
            pending.append(ident)
        if status == 'out_of_scope' and not material.get('scope_reason'):
            errors.append(f'{ident}: excluded without scope reason')
        if status != 'full':
            continue
        if material.get('identity_status') != 'verified' or not material.get('title') or not material.get('source_url'):
            errors.append(f'{ident}: full reading needs verified identity/source')
        path = root / material.get('path', '')
        if not path.is_file() or material.get('sha256') != sha(path):
            errors.append(f'{ident}: source missing or stale')
        if path.is_file() and material.get('kind') not in {'web', 'video'}:
            with path.open('rb') as stream:
                if not stream.read(5).startswith(b'%PDF-'):
                    errors.append(f'{ident}: declared PDF is not a PDF; abstract HTML is not full text')
        if material.get('kind') == 'video':
            video = material.get('video_review', {})
            if not video.get('video_id') or not isinstance(video.get('duration_seconds'), (int, float)) or video['duration_seconds'] <= 0:
                errors.append(f'{ident}: video identity/duration missing')
            for field, value in [('media_integrity', 'passed'), ('transcript_reading', 'full'), ('visual_review', 'full_timeline')]:
                if video.get(field) != value:
                    errors.append(f'{ident}: video {field} not complete')
            artifacts = video.get('artifacts', {})
            for key in ['transcript', 'read_coverage', 'manifest', 'fidelity_eval']:
                artifact = artifacts.get(key, {})
                artifact_path = root / artifact.get('path', '')
                if not artifact_path.is_file() or artifact.get('sha256') != sha(artifact_path):
                    errors.append(f'{ident}: video {key} evidence missing or stale')
        elif material.get('kind') == 'web':
            scope = material.get('scope_sections', [])
            if not scope or not set(scope).issubset(material.get('read_sections', [])):
                errors.append(f'{ident}: scoped web sections not completely declared read')
        else:
            count = material.get('total_pages')
            scope = material.get('scope_pages')
            if scope is not None and not material.get('scope_reason'):
                errors.append(f'{ident}: scoped PDF needs original recommendation/scope reason')
            if not isinstance(count, int) or count < 1:
                errors.append(f'{ident}: PDF physical page count missing')
            else:
                expected_pages = set(scope) if scope is not None else set(range(1, count + 1))
                if not expected_pages or not expected_pages.issubset(range(1, count + 1)) or set(material.get('read_pages', [])) != expected_pages:
                    errors.append(f'{ident}: full declared PDF scope not completely read')
        if material.get('known_gaps'):
            errors.append(f'{ident}: full reading has unresolved gaps')
        contributions = material.get('contributions', [])
        if not contributions and not material.get('not_adopted_reason'):
            errors.append(f'{ident}: no note contribution or reason')
        for contribution in contributions:
            item = contribution.get('item')
            if item not in material.get('related_items', []):
                errors.append(f'{ident}: contribution outside related items')
                continue
            notes_path = root / item / 'notes.json'
            if not notes_path.is_file():
                errors.append(f'{ident}: notes missing for {item}')
                continue
            notes = json.loads(notes_path.read_text())
            section = contribution.get('section')
            if not isinstance(section, int) or not 1 <= section <= len(notes['sections']):
                errors.append(f'{ident}: invalid contribution section')
                continue
            text = json.dumps(notes['sections'][section - 1], ensure_ascii=False) + json.dumps(notes.get('supplements', []), ensure_ascii=False)
            if ident not in text or not contribution.get('location') or not contribution.get('claim'):
                errors.append(f'{ident}: note marker/location/claim missing')
    if isinstance(expected, list) and set(expected) != seen:
        errors.append('Material inventory differs from expected IDs; missing or extra disposition')
    return {'status': 'failed' if errors else 'pending' if pending else 'passed', 'errors': errors, 'pending_materials': pending, 'materials': len(seen), 'scope': 'File versions, declared page/section coverage and actual note markers only; not proof of reading, semantics or UI.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--materials', type=Path, required=True)
    parser.add_argument('--course-root', type=Path, required=True)
    args = parser.parse_args()
    result = validate(json.loads(args.materials.read_text()), args.course_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1 if result['errors'] else 2 if result['pending_materials'] else 0)


if __name__ == '__main__':
    main()
