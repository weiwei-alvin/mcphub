"""Regressions for the 2026-09-29 harness review: GP coverage gate, approved-plan
lock, configurable source-hash exclusions and toolchain environment."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_support import fixture
import test_reliability

PLAN_PAUSE='PLAN_CHANGE_REQUIRES_DECISION'

class ReviewFixes(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='harness-review-fix-')
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        fixture(self.root,3)

    def tearDown(self):
        test_reliability.FIXTURES.append(dict(test=self.id(),files={str(p.relative_to(self.root)):p.read_text(encoding='utf-8') for p in (self.root/'.harness').rglob('*.json')}))

    def cli(self,*args,module='runner.py',ok=None):
        p=subprocess.run([sys.executable,str(self.root/'harness/runner'/module),*args],cwd=self.root,capture_output=True,text=True,encoding='utf-8',timeout=60)
        test_reliability.EVENTS.append(dict(test=self.id(),args=list(args),module=module,returncode=p.returncode,stdout=p.stdout,stderr=p.stderr,state=self.state()))
        if ok is not None: self.assertEqual(p.returncode==0,ok,p.stdout+p.stderr)
        return p

    def state(self):
        return json.loads((self.root/'.harness/state.json').read_text(encoding='utf-8'))

    def plan(self,extra_steps=(),per_ticket=('T-001','T-002','T-003'),**settings):
        (self.root/'calc.py').write_text('def add(a,b): return a+b\n',encoding='utf-8')
        (self.root/'check.py').write_text('from calc import add\nassert add(2,3)==5\nprint("OK")\n',encoding='utf-8')
        steps=[dict(id=f'GP-{n:03}',description=tid,user_story_ids=[],ticket_ids=[tid],verification_command=[sys.executable,'check.py'],expected_output='OK') for n,tid in enumerate(per_ticket,1)]
        steps+=list(extra_steps)
        (self.root/'.harness/golden_path.json').write_text(json.dumps(dict(steps=steps,**settings)),encoding='utf-8')

    def step(self,sid,tickets,command=None):
        return dict(id=sid,description='cross',user_story_ids=[],ticket_ids=list(tickets),verification_command=command or [sys.executable,'check.py'],expected_output='')

    def decision(self):
        ref=self.state()['pause']['decision_ref']
        return ref,json.loads((self.root/f'.harness/decisions/{ref}.json').read_text(encoding='utf-8'))

    def approved(self):
        self.plan(); self.cli('gate-verdict','--verdict','PASS',ok=True)

    # 1. TICKETS gate coverage
    def test_gate_rejects_ticket_without_own_step(self):
        self.plan(extra_steps=[self.step('GP-009',['T-001','T-002'])],per_ticket=('T-002','T-003'))
        before=self.state()
        p=self.cli('gate-verdict','--verdict','PASS',ok=False)
        self.assertIn('T-001 has no Golden Path step',p.stderr+p.stdout)
        self.assertNotIn('T-002 has no',p.stderr+p.stdout)
        self.assertEqual(before,self.state())

    def test_gate_rejects_step_without_command_as_coverage(self):
        self.plan(extra_steps=[dict(self.step('GP-009',['T-001']),verification_command='')],per_ticket=('T-002','T-003'))
        self.cli('gate-verdict','--verdict','PASS',ok=False)

    def test_gate_rejects_unknown_ticket_reference(self):
        self.plan(extra_steps=[self.step('GP-009',['T-001','T-404'])])
        p=self.cli('gate-verdict','--verdict','PASS',ok=False)
        self.assertIn('T-404',p.stderr)

    def test_cross_ticket_step_allowed_with_own_steps(self):
        self.plan(extra_steps=[self.step('GP-009',['T-001','T-002','T-003'])])
        self.cli('gate-verdict','--verdict','PASS',ok=True)
        s=self.state(); self.assertEqual(s['active_ticket_id'],'T-001'); self.assertRegex(s['approved_plan']['sha256'],'^[a-f0-9]{64}$')
        receipt=json.loads(self.cli('verify-ticket','--ticket','T-001','--trust-commands',ok=True).stdout)
        self.assertEqual([x['step_id'] for x in receipt['results']],['GP-001'])

    def test_fix_gate_verdict_does_not_require_coverage(self):
        self.cli('gate-verdict','--verdict','FIX_REQUIRED',ok=True)
        self.assertEqual(self.state()['stage_status'],'IN_PROGRESS')

    # 3. approved plan lock
    def test_weakened_golden_path_pauses_instead_of_verifying(self):
        self.approved()
        data=json.loads((self.root/'.harness/golden_path.json').read_text())
        data['steps'][0]['verification_command']=[sys.executable,'-c','print("OK")']
        (self.root/'.harness/golden_path.json').write_text(json.dumps(data))
        p=self.cli('verify-ticket','--ticket','T-001','--trust-commands',ok=False)
        self.assertIn('Approved plan',p.stderr)
        s=self.state(); self.assertEqual(s['project_status'],'PAUSED'); self.assertEqual(s['pause']['reason'],PLAN_PAUSE)
        self.assertNotIn('verification',s['tickets']['T-001'])
        ref,d=self.decision(); self.assertEqual(d['options'],['CONTINUE']); self.assertRegex(d['plan_hash'],'^[a-f0-9]{64}$')
        self.cli('resume',ok=False)
        self.cli('decide','--option','CONTINUE','--rationale','Reviewed new command','--source','operator',ok=True)
        self.cli('resume',ok=True)
        s=self.state(); self.assertEqual(s['project_status'],'IN_PROGRESS'); self.assertEqual(s['approved_plan']['sha256'],d['plan_hash'])
        self.assertNotIn('retry_limit',s['tickets']['T-001'])
        self.cli('verify-ticket','--ticket','T-001','--trust-commands',ok=True)

    def test_ticket_edit_pauses_review(self):
        self.approved()
        with open(self.root/'.harness/tickets/T-001.md','a',encoding='utf-8') as f: f.write('\nScope reduced\n')
        self.cli('mark-ticket-ready-for-review','--ticket','T-001',ok=True)
        (self.root/'.harness/inbox').mkdir(); (self.root/'.harness/inbox/r.json').write_text('{}')
        self.cli('review-verdict','--ticket','T-001','--verdict','PASS','--review','.harness/inbox/r.json','--handoff','.harness/inbox/r.json','--trust-commands',ok=False)
        self.assertEqual(self.state()['pause']['reason'],PLAN_PAUSE)

    def test_revert_plan_and_resume(self):
        self.approved(); gp=self.root/'.harness/golden_path.json'; original=gp.read_text()
        gp.write_text(original.replace('"OK"','"CHANGED"'))
        self.cli('verify-ticket','--ticket','T-001','--trust-commands',ok=False)
        gp.write_text(original)
        self.cli('decide','--option','CONTINUE','--rationale','Reverted','--source','operator',ok=True)
        p=self.cli('resume',ok=False)
        self.assertIn('changed again',p.stderr)
        self.assertEqual(self.state()['project_status'],'PAUSED')
        self.cli('decide','--option','CONTINUE','--rationale','Original plan restored','--source','operator',ok=True)
        self.cli('resume',ok=True)

    def test_second_change_after_decision_supersedes(self):
        self.approved(); gp=self.root/'.harness/golden_path.json'
        gp.write_text(gp.read_text().replace('"OK"','"A"'))
        self.cli('verify-ticket','--ticket','T-001','--trust-commands',ok=False)
        first,_=self.decision()
        self.cli('decide','--option','CONTINUE','--rationale','ok','--source','operator',ok=True)
        gp.write_text(gp.read_text().replace('"A"','"B"'))
        self.cli('resume',ok=False)
        second,d=self.decision()
        self.assertNotEqual(first,second); self.assertFalse(d['resolved'])

    def test_added_ticket_joins_state_after_decision(self):
        self.approved()
        (self.root/'.harness/tickets/T-004.md').write_text('---\nid: T-004\ndepends_on: [T-003]\n---\n# new\n',encoding='utf-8')
        data=json.loads((self.root/'.harness/golden_path.json').read_text()); data['steps'].append(self.step('GP-004',['T-004']))
        (self.root/'.harness/golden_path.json').write_text(json.dumps(data))
        self.cli('verify-ticket','--ticket','T-001','--trust-commands',ok=False)
        self.cli('decide','--option','CONTINUE','--rationale','Scope approved','--source','operator',ok=True)
        self.cli('resume',ok=True)
        self.assertEqual(self.state()['tickets']['T-004']['status'],'TODO')
        self.cli('validate',ok=True)

    def test_invalid_changed_plan_stays_paused(self):
        self.approved()
        (self.root/'.harness/tickets/T-004.md').write_text('---\nid: T-004\ndepends_on: []\n---\n',encoding='utf-8')
        self.cli('verify-ticket','--ticket','T-001','--trust-commands',ok=False)
        self.cli('decide','--option','CONTINUE','--rationale','x','--source','operator',ok=True)
        p=self.cli('resume',ok=False)
        self.assertIn('T-004 has no Golden Path step',p.stderr)
        self.assertEqual(self.state()['project_status'],'PAUSED')

    def test_removed_ticket_rejected(self):
        self.approved(); (self.root/'.harness/tickets/T-003.md').unlink()
        self.cli('verify-ticket','--ticket','T-001','--trust-commands',ok=False)
        self.cli('decide','--option','CONTINUE','--rationale','x','--source','operator',ok=True)
        p=self.cli('resume',ok=False); self.assertIn('Removing approved tickets',p.stderr)

    def test_manual_plan_pause_rejected(self):
        self.approved()
        self.cli('pause','--reason',PLAN_PAUSE,'--decision-ref','DEC-050',ok=False)
        self.assertEqual(self.state()['project_status'],'IN_PROGRESS')

    def test_unchanged_plan_completes_three_tickets(self):
        self.approved()
        for n in range(1,4):
            tid=f'T-{n:03}'
            receipt=json.loads(self.cli('verify-ticket','--ticket',tid,'--trust-commands',ok=True).stdout)
            self.cli('mark-ticket-ready-for-review','--ticket',tid,ok=True)
            common=dict(ticket_id=tid,review_round=receipt['review_round'],source_hash=receipt['source_hash'],verification_id=receipt['verification_id'])
            r=dict(**common,verdict='PASS',criteria=[dict(id=x['step_id'],status='PASS',critical=True) for x in receipt['results']],findings=[])
            h=dict(**common,changes=[dict(file='calc.py',summary='add')],verification=[dict(step='receipt',expected='exit 0',actual='exit 0',status='PASS')],dependencies=[])
            inbox=self.root/'.harness/inbox'; inbox.mkdir(exist_ok=True)
            (inbox/'r.json').write_text(json.dumps(r)); (inbox/'h.json').write_text(json.dumps(h))
            self.cli('review-verdict','--ticket',tid,'--verdict','PASS','--review',str(inbox/'r.json'),'--handoff',str(inbox/'h.json'),'--trust-commands',ok=True)
        self.assertEqual(self.state()['project_status'],'COMPLETE')

    # 4. source hash exclusions
    def generated_plan(self,exclude=None):
        (self.root/'gen.py').write_text("import time\nopen('out.log','a').write(str(time.time()))\nopen('.coverage','w').write(str(time.time()))\nprint('OK')\n",encoding='utf-8')
        cmd=[sys.executable,'gen.py']
        settings={} if exclude is None else dict(source_hash_exclude=exclude)
        steps=[self.step(f'GP-00{n}',[t],cmd) for n,t in enumerate(('T-001','T-002','T-003'),1)]
        (self.root/'.harness/golden_path.json').write_text(json.dumps(dict(steps=steps,**settings)))
        self.cli('gate-verdict','--verdict','PASS',ok=True)

    def test_generated_files_without_exclusion_block_verification(self):
        self.generated_plan()
        p=self.cli('verify-ticket','--ticket','T-001','--trust-commands',ok=False)
        self.assertIn('Project changed during verification',p.stderr)

    def test_generated_files_with_exclusion_verify_repeatedly(self):
        self.generated_plan(['out.log','.coverage'])
        self.cli('verify-ticket','--ticket','T-001','--trust-commands',ok=True)
        self.cli('verify-ticket','--ticket','T-001','--trust-commands',ok=True)
        from storage import source_hash
        (self.root/'calc.py').write_text('def add(a,b): return a-b\n')
        a=source_hash(self.root); (self.root/'calc.py').write_text('def add(a,b): return a*b\n')
        self.assertNotEqual(a,source_hash(self.root))

    def test_directory_pattern_excluded(self):
        from storage import source_hash
        self.plan(source_hash_exclude=['build','reports/*.xml'])
        a=source_hash(self.root)
        (self.root/'build/x').mkdir(parents=True); (self.root/'build/x/a.bin').write_text('1')
        (self.root/'reports').mkdir(); (self.root/'reports/r.xml').write_text('1')
        self.assertEqual(a,source_hash(self.root))
        (self.root/'reports/keep.txt').write_text('1')
        self.assertNotEqual(a,source_hash(self.root))

    def test_exclusion_cannot_hide_plan_files(self):
        from storage import source_hash
        self.plan(source_hash_exclude=['*.md','*harness*'])
        a=source_hash(self.root)
        (self.root/'.harness/tickets/T-001.md').write_text('---\nid: T-001\ndepends_on: []\n---\n# edited\n')
        self.assertNotEqual(a,source_hash(self.root))

    def test_dangerous_or_unknown_settings_rejected(self):
        from storage import project_settings, source_hash
        for bad in (['.harness/tickets'],['*'],['**/*'],['../x'],['/abs'],['C:/x'],[''],'x'):
            self.plan(source_hash_exclude=bad)
            with self.assertRaises(ValueError,msg=bad): project_settings(self.root)
        self.plan(env_passthrough=['BAD NAME'])
        with self.assertRaises(ValueError): project_settings(self.root)
        self.plan(unexpected=True)
        with self.assertRaises(ValueError): source_hash(self.root)
        self.cli('snapshot',ok=False)

    # 5. environment
    def test_toolchain_paths_and_passthrough(self):
        from command_execution import execute
        self.plan(env_passthrough=['MY_TOOL_CONFIG'])
        probe=self.root/'probe.py'; probe.write_text("import os,json\nprint(json.dumps({k:os.environ.get(k) for k in ('HOME','USERPROFILE','APPDATA','LOCALAPPDATA','MY_TOOL_CONFIG','HARNESS_TEST_SECRET','GITHUB_TOKEN')}))\n")
        fake={'HOME':'/h','USERPROFILE':'C:/u','APPDATA':'C:/a','LOCALAPPDATA':'C:/l','MY_TOOL_CONFIG':'cfg','HARNESS_TEST_SECRET':'synthetic','GITHUB_TOKEN':'synthetic'}
        with patch.dict(os.environ,fake):
            result=execute([sys.executable,str(probe)],self.root,trusted=True,timeout=30)
        seen=json.loads(result['stdout'])
        for k in ('HOME','USERPROFILE','APPDATA','LOCALAPPDATA','MY_TOOL_CONFIG'): self.assertEqual(seen[k],fake[k])
        self.assertIsNone(seen['HARNESS_TEST_SECRET']); self.assertIsNone(seen['GITHUB_TOKEN'])

if __name__=='__main__':
    unittest.main()
