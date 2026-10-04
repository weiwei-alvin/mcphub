"""Parallel-ticket mode (max_parallel_tickets > 1); every write targets a disposable project."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from test_support import fixture


class Parallel(unittest.TestCase):
    """T-001 is COMPLETE; T-002 and T-003 both depend only on T-001; T-004 depends on T-002."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='harness-parallel-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        fixture(self.root, 4)
        deps = {'T-001': '', 'T-002': 'T-001', 'T-003': 'T-001', 'T-004': 'T-002'}
        for tid, dep in deps.items():
            (self.root/f'.harness/tickets/{tid}.md').write_text(f'---\nid: {tid}\ndepends_on: [{dep}]\n---\n# Test ticket\n', encoding='utf-8')
        s = self.state()
        s.update(pipeline_stage='IMPLEMENTATION', stage_status='IN_PROGRESS', active_ticket_id=None)
        s['tickets']['T-001']['status'] = 'COMPLETE'
        self.state(s)

    def cli(self, *args, ok=None):
        p = subprocess.run([sys.executable, str(self.root/'harness/runner/runner.py'), *args], cwd=self.root, capture_output=True, text=True, encoding='utf-8', timeout=30)
        if ok is not None:
            self.assertEqual(p.returncode == 0, ok, p.stdout + p.stderr)
        return p

    def state(self, s=None):
        f = self.root/'.harness/state.json'
        if s is not None: f.write_text(json.dumps(s), encoding='utf-8')
        return json.loads(f.read_text(encoding='utf-8'))

    def statuses(self):
        return {k: v['status'] for k, v in self.state()['tickets'].items()}

    def test_default_mode_still_allows_one_active_ticket(self):
        self.cli('start-ticket', '--ticket', 'T-002', ok=True)
        p = self.cli('start-ticket', '--ticket', 'T-003', ok=False)
        self.assertIn('Another ticket T-002 is active', p.stderr)
        self.assertNotIn('max_parallel_tickets', self.state())

    def test_parallel_mode_starts_independent_tickets_up_to_limit(self):
        self.cli('set-max-parallel', '--max-parallel', '2', ok=True)
        self.cli('start-ticket', '--ticket', 'T-002', ok=True)
        self.cli('start-ticket', '--ticket', 'T-003', ok=True)
        self.assertEqual(self.statuses()['T-002'], 'IN_PROGRESS')
        self.assertEqual(self.statuses()['T-003'], 'IN_PROGRESS')
        self.cli('validate', ok=True)

    def test_parallel_limit_is_enforced(self):
        self.cli('set-max-parallel', '--max-parallel', '2', ok=True)
        s = self.state(); s['tickets']['T-004'] = dict(status='TODO', review_attempts=0, active_findings=[])
        (self.root/'.harness/tickets/T-004.md').write_text('---\nid: T-004\ndepends_on: [T-001]\n---\n', encoding='utf-8')
        self.state(s)
        self.cli('start-ticket', '--ticket', 'T-002', ok=True)
        self.cli('start-ticket', '--ticket', 'T-003', ok=True)
        p = self.cli('start-ticket', '--ticket', 'T-004', ok=False)
        self.assertIn('Parallel limit 2 reached', p.stderr)

    def test_parallel_mode_still_enforces_dependencies(self):
        self.cli('set-max-parallel', '--max-parallel', '3', ok=True)
        self.cli('start-ticket', '--ticket', 'T-002', ok=True)
        self.cli('start-ticket', '--ticket', 'T-004', ok=False)
        self.assertEqual(self.statuses()['T-004'], 'TODO')

    def test_each_parallel_ticket_can_be_marked_ready_independently(self):
        self.cli('set-max-parallel', '--max-parallel', '2', ok=True)
        self.cli('start-ticket', '--ticket', 'T-002', ok=True)
        self.cli('start-ticket', '--ticket', 'T-003', ok=True)
        self.cli('mark-ticket-ready-for-review', '--ticket', 'T-002', ok=True)
        self.cli('mark-ticket-ready-for-review', '--ticket', 'T-003', ok=True)
        self.assertEqual(self.statuses()['T-002'], 'READY_FOR_REVIEW')
        self.assertEqual(self.statuses()['T-003'], 'READY_FOR_REVIEW')

    def test_non_active_ticket_still_rejected_in_parallel_mode(self):
        self.cli('set-max-parallel', '--max-parallel', '2', ok=True)
        self.cli('start-ticket', '--ticket', 'T-002', ok=True)
        self.cli('mark-ticket-ready-for-review', '--ticket', 'T-003', ok=False)

    def test_limit_cannot_drop_below_current_active_count(self):
        self.cli('set-max-parallel', '--max-parallel', '2', ok=True)
        self.cli('start-ticket', '--ticket', 'T-002', ok=True)
        self.cli('start-ticket', '--ticket', 'T-003', ok=True)
        before = self.state()
        self.cli('set-max-parallel', '--max-parallel', '1', ok=False)
        self.assertEqual(before, self.state())

    def test_review_fix_required_on_one_ticket_leaves_the_other_active(self):
        from runner import HarnessRunner
        from workflow import Workflow
        from storage import source_hash
        self.cli('set-max-parallel', '--max-parallel', '2', ok=True)
        self.cli('start-ticket', '--ticket', 'T-002', ok=True)
        self.cli('start-ticket', '--ticket', 'T-003', ok=True)
        self.cli('mark-ticket-ready-for-review', '--ticket', 'T-002', ok=True)
        s = self.state()
        review = dict(ticket_id='T-002', review_round=1, source_hash=source_hash(self.root), verdict='FIX_REQUIRED',
                      criteria=[dict(id='GP-002', status='FAIL', critical=True)],
                      findings=[dict(finding_key='bad', criterion_ref='GP-002', description='Bad result', blocking=True)])
        outside = tempfile.TemporaryDirectory(prefix='harness-parallel-payload-'); self.addCleanup(outside.cleanup)
        path = Path(outside.name)/'review.json'; path.write_text(json.dumps(review), encoding='utf-8')
        Workflow(HarnessRunner(self.root)).review('T-002', 'FIX_REQUIRED', path, None)
        self.assertEqual(self.statuses()['T-002'], 'IN_PROGRESS')
        self.assertEqual(self.statuses()['T-003'], 'IN_PROGRESS')
        self.assertEqual(self.state()['tickets']['T-002']['active_findings'], ['F-001'])

    def test_review_pass_completes_one_ticket_without_auto_starting_another(self):
        from runner import HarnessRunner
        from workflow import Workflow
        from test_support import review_files
        self.cli('set-max-parallel', '--max-parallel', '2', ok=True)
        self.cli('start-ticket', '--ticket', 'T-002', ok=True)
        self.cli('start-ticket', '--ticket', 'T-003', ok=True)
        self.cli('mark-ticket-ready-for-review', '--ticket', 'T-003', ok=True)
        self.assertEqual(self.state()['active_ticket_id'], 'T-003')
        rp, hp = review_files(self.root)
        Workflow(HarnessRunner(self.root), trusted=True).review('T-003', 'PASS', rp, hp)
        s = self.state()
        self.assertEqual(self.statuses(), {'T-001': 'COMPLETE', 'T-002': 'IN_PROGRESS', 'T-003': 'COMPLETE', 'T-004': 'TODO'})
        self.assertEqual(s['active_ticket_id'], 'T-002')
        self.assertEqual(s['project_status'], 'IN_PROGRESS')

    def test_pause_raised_by_a_non_focus_ticket_resumes_that_ticket(self):
        from runner import HarnessRunner
        from workflow import Workflow
        from storage import source_hash
        self.cli('set-max-parallel', '--max-parallel', '2', ok=True)
        self.cli('start-ticket', '--ticket', 'T-002', ok=True)
        self.cli('mark-ticket-ready-for-review', '--ticket', 'T-002', ok=True)
        self.cli('start-ticket', '--ticket', 'T-003', ok=True)
        self.assertEqual(self.state()['active_ticket_id'], 'T-003')
        review = dict(ticket_id='T-002', review_round=1, source_hash=source_hash(self.root), verdict='USER_DECISION_REQUIRED',
                      criteria=[dict(id='GP-002', status='FAIL', critical=True)], findings=[],
                      decision_context=dict(question='Scope?', why_blocked='SPEC is silent', options=[dict(label='FIX_REQUIRED', impact='Rework')]))
        outside = tempfile.TemporaryDirectory(prefix='harness-parallel-payload-'); self.addCleanup(outside.cleanup)
        path = Path(outside.name)/'review.json'; path.write_text(json.dumps(review), encoding='utf-8')
        Workflow(HarnessRunner(self.root)).review('T-002', 'USER_DECISION_REQUIRED', path, None)
        s = self.state()
        self.assertEqual(s['project_status'], 'PAUSED')
        decision = json.loads((self.root/'.harness/decisions'/f"{s['pause']['decision_ref']}.json").read_text(encoding='utf-8'))
        self.assertEqual(decision['ticket_id'], 'T-002')
        self.cli('decide', '--option', 'FIX_REQUIRED', '--rationale', 'rework', '--source', 'test', ok=True)
        self.cli('resume', ok=True)
        s = self.state()
        self.assertEqual(s['project_status'], 'IN_PROGRESS')
        self.assertEqual(self.statuses()['T-002'], 'IN_PROGRESS')
        self.assertEqual(self.statuses()['T-003'], 'IN_PROGRESS')


if __name__ == '__main__':
    unittest.main()
