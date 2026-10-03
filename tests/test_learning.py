"""Optional learning defaults and compatibility; all writes use temporary items."""
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
from pf_lib import learning, load
import pf
import validate_v2


class LearningContractTests(unittest.TestCase):
    def item(self, mode=None):
        return {'route': {'selected': ['read', 'understand']},
                'learning': learning.new_learning(mode, '2026-09-29'),
                'state': {'lifecycle': 'active', 'current_stage': 'understand', 'blocker': None}}

    def test_default_is_off_without_request_dates(self):
        value = self.item()
        self.assertEqual(value['learning']['feynman']['status'], 'not_requested')
        self.assertIsNone(value['learning']['feynman']['mode'])
        self.assertIsNone(value['learning']['feynman']['requested_at'])
        self.assertEqual(learning.validate_learning(value), [])

    def test_modes_only_record_requests_not_completion(self):
        for mode in ['standard', 'blank_sheet']:
            with self.subTest(mode=mode):
                value = self.item(mode)
                self.assertEqual(value['learning']['feynman']['status'], 'active')
                self.assertEqual(learning.validate_learning(value), [])

    def test_pause_resume_keeps_stage_and_history(self):
        original = self.item('standard')
        snapshot = copy.deepcopy(original)
        paused = learning.transition_learning(original, 'pause', '2026-09-29', 'Pause requested')
        resumed = learning.transition_learning(paused, 'resume', '2026-09-30', 'Resume requested')
        self.assertEqual(original, snapshot)
        self.assertEqual(paused['state'], original['state'])
        self.assertEqual(resumed['state'], original['state'])
        exercise = resumed['learning']['feynman']
        self.assertEqual(exercise['status'], 'active')
        self.assertEqual(exercise['requested_at'], '2026-09-29')
        self.assertIsNone(exercise['paused_at'])
        self.assertEqual([h['before']['status'] for h in exercise['history']], ['active', 'paused'])

    def test_illegal_transitions_and_dates_rejected(self):
        for action, day in [('resume', '2026-09-29'), ('pause', '2026-09-28'), ('pause', 'tomorrow'), ('complete', '2026-09-29')]:
            with self.subTest(action=action, day=day), self.assertRaises(ValueError):
                learning.transition_learning(self.item('standard'), action, day, 'request')

    def test_legacy_requests_are_not_silently_resumed(self):
        for mode in ['standard', 'blank_sheet']:
            value = {'route': {'selected': ['read', 'understand'], 'feynman_mode': mode}}
            snapshot = copy.deepcopy(value)
            exercise = learning.read_learning(value)['feynman']
            self.assertEqual(exercise['status'], 'paused')
            self.assertIsNone(exercise['requested_at'])
            self.assertEqual(value, snapshot)

    def test_legacy_written_work_never_proves_live_completion(self):
        for mode in ['skipped', 'legacy_written_only', None]:
            value = {'route': {'selected': ['read', 'understand'], 'feynman_mode': mode}}
            self.assertEqual(learning.read_learning(value)['feynman']['status'], 'not_requested')

    def test_stale_mode_without_understand_does_not_create_exercise(self):
        value = {'route': {'selected': ['read', 'extend'], 'feynman_mode': 'standard'}}
        self.assertEqual(learning.read_learning(value)['feynman']['status'], 'not_requested')

    def test_legacy_explicit_resume_records_today_not_invented_history(self):
        value = {'route': {'selected': ['read', 'understand'], 'feynman_mode': 'standard'}}
        result = learning.transition_learning(value, 'resume', '2026-09-29', 'Alex requested resumption')
        self.assertEqual(result['learning']['feynman']['requested_at'], '2026-09-29')
        self.assertIsNone(result['learning']['feynman']['history'][0]['before']['requested_at'])

    def test_conflicting_canonical_and_legacy_modes_fail(self):
        value = self.item('standard'); value['route']['feynman_mode'] = 'blank_sheet'
        self.assertTrue(any('conflicts' in x for x in learning.validate_learning(value)))
        with self.assertRaises(ValueError): learning.read_learning(value)

    def test_matching_legacy_projection_is_accepted(self):
        for mode in ['standard', 'blank_sheet']:
            value = self.item(mode);value['route']['feynman_mode'] = mode
            self.assertEqual(learning.validate_learning(value), [])

    def test_bad_shapes_dates_and_states_fail_without_tracebacks(self):
        changes = [('status', []), ('status', 'done'), ('mode', []), ('mode', 'unknown'),
                   ('requested_at', 'not-a-date'), ('reason', ''), ('history', [1])]
        for key, value in changes:
            item = self.item('standard');item['learning']['feynman'][key] = value
            with self.subTest(key=key, value=value):self.assertTrue(learning.validate_learning(item))
        for value in [None, [], {}, {'schema_version': True, 'feynman': {}}, {'schema_version': 9, 'feynman': {}}]:
            with self.subTest(value=value):self.assertTrue(learning.validate_learning({'learning': value}))

    def test_active_requires_understand_but_paused_is_independent(self):
        value = self.item('standard');value['route']['selected'] = ['read']
        self.assertTrue(learning.validate_learning(value))
        value['learning']['feynman']['status'] = 'paused'
        self.assertEqual(learning.validate_learning(value), [])

    def test_pause_cannot_precede_prior_resume(self):
        paused = learning.transition_learning(self.item('standard'), 'pause', '2026-09-29', 'pause')
        resumed = learning.transition_learning(paused, 'resume', '2026-09-30', 'resume')
        with self.assertRaises(ValueError):
            learning.transition_learning(resumed, 'pause', '2026-09-29', 'backdated pause')

    def test_malformed_history_and_route_selection_rejected(self):
        item = self.item('standard')
        item['learning']['feynman']['history'] = [{}]
        self.assertTrue(learning.validate_learning(item))
        for selection in [None, 'understand', 3, [1]]:
            item = self.item('standard');item['route']['selected'] = selection
            self.assertTrue(learning.validate_learning(item))

    def test_unrequested_cannot_carry_request_dates(self):
        value = self.item();value['learning']['feynman']['requested_at'] = '2026-09-29'
        self.assertTrue(learning.validate_learning(value))


class LearningCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.root = Path(self.temp.name)
        shutil.copytree(ROOT / 'templates', self.root / 'templates')
        shutil.copytree(ROOT / 'config', self.root / 'config')
        (self.root / 'papers').mkdir()

    def tearDown(self):self.temp.cleanup()

    def args(self, *extra):
        return pf.build_parser().parse_args(['capture', '--text', 'A bounded synthetic hypothesis.',
                                            '--title', 'Synthetic hypothesis', '--retrieved', '2000-01-01', *extra])

    def test_all_routes_default_off_and_render_actual_selection(self):
        for route in pf.ROUTES:
            with self.subTest(route=route):
                args = self.args('--route', route, '--slug', route)
                args.text += route
                dest = pf.create_item(args, self.root)
                data = json.loads((dest / 'metadata.json').read_text())
                self.assertEqual(data['learning']['feynman']['status'], 'not_requested')
                self.assertNotIn('feynman_mode', data['route'])
                workbook = (dest / 'work/02-understand.md').read_text()
                self.assertIn('Feynman mode: `off`', workbook)
                self.assertNotIn('{{FEYNMAN', workbook)
                self.assertEqual(data['state']['current_stage'], 'read')
                self.assertEqual(pf.validate_repository(self.root), [])

    def test_explicit_modes_use_request_date_not_retrieval_date(self):
        for mode in ['standard', 'blank_sheet']:
            args = self.args('--route', 'interpret', '--feynman', mode, '--slug', mode);args.text += mode
            dest = pf.create_item(args, self.root)
            data = json.loads((dest / 'metadata.json').read_text())
            exercise = data['learning']['feynman']
            self.assertEqual(exercise['status'], 'active')
            self.assertNotEqual(exercise['requested_at'], '2000-01-01')
            self.assertIn(f'Feynman mode: `{mode}`', (dest / 'work/02-understand.md').read_text())

    def test_invalid_route_fails_before_fetch_or_write(self):
        args = self.args('--feynman', 'standard');args.text = None;args.source = 'https://example.invalid/paper.pdf'
        with mock.patch.object(pf, 'fetch_url') as fetch, self.assertRaisesRegex(ValueError, 'Understand'):
            pf.create_item(args, self.root)
        fetch.assert_not_called()
        self.assertEqual(list((self.root / 'papers').iterdir()), [])
        self.assertFalse((self.root / 'ledger').exists())

    def test_legacy_wrapper_none_still_defaults_off(self):
        args=self.args('--route', 'interpret');args.feynman=None
        dest=pf.create_item(args,self.root)
        self.assertEqual(json.loads((dest/'metadata.json').read_text())['learning']['feynman']['status'],'not_requested')

    def test_both_validators_reject_conflict_and_loader_fails_closed(self):
        dest=pf.create_item(self.args('--route','interpret','--feynman','standard'),self.root)
        path=dest/'metadata.json';data=json.loads(path.read_text());data['route']['feynman_mode']='blank_sheet';path.write_text(json.dumps(data))
        self.assertTrue(any('conflicts' in x for x in pf.validate_repository(self.root)))
        errors,_=validate_v2.validate_repository(self.root)
        self.assertTrue(any('conflicts' in x for x in errors))
        with self.assertRaisesRegex(SystemExit,'conflicts'):load.load_repository(self.root)

    def test_understand_can_complete_with_exercise_off(self):
        dest=pf.create_item(self.args('--route','interpret'),self.root)
        path=dest/'metadata.json';data=json.loads(path.read_text())
        data['state'].update(lifecycle='route_complete', current_stage='understand',
                             stage_statuses={'read':'complete','understand':'complete'})
        path.write_text(json.dumps(data))
        # This is a mechanical compatibility fixture, not evidence of a real learning outcome.
        self.assertEqual(pf.validate_repository(self.root),[])
        self.assertEqual(data['learning']['feynman']['status'],'not_requested')


if __name__ == '__main__':unittest.main()
