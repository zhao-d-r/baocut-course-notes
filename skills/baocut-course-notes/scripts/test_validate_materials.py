import copy
import json
import tempfile
import unittest
from pathlib import Path

from validate_materials import sha, validate


class MaterialGates(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = self.root / 'paper.pdf'
        source.write_bytes(b'%PDF-1.7\nfixture source, not an actually read paper')
        run = self.root / 'lecture-01'
        run.mkdir()
        (run / 'notes.json').write_text(json.dumps({'sections': [{'editor_notes': ['paper-fixture supplement']}] }))
        self.row = {'id': 'paper-fixture', 'required': True, 'kind': 'pdf', 'identity_status': 'verified', 'title': 'Fixture', 'source_url': 'https://example.org/paper', 'path': 'paper.pdf', 'sha256': sha(source), 'reading_status': 'full', 'total_pages': 2, 'read_pages': [1, 2], 'known_gaps': [], 'related_items': ['lecture-01'], 'contributions': [{'item': 'lecture-01', 'section': 1, 'location': 'physical page2', 'claim': 'synthetic claim'}]}

    def result(self, row=None):
        return validate({'expected_material_ids': ['paper-fixture'], 'materials': [row or self.row]}, self.root)

    def test_consistent_declared_fixture_passes(self):
        self.assertEqual(self.result()['status'], 'passed')

    def test_download_or_abstract_is_pending_not_full_reading(self):
        self.row['reading_status'] = 'abstract_only'
        self.assertEqual(self.result()['status'], 'pending')

    def test_missing_pages_reject_full_claim(self):
        self.row['read_pages'] = [1]
        self.assertEqual(self.result()['status'], 'failed')

    def test_changed_source_rejects_stale_reading(self):
        (self.root / 'paper.pdf').write_bytes(b'new version')
        self.assertEqual(self.result()['status'], 'failed')

    def test_missing_body_contribution_rejected(self):
        (self.root / 'lecture-01/notes.json').write_text(json.dumps({'sections': [{}]}))
        self.assertEqual(self.result()['status'], 'failed')

    def test_unverified_identity_rejects_full(self):
        self.row['identity_status'] = 'mismatch'
        self.assertEqual(self.result()['status'], 'failed')

    def test_web_scope_does_not_claim_entire_book(self):
        row = copy.deepcopy(self.row)
        row.update(kind='web', scope_sections=['one', 'two'], read_sections=['one'])
        self.assertEqual(self.result(row)['status'], 'failed')
        row['read_sections'].append('two')
        self.assertEqual(self.result(row)['status'], 'passed')

    def test_abstract_html_mislabeled_pdf_rejected(self):
        source = self.root / 'paper.pdf'
        source.write_bytes(b'<html>abstract only</html>')
        self.row['sha256'] = sha(source)
        self.assertEqual(self.result()['status'], 'failed')

    def test_specific_recommended_pdf_scope_is_explicit(self):
        self.row.update(scope_pages=[2], read_pages=[2], scope_reason='Teacher specifically recommended appendix on physical page2')
        self.assertEqual(self.result()['status'], 'passed')

    def test_missing_expected_material_disposition_rejected(self):
        result = validate({'expected_material_ids': ['paper-fixture', 'missing'], 'materials': [self.row]}, self.root)
        self.assertEqual(result['status'], 'failed')

    def test_explicit_recommendation_cannot_be_silently_excluded(self):
        self.row.update(recommendation_kind='explicit_recommendation', required=False, reading_status='unread')
        self.assertEqual(self.result()['status'], 'failed')
        self.row['scope_reason']='User explicitly requested only a different chapter; recommendation retained as excluded.'
        self.assertEqual(self.result()['status'], 'passed')

    def test_required_read_but_not_integrated_stays_pending(self):
        self.row.update(contributions=[], not_adopted_reason='Read the material, but relevant note integration remains undone')
        self.assertEqual(self.result()['status'], 'pending')

    def video_fixture(self):
        media = self.root / 'video.mp4'
        media.write_bytes(b'synthetic media fixture, not actual audiovisual proof')
        row = copy.deepcopy(self.row)
        row.update(kind='video', path='video.mp4', sha256=sha(media))
        row['video_review'] = {'video_id': 'fixture-id', 'duration_seconds': 120, 'media_integrity': 'passed', 'transcript_reading': 'full', 'visual_review': 'full_timeline', 'artifacts': {}}
        for key in ['transcript', 'read_coverage', 'manifest', 'fidelity_eval']:
            artifact = self.root / (key + '.json')
            artifact.write_text('{}')
            row['video_review']['artifacts'][key] = {'path': artifact.name, 'sha256': sha(artifact)}
        return row

    def test_video_uses_av_contract_not_pdf_pages(self):
        row = self.video_fixture()
        row.pop('read_pages')
        row.pop('total_pages')
        self.assertEqual(self.result(row)['status'], 'passed')

    def test_video_companion_text_cannot_replace_av_review(self):
        row = self.video_fixture()
        row.pop('video_review')
        self.assertEqual(self.result(row)['status'], 'failed')

    def test_video_needs_identity_and_duration(self):
        for key in ['video_id', 'duration_seconds']:
            row = self.video_fixture()
            row['video_review'].pop(key)
            with self.subTest(key=key):
                self.assertEqual(self.result(row)['status'], 'failed')

    def test_video_partial_transcript_or_visual_review_rejected(self):
        for key in ['media_integrity', 'transcript_reading', 'visual_review']:
            row = self.video_fixture()
            row['video_review'][key] = 'partial'
            with self.subTest(key=key):
                self.assertEqual(self.result(row)['status'], 'failed')

    def test_video_evidence_each_required(self):
        for key in ['transcript', 'read_coverage', 'manifest', 'fidelity_eval']:
            row = self.video_fixture()
            row['video_review']['artifacts'].pop(key)
            with self.subTest(key=key):
                self.assertEqual(self.result(row)['status'], 'failed')

    def test_video_changed_evidence_rejected(self):
        row = self.video_fixture()
        (self.root / 'manifest.json').write_text('changed')
        self.assertEqual(self.result(row)['status'], 'failed')

    def test_video_download_only_remains_pending(self):
        row = self.video_fixture()
        row.update(reading_status='partial', video_review={})
        self.assertEqual(self.result(row)['status'], 'pending')


if __name__ == '__main__':
    unittest.main()
