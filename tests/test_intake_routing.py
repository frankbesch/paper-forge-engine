"""Current-policy intake and application tests; historical fixtures remain unchanged."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import pf
from pf_lib import assessment, intake, ledger

class IntakeRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        shutil.copytree(ROOT / 'templates', self.root / 'templates')
        shutil.copytree(ROOT / 'config', self.root / 'config')
        (self.root / 'papers').mkdir()
        self.parser = pf.build_parser() if hasattr(pf, 'build_parser') else pf.parser()

    def capture(self, text='An uncited hypothesis.', **kwargs):
        argv = ['capture', '--text', text, '--title', text[:20]]
        for k, v in kwargs.items(): argv += ['--' + k.replace('_', '-'), v]
        path = pf.create_item(self.parser.parse_args(argv), self.root) if hasattr(pf, 'create_item') else pf.capture_source(self.parser.parse_args(argv), self.root)
        return path, json.loads((path / 'metadata.json').read_text())

    def draft(self, item_id, also=None):
        return {'status': 'draft', 'intake': {
            'idea': 'Use a checklist before a bounded task.', 'support': 'Conceptual suggestion only.',
            'unknowns': 'No outcome evidence.', 'potential_use': 'A local promptkit experiment.',
            'effort': 'One manual comparison.', 'risk': 'Extra review effort.',
            'next_action': 'Compare one checklist-assisted draft with a baseline.', 'confidence': 'low',
            'evidence_locations': ['source/pasted-text.md:1'], 'conflicts': []},
            'recommendation': {'disposition': 'Test', 'rationale': 'Test before adoption.', 'applications': [{
                'purpose': 'Compare checklist usefulness', 'destination': 'notes', 'project_path': 'prompts/checklist.md',
                'artifact_type': 'technique', 'item_ids': [item_id] + (also or []),
                'evidence_limits': 'Unmeasured conceptual suggestion.', 'success_check': 'Record errors and review time against baseline.'}]}}

    def submit(self, item_id, draft=None, failure=None):
        argv = ['intake', item_id, '--assessor', 'Codex', '--date', '2026-09-29']
        if draft is not None:
            path = self.root / 'draft.json'; path.write_text(json.dumps(draft)); argv += ['--from', str(path)]
        if failure: argv += ['--failure', failure]
        return pf.intake_item(self.parser.parse_args(argv), self.root)

    def test_cited_and_uncited_capture_are_pending_not_judgments(self):
        for kwargs in ({}, {'url': 'https://example.org/source', 'authors': 'Named author'}):
            path, m = self.capture('Unique text ' + str(kwargs), **kwargs)
            a = json.loads((path / 'assessment.json').read_text())
            self.assertEqual(a['status'], 'pending')
            self.assertEqual(a['intake']['attribution'], 'partial' if kwargs else 'unknown')
            self.assertEqual(assessment.validate_document(a, m, None), [])
            self.assertTrue(all(s['score'] is None for s in a['general'].values()))
            self.assertIsNone(assessment.safety_gate(a, m)['effective_disposition'])

    def test_weak_and_conflicting_evidence_remain_drafts(self):
        path, m = self.capture()
        draft = self.draft(m['item_id']); draft['intake']['conflicts'] = ['Second note disputes usefulness; unresolved.']
        doc, errors, written = self.submit(m['item_id'], draft)
        self.assertEqual(errors, []); self.assertTrue(written)
        self.assertEqual(doc['recommendation']['disposition'], 'Test')
        self.assertIsNone(assessment.safety_gate(doc, m)['effective_disposition'])
        self.assertEqual(doc['revision'], 2)
        args = self.parser.parse_args(['apply', m['item_id'], '--to', 'notes', '--recommendation', 'Test', '--evidence-boundary', 'Unmeasured'])
        with self.assertRaisesRegex(ValueError, 'only Apply or Test'): pf.apply_item(args, self.root)

    def test_failed_assessment_retries_same_item_and_preserves_history(self):
        path, m = self.capture(); source = next((path / 'source').iterdir()); before = source.read_bytes()
        failed, errors, _ = self.submit(m['item_id'], failure='Source review interrupted')
        self.assertEqual(errors, []); self.assertEqual(failed['status'], 'failed')
        retried, errors, _ = self.submit(m['item_id'], self.draft(m['item_id']))
        self.assertEqual(errors, []); self.assertEqual(retried['status'], 'draft')
        self.assertEqual(retried['history'][-1]['previous']['intake']['failure'], 'Source review interrupted')
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(len(list((self.root / 'papers').glob('*/metadata.json'))), 1)

    def test_draft_cannot_set_effective_decision_or_fake_verified_attribution(self):
        _, m = self.capture(); draft = self.draft(m['item_id'])
        draft['disposition'] = {'value': 'Apply', 'rationale': 'Do it'}
        self.assertTrue(self.submit(m['item_id'], draft)[1])
        draft = self.draft(m['item_id']); draft['intake'].update(attribution='verified', evidence_locations=[])
        self.assertTrue(self.submit(m['item_id'], draft)[1])

    def test_failed_integrity_stays_distinct_from_missing_citation(self):
        _, m = self.capture(); doc = intake.pending_assessment(m, '2026-09-29')
        self.assertFalse(assessment.safety_gate(doc, m)['blocked'])
        m['provenance_status'] = 'failed'
        self.assertTrue(assessment.safety_gate(doc, m)['blocked'])

    def test_code_capture_does_not_execute_and_records_supplied_commit(self):
        with mock.patch.object(pf.subprocess, 'run', side_effect=AssertionError('Code executed')):
            path, m = self.capture('raise RuntimeError("must never execute")', filename='example.py', source_commit='abc123')
        self.assertEqual(m['sources'][0]['commit'], 'abc123')
        self.assertIn('never executed', m['sources'][0]['extraction']['caveat'])
        self.assertIn('raise RuntimeError', (path / 'work/extracted.txt').read_text())

    def test_invalid_json_records_failure_without_losing_the_capture(self):
        path, m = self.capture()
        source_hash = pf.sha256(next((path / 'source').iterdir()))
        bad = self.root / 'bad.json'; bad.write_text('{invalid')
        doc, errors, written = pf.intake_item(self.parser.parse_args(['intake', m['item_id'], '--from', str(bad)]), self.root)
        self.assertTrue(errors); self.assertTrue(written)
        self.assertEqual(doc['status'], 'failed')
        self.assertEqual(source_hash, pf.sha256(next((path / 'source').iterdir())))

    def test_binary_code_records_failed_extraction_and_keeps_original(self):
        source = self.root / 'binary.py'; source.write_bytes(b'\xff\xfe\x00')
        args = self.parser.parse_args(['capture', str(source), '--title', 'Binary code input'])
        path = pf.create_item(args, self.root)
        m = json.loads((path / 'metadata.json').read_text())
        self.assertEqual(m['sources'][0]['extraction']['status'], 'failed')
        self.assertEqual((path / 'source/binary.py').read_bytes(), source.read_bytes())

    def test_unknown_source_ids_and_unsafe_application_path_fail(self):
        _, m = self.capture(); draft = self.draft(m['item_id'], ['PF-9999'])
        with self.assertRaises((ValueError, FileNotFoundError)):
            # resolve_item may fail before a structured finding; either must leave the pending record intact.
            result = self.submit(m['item_id'], draft)
            if result[1]: raise ValueError(result[1])
        draft = self.draft(m['item_id']); draft['recommendation']['applications'][0]['project_path'] = '../escape'
        self.assertTrue(self.submit(m['item_id'], draft)[1])

    def test_combined_proposal_approval_outcome_trace_without_feynman(self):
        path, m = self.capture(); _, second = self.capture('A second independent note.')
        doc, errors, _ = self.submit(m['item_id'], self.draft(m['item_id'], [second['item_id']]))
        self.assertEqual(errors, [])
        decision = {'status': 'assessed', 'disposition': {'value': 'Test', 'rationale': 'Alex authorized a bounded test.'}, 'application_state': 'candidate',
            'general': {key: {'score': 1, 'rationale': 'Synthetic fixture judgment.'} for key in assessment.REQUIRED_SCORES}}
        draft = self.root / 'decision.json'; draft.write_text(json.dumps(decision))
        args = self.parser.parse_args(['assess', m['item_id'], '--from', str(draft), '--reason', 'Synthetic decision', '--assessor', 'Codex'])
        self.assertTrue(pf.assess_item(args, self.root)[1])
        args.assessor = 'Alex'; self.assertEqual(pf.assess_item(args, self.root)[1], [])
        argv = ['apply', m['item_id'], '--to', 'notes', '--recommendation', 'Run bounded comparison', '--evidence-boundary', 'Not measured', '--repo-path', 'prompts/checklist.md', '--also', second['item_id'], '--proposal', '1']
        receipt, package, written = pf.apply_item(self.parser.parse_args(argv), self.root)
        self.assertTrue(written); self.assertIn('Success check', package)
        self.assertEqual(receipt['approval_status'], 'pending')
        self.assertIsNone(ledger.derive_states([receipt], [])[m['item_id']]['application_state'])
        approval, _ = pf.approve_export(self.parser.parse_args(['approve', receipt['receipt_id'], '--by', 'Alex']), self.root)
        self.assertEqual(ledger.derive_states([receipt], [], [approval])[m['item_id']]['application_state'], 'exported')
        outcome, _ = pf.outcome_item(self.parser.parse_args(['outcome', receipt['receipt_id'], '--expected', 'Fewer errors', '--observed', 'No improvement in this fixture', '--method', 'Manual paired comparison', '--uncertainty', 'One synthetic case', '--period', '2026-09-29:2026-09-29']), self.root)
        states = ledger.derive_states([receipt], [outcome], [approval])
        self.assertEqual(states[second['item_id']]['application_state'], 'measured')
        errors = []; ledger.validate_ledgers(self.root, {m['item_id'], second['item_id']}, errors); self.assertEqual(errors, [])
        self.assertEqual(m['learning']['feynman']['status'], 'not_requested')
        # Later source corruption blocks a new export even if metadata still says verified.
        next((path / 'source').iterdir()).write_text('corrupted')
        with self.assertRaisesRegex(ValueError, 'checksum'): pf.apply_item(self.parser.parse_args(argv), self.root)

if __name__ == '__main__': unittest.main()
