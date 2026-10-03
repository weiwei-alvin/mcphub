"""Runtime regressions: all writes and subprocesses target disposable projects."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from test_support import fixture
from unittest.mock import patch

EVENTS=[]
FIXTURES=[]

class Reliability(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='harness-regression-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        fixture(self.root, 3)

    def tearDown(self):
        FIXTURES.append(dict(test=self.id(),files={str(p.relative_to(self.root)):p.read_text(encoding='utf-8') for p in (self.root/'.harness').rglob('*.json')}))

    def cli(self, *args, module='runner.py', ok=None):
        p = subprocess.run([sys.executable, str(self.root/'harness/runner'/module), *args], cwd=self.root, capture_output=True, text=True, encoding='utf-8', timeout=30)
        EVENTS.append(dict(test=self.id(),args=list(args),module=module,returncode=p.returncode,stdout=p.stdout,stderr=p.stderr,state=self.state()))
        if ok is not None:
            self.assertEqual(p.returncode == 0, ok, p.stdout + p.stderr)
        return p

    def state(self, s=None):
        f = self.root/'.harness/state.json'
        if s is not None: f.write_text(json.dumps(s), encoding='utf-8')
        return json.loads(f.read_text(encoding='utf-8'))

    def ready(self):
        s=self.state(); s.update(pipeline_stage='IMPLEMENTATION',stage_status='IN_PROGRESS',active_ticket_id='T-001')
        s['tickets']['T-001']['status']='READY_FOR_REVIEW'; self.state(s)

    def test_pass_string_cannot_complete(self):
        self.ready(); s=self.state(); s['tickets']={k:v for k,v in s['tickets'].items() if k=='T-001'}; self.state(s)
        for f in (self.root/'.harness/tickets').glob('T-*.md'):
            if f.stem!='T-001': f.unlink()
        before=self.state()
        self.cli('review-verdict','--ticket','T-001','--verdict','PASS',ok=False)
        self.assertEqual(before,self.state())

    def test_dependency_gate(self):
        self.application()
        self.cli('gate-verdict','--verdict','PASS',ok=True)
        self.assertEqual(self.state()['active_ticket_id'],'T-001')

    def test_blank_decision_rejected(self):
        self.ready()
        self.cli('pause','--reason','REVIEW_USER_DECISION_REQUIRED','--decision-ref','DEC-001',ok=True)
        self.cli('resume',ok=False)
        self.assertEqual(self.state()['project_status'],'PAUSED')

    def test_unsupported_commands_rejected(self):
        for cmd in ('complete-ticket','ready-for-review'):
            with self.subTest(command=cmd): self.cli(cmd,'--ticket','T-001',ok=False)

    def test_dependency_multiline_rejected(self):
        (self.root/'.harness/tickets/T-002.md').write_text('---\nid: T-002\ndepends_on:\n  - T-001\n---\n',encoding='utf-8')
        self.cli('validate-deps',ok=False)

    def golden(self, command='', expected=''):
        (self.root/'.harness/golden_path.json').write_text(json.dumps({'steps':[dict(id='GP-001',description='assertion',user_story_ids=[],ticket_ids=['T-001'],verification_command=command,expected_output=expected)]}),encoding='utf-8')

    def test_unverified_not_passed(self):
        self.golden()
        p=self.cli('verify-incremental','--tickets','T-001',module='golden_path_verifier.py',ok=False)
        self.assertFalse(json.loads(p.stdout)['all_passed'])

    def test_untrusted_command_rejected(self):
        self.golden('python -c "from pathlib import Path; Path(\'marker\').touch()"')
        self.cli('verify-final',module='golden_path_verifier.py',ok=False)
        self.assertFalse((self.root/'marker').exists())

    def test_nonempty_finding_schema(self):
        self.ready()
        payload=dict(ticket_id='T-001',verdict='FIX_REQUIRED',criteria=[dict(id='AC-1',status='FAIL',critical=True)], findings=[dict(finding_key='wrong-addition',criterion_ref='AC-1',description='Wrong result',blocking=True)])
        f=self.root/'review.json'; f.write_text(json.dumps(payload),encoding='utf-8')
        self.cli('review','--file',str(f),module='payload_validator.py',ok=True)

    def test_stale_writer(self):
        from runner import HarnessRunner
        a=HarnessRunner(self.root); b=HarnessRunner(self.root)
        sa=a.read_state(); sb=b.read_state()
        sa['tickets']['T-001']['review_attempts']=1
        self.assertTrue(a.write_state_atomic(sa))
        self.assertFalse(b.write_state_atomic(sb))
        self.assertEqual(self.state()['tickets']['T-001']['review_attempts'],1)

    def application(self):
        (self.root/'calc.py').write_text('def add(a,b): return a+b\ndef mul(a,b): return a*b\ndef div(a,b): return a/b\n',encoding='utf-8')
        steps=[]
        for n,assertion in enumerate(('add(2,3)==5','mul(4,3)==12','div(mul(add(2,3),4),2)==10'),1):
            (self.root/f'check_{n}.py').write_text(f'from calc import add,mul,div\nassert {assertion}\n',encoding='utf-8')
            steps.append(dict(id=f'GP-{n:03}',description=assertion,user_story_ids=[],ticket_ids=[f'T-{n:03}'],verification_command=[sys.executable,f'check_{n}.py'],expected_output=''))
        (self.root/'.harness/golden_path.json').write_text(json.dumps({'steps':steps}),encoding='utf-8')

    def evidence(self,tid='T-001',verdict='PASS'):
        from storage import source_hash
        s=self.state(); t=s['tickets'][tid]
        common=dict(ticket_id=tid,review_round=t.get('review_total',0)+1,source_hash=source_hash(self.root))
        if verdict=='PASS':
            receipt=json.loads(self.cli('verify-ticket','--ticket',tid,'--trust-commands',ok=True).stdout)
            common['verification_id']=receipt['verification_id']
            criteria=[dict(id=x['step_id'],status='PASS',critical=True) for x in receipt['results']]
            findings=[]
        else:
            criteria=[dict(id='GP-001',status='FAIL',critical=True)]
            findings=[dict(finding_key='wrong-addition',criterion_ref='GP-001',description='Addition assertion failed',blocking=True)]
        review=dict(**common,verdict=verdict,criteria=criteria,findings=findings)
        handoff=dict(**common,changes=[dict(file='calc.py',summary='Arithmetic operations')],verification=[dict(step='controlled receipt',expected='exit 0',actual='exit 0',status='PASS')],dependencies=[])
        folder=self.root/'.harness/inbox'; folder.mkdir(exist_ok=True)
        r=folder/'review.json'; h=folder/'handoff.json'
        r.write_text(json.dumps(review),encoding='utf-8'); h.write_text(json.dumps(handoff),encoding='utf-8')
        return r,h

    def submit(self,tid,r,h,verdict='PASS',ok=True):
        self.cli('review-verdict','--ticket',tid,'--verdict',verdict,'--review',str(r),'--handoff',str(h),'--trust-commands',ok=ok)

    def test_three_ticket_end_to_end(self):
        self.application()
        self.cli('gate-verdict','--verdict','PASS',ok=True)
        for n in range(1,4):
            tid=f'T-{n:03}'
            self.assertEqual(self.state()['active_ticket_id'],tid)
            r,h=self.evidence(tid)
            self.cli('mark-ticket-ready-for-review','--ticket',tid,ok=True)
            self.submit(tid,r,h)
            self.cli('validate',ok=True)
            s=self.state(); self.assertEqual(s['tickets'][tid]['status'],'COMPLETE')
            self.assertEqual(s['project_status'],'COMPLETE' if n==3 else 'IN_PROGRESS')
        self.assertIn('final_verification',s)
        self.assertEqual(len(s['tickets']['T-003']['review_history']),1)

    def test_bound_evidence_rejections(self):
        self.application(); self.ready()
        r,h=self.evidence(); original=json.loads(r.read_text()); handoff=json.loads(h.read_text())
        for target,key,value in [('review','ticket_id','T-002'),('review','review_round',8),('review','source_hash','0'*64),('review','verification_id','fake'),('handoff','review_round',9),('handoff','source_hash','0'*64)]:
            with self.subTest(target=target,key=key):
                data=copy_dict(original if target=='review' else handoff); data[key]=value
                path=r if target=='review' else h; path.write_text(json.dumps(data),encoding='utf-8')
                before=self.state(); self.submit('T-001',r,h,ok=False); self.assertEqual(self.state(),before)
                path.write_text(json.dumps(original if target=='review' else handoff),encoding='utf-8')
        for flag,path in [('--review',r),('--handoff',h)]:
            args=['review-verdict','--ticket','T-001','--verdict','PASS',flag,str(path)]
            self.cli(*args,ok=False)
        for status in ('FAIL','UNVERIFIED'):
            data=copy_dict(original); data['criteria'][0]['status']=status
            r.write_text(json.dumps(data),encoding='utf-8'); self.submit('T-001',r,h,ok=False)
        r.write_text(json.dumps(original),encoding='utf-8')
        data=copy_dict(handoff); data['verification'][0]['status']='UNVERIFIED'
        h.write_text(json.dumps(data),encoding='utf-8'); self.submit('T-001',r,h,ok=False)
        h.write_text(json.dumps(handoff),encoding='utf-8')
        (self.root/'calc.py').write_text('def add(a,b): return a-b\n',encoding='utf-8')
        self.submit('T-001',r,h,ok=False)

    def test_failed_test_cannot_complete_and_fix(self):
        self.application(); self.ready()
        good=(self.root/'calc.py').read_text(); (self.root/'calc.py').write_text(good.replace('a+b','a-b'))
        self.cli('verify-ticket','--ticket','T-001','--trust-commands',ok=False)
        self.cli('review-verdict','--ticket','T-001','--verdict','PASS',ok=False)
        self.assertNotEqual(self.state()['tickets']['T-001']['status'],'COMPLETE')
        (self.root/'calc.py').write_text(good)
        r,h=self.evidence(); self.submit('T-001',r,h)

    def test_pause_retry_resume_round_four(self):
        self.application(); self.ready()
        for attempt in range(1,4):
            r,h=self.evidence(verdict='FIX_REQUIRED'); self.submit('T-001',r,h,'FIX_REQUIRED')
            if attempt<3: self.cli('mark-ticket-ready-for-review','--ticket','T-001',ok=True)
        s=self.state(); self.assertEqual(s['project_status'],'PAUSED')
        self.assertEqual(len(s['tickets']['T-001']['review_history']),3)
        pause=s['pause']; path=self.root/'.harness/decisions'/f"{pause['decision_ref']}.json"
        original=json.loads(path.read_text())
        self.cli('resume',ok=False)
        self.cli('decide','--option','PASS','--rationale','override','--source','operator',ok=False)
        for changes in ({'resolved':False,'chosen_option':'CONTINUE','rationale':'retry','source':'operator'}, {'resolved':True,'chosen_option':'CONTINUE','rationale':'retry','source':'operator','pause_id':'old'}, {'resolved':True,'chosen_option':'CONTINUE','rationale':' ','source':'operator'}):
            d=dict(original,**changes); path.write_text(json.dumps(d)); self.cli('resume',ok=False)
        path.write_text(json.dumps(original))
        self.cli('decide','--option','CONTINUE','--rationale','Fix assertion','--source','local operator',ok=True)
        self.cli('resume',ok=True)
        self.cli('mark-ticket-ready-for-review','--ticket','T-001',ok=True)
        r,h=self.evidence(verdict='FIX_REQUIRED'); self.submit('T-001',r,h,'FIX_REQUIRED')
        s=self.state(); self.assertEqual(s['tickets']['T-001']['review_attempts'],4)
        self.assertEqual(s['tickets']['T-001']['review_total'],4)
        self.assertEqual(s['project_status'],'IN_PROGRESS')
        self.assertEqual(len(s['tickets']['T-001']['review_history']),4)
        f=next(iter(s['findings'].values())); self.assertEqual(f['description'],'Addition assertion failed')
        self.cli('update-fix-memory','--ticket','T-001','--finding-data','Changed subtraction to addition',ok=True)
        self.assertEqual(self.state()['tickets']['T-001']['fix_loop_memory']['fix_summary'],'Changed subtraction to addition')
        self.cli('resolve-finding','--finding-id','F-001',ok=True)
        self.cli('mark-ticket-ready-for-review','--ticket','T-001',ok=True)
        r,h=self.evidence(); self.submit('T-001',r,h)
        self.assertEqual(self.state()['tickets']['T-001']['status'],'COMPLETE')
        self.assertEqual(len(self.state()['tickets']['T-001']['review_history']),5)

    def test_all_pause_routes(self):
        self.cli('gate-verdict','--verdict','USER_DECISION_REQUIRED','--decision-ref','DEC-017',ok=True)
        self.cli('resume',ok=False)
        self.cli('decide','--option','FIX_REQUIRED','--rationale','Revise graph','--source','operator',ok=True)
        self.cli('resume',ok=True)
        self.application(); self.ready()
        r,h=self.evidence(verdict='FIX_REQUIRED'); d=json.loads(r.read_text())
        d.update(verdict='USER_DECISION_REQUIRED',decision_context=dict(question='Scope?',why_blocked='Needs operator',options=[dict(label='FIX_REQUIRED',impact='Return to fixes')]))
        r.write_text(json.dumps(d)); self.submit('T-001',r,h,'USER_DECISION_REQUIRED')
        self.cli('resume',ok=False)
        self.cli('decide','--option','FIX_REQUIRED','--rationale','Clarified scope','--source','operator',ok=True)
        self.cli('resume',ok=True)
        self.assertEqual(self.state()['tickets']['T-001']['status'],'IN_PROGRESS')

    def test_write_failures_do_not_complete(self):
        from runner import HarnessRunner
        from workflow import Workflow
        self.application(); self.ready(); r,h=self.evidence(); before=self.state()
        for target in ('workflow.atomic_json','storage.os.replace'):
            with self.subTest(target=target),patch(target,side_effect=OSError('injected disk failure')):
                with self.assertRaises((OSError,RuntimeError)): Workflow(HarnessRunner(self.root),trusted=True).review('T-001','PASS',r,h)
            self.assertEqual(before,self.state())

    def test_final_acceptance_failure_no_complete(self):
        self.application(); self.cli('gate-verdict','--verdict','PASS',ok=True)
        for tid in ('T-001','T-002'):
            r,h=self.evidence(tid); self.cli('mark-ticket-ready-for-review','--ticket',tid,ok=True); self.submit(tid,r,h)
        # Last check passes once but fails on the mandatory final execution.
        (self.root/'check_3.py').write_text("from pathlib import Path\nfrom calc import add,mul,div\nassert div(mul(add(2,3),4),2)==10\np=Path('.harness/final-counter')\nn=int(p.read_text()) if p.exists() else 0\np.write_text(str(n+1))\nassert n==0\n")
        r,h=self.evidence('T-003'); self.cli('mark-ticket-ready-for-review','--ticket','T-003',ok=True)
        before=self.state(); self.submit('T-003',r,h,ok=False)
        self.assertEqual(before,self.state())

    def test_timeout_cleans_descendants_and_filters_environment(self):
        import time
        from command_execution import execute
        child=self.root/'child.py'; child.write_text("import time\nfrom pathlib import Path\ntime.sleep(2)\nPath('escaped').write_text('alive')\ntime.sleep(30)\n")
        parent=self.root/'parent.py'; parent.write_text("import subprocess,sys,time,os\nfrom pathlib import Path\nassert 'HARNESS_TEST_SECRET' not in os.environ\np=subprocess.Popen([sys.executable,'child.py'])\nPath('child-pid').write_text(str(p.pid))\ntime.sleep(30)\n")
        with patch.dict(os.environ,{'HARNESS_TEST_SECRET':'synthetic-test-value'}):
            result=execute([sys.executable,str(parent)],self.root,trusted=True,timeout=0.7)
        self.assertIn('timed out',result['error']); self.assertTrue((self.root/'child-pid').exists())
        time.sleep(2.2); self.assertFalse((self.root/'escaped').exists())
        pid=int((self.root/'child-pid').read_text())
        if os.name=='nt':
            import ctypes
            k=ctypes.WinDLL('kernel32'); k.OpenProcess.restype=ctypes.c_void_p
            handle=k.OpenProcess(0x1000,False,pid)
            if handle:
                code=ctypes.c_ulong(); k.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.c_void_p]; k.GetExitCodeProcess(handle,ctypes.byref(code)); k.CloseHandle.argtypes=[ctypes.c_void_p]; k.CloseHandle(handle)
                self.assertNotEqual(code.value,259)

    def test_incremental_reruns_and_source_changes(self):
        self.application(); self.ready()
        self.cli('verify-ticket','--ticket','T-001','--trust-commands',ok=True)
        a=self.state()['tickets']['T-001']['verification']
        self.cli('verify-ticket','--ticket','T-001','--trust-commands',ok=True)
        self.assertNotEqual(a,self.state()['tickets']['T-001']['verification'])
        (self.root/'calc.py').write_text('def add(a,b): return a-b\n')
        self.cli('verify-ticket','--ticket','T-001','--trust-commands',ok=False)

    def test_golden_optional_expected_and_malformed(self):
        (self.root/'SPEC.md').write_text('## Golden Path\n- GP-001: arithmetic (T-001) - `python check.py`\n')
        self.cli('list-steps',module='golden_path_verifier.py',ok=True)
        (self.root/'SPEC.md').write_text('## Golden Path\n- GP-001 malformed\n')
        self.cli('list-steps',module='golden_path_verifier.py',ok=False)

    def test_reopened_blocker(self):
        self.application(); self.ready(); s=self.state()
        s['findings']={'F-001':dict(ticket_id='T-001',finding_key='bug',status='REOPENED',first_detected_attempt=1,last_seen_attempt=1,reopen_count=1)}
        s['tickets']['T-001']['active_findings']=['F-001']; self.state(s)
        p=self.cli('--json',module='status.py',ok=True)
        self.assertEqual(json.loads(p.stdout)['tickets']['blocking_findings_count'],1)
        r,h=self.evidence(); self.submit('T-001',r,h,ok=False)

    def test_init_and_every_runner_command(self):
        # init is tested only on a new temporary project's state.
        (self.root/'.harness/state.json').unlink()
        self.cli('init',ok=True); self.cli('init',ok=False)
        self.assertEqual(self.state()['pipeline_stage'],'TICKETS')
        self.cli('set-ready-for-gate',ok=True)
        for cmd in ('read','validate','recover','executable-tickets','next-ticket','blocked-tickets','validate-deps','snapshot'):
            p=self.cli(cmd,ok=True); self.assertTrue(p.stdout.strip())
        self.cli('start-ticket','--ticket','T-002',ok=False)
        self.application()
        self.cli('gate-verdict','--verdict','PASS',ok=True)
        self.cli('start-ticket','--ticket','T-002',ok=False)
        self.cli('increment-review','--ticket','T-001',ok=False)
        self.cli('fix-loop-memory','--ticket','T-001',ok=True)
        self.cli('update-fix-memory','--ticket','T-001','--finding-data','Fixed calc',ok=True)
        f=dict(ticket_id='T-001',finding_key='bug',status='OPEN',first_detected_attempt=1,last_seen_attempt=1,reopen_count=0)
        self.cli('add-finding','--finding-id','F-001','--finding-data',json.dumps(f),ok=True)
        self.cli('resolve-finding','--finding-id','F-001',ok=True)
        self.assertEqual(self.state()['findings']['F-001']['status'],'RESOLVED')
        # Standalone start supports an idle implementation state.
        s=self.state(); s['active_ticket_id']=None; s['tickets']['T-001']['status']='TODO'; self.state(s)
        self.cli('start-ticket','--ticket','T-001',ok=True)
        self.assertEqual(self.state()['active_ticket_id'],'T-001')

    def test_all_auxiliary_cli_commands(self):
        for cmd in ('validate','executable','next','blocked'):
            self.cli(cmd,module='dependency_scheduler.py',ok=True)
        self.cli('can-start','--ticket','T-001',module='dependency_scheduler.py',ok=True)
        self.cli('can-start','--ticket','T-002',module='dependency_scheduler.py',ok=False)
        for args in [('create-scope','--title','Calculator'),('create-story','--title','Add','--scope','S-001'),('create-ticket','--title','Implement','--story','US-001'),('get','--id','T-001'),('trace','--id','T-001'),('validate',),('report',),('list',)]:
            self.cli(*args,module='traceability.py',ok=True)
        self.cli('get','--id','T-999',module='traceability.py',ok=False)
        self.cli(module='status.py',ok=True)
        self.application()
        for args in [('list-steps',),('verify-final','--trust-commands'),('verify-incremental','--tickets','T-001','--trust-commands')]:
            self.cli(*args,module='golden_path_verifier.py',ok=True)

    def test_explicit_project_root_from_other_cwd(self):
        from state_transition import StateTransitionEngine,GateVerdict
        from runner import HarnessRunner
        self.application()
        s=self.state(); result=StateTransitionEngine(self.root).process_gate_verdict(s,GateVerdict.PASS)
        self.assertTrue(result.success,result.error)
        self.assertEqual(result.new_state['active_ticket_id'],'T-001')
        p=subprocess.run([sys.executable,str(self.root/'harness/runner/runner.py'),'gate-verdict','--verdict','PASS','--project-root',str(self.root)],cwd=self.root.parent,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertTrue(HarnessRunner(self.root).validate_state(self.state())[0])

    def test_gate_selects_dependency_ready_not_first_id(self):
        self.application()
        for tid,deps in [('T-001','T-003'),('T-002','T-001'),('T-003','')]:
            (self.root/f'.harness/tickets/{tid}.md').write_text(f'---\nid: {tid}\ndepends_on: [{deps}]\n---\n')
        self.cli('gate-verdict','--verdict','PASS',ok=True)
        self.assertEqual(self.state()['active_ticket_id'],'T-003')

    def test_unknown_schema_reference_never_fetches_network(self):
        from schema_validation import validator
        schema=dict(json.loads((self.root/'harness/finding.schema.json').read_text()))
        schema['$ref']='https://invalid.example/never-fetch'
        (self.root/'harness/finding.schema.json').write_text(json.dumps(schema))
        with patch('urllib.request.urlopen',side_effect=AssertionError('Network attempted')) as network:
            with self.assertRaises(Exception): validator(self.root/'harness','finding.schema.json').validate({})
            network.assert_not_called()

    def test_state_lock_conflict(self):
        from storage import state_lock
        with state_lock(self.root/'.harness'):
            self.cli('gate-verdict','--verdict','PASS',ok=False)
        self.assertEqual(self.state()['pipeline_stage'],'TICKETS')

    def test_required_command_missing_receipt_tamper_and_manual_limits(self):
        self.application(); self.ready(); r,h=self.evidence()
        s=self.state(); ref=s['tickets']['T-001']['verification']; f=self.root/'.harness'/ref['path']; old=f.read_bytes()
        f.write_text('{}'); self.submit('T-001',r,h,ok=False); f.write_bytes(old)
        s['tickets']['T-001'].pop('verification'); self.state(s)
        self.submit('T-001',r,h,ok=False)
        r,h=self.evidence(); d=json.loads(r.read_text()); d['criteria'].append(dict(id='MANUAL-UX',status='PASS',critical=True))
        r.write_text(json.dumps(d)); self.submit('T-001',r,h,ok=False)
        d['criteria'][-1].update(source='Operator observed local keyboard flow',limitations='One Windows display size only')
        r.write_text(json.dumps(d)); self.submit('T-001',r,h,ok=True)

    def test_unverified_controlled_receipt_blocks_pass(self):
        self.application(); self.ready(); r,h=self.evidence()
        f=self.root/'.harness/golden_path.json'; data=json.loads(f.read_text()); data['steps'][0]['verification_command']=''; f.write_text(json.dumps(data))
        self.cli('verify-ticket','--ticket','T-001','--trust-commands',ok=False)
        s=self.state(); receipt=json.loads((self.root/'.harness'/s['tickets']['T-001']['verification']['path']).read_text())
        self.assertFalse(receipt['all_passed']); self.assertEqual(receipt['results'][0]['status'],'UNVERIFIED')
        for path in (r,h):
            d=json.loads(path.read_text()); d.update(source_hash=receipt['source_hash'],verification_id=receipt['verification_id']); path.write_text(json.dumps(d))
        before=self.state(); self.submit('T-001',r,h,ok=False); self.assertEqual(self.state(),before)

    def test_pause_artifact_failure_does_not_change_state(self):
        from runner import HarnessRunner
        from workflow import Workflow
        self.ready(); before=self.state()
        with patch('workflow.atomic_json',side_effect=OSError('injected decision write failure')):
            with self.assertRaises(OSError): Workflow(HarnessRunner(self.root)).pause('REVIEW_USER_DECISION_REQUIRED','DEC-999')
        self.assertEqual(before,self.state())

    def test_invalid_graph_and_config_rejected(self):
        p=self.root/'.harness/tickets/T-001.md'
        for dep in ('T-003','T-999'):
            p.write_text(f'---\nid: T-001\ndepends_on: [{dep}]\n---\n')
            before=self.state(); self.cli('gate-verdict','--verdict','PASS',ok=False); self.assertEqual(before,self.state())
        (self.root/'.harness/golden_path.json').write_text('{bad json')
        self.cli('list-steps',module='golden_path_verifier.py',ok=False)

def copy_dict(data): return json.loads(json.dumps(data))

if __name__ == '__main__': unittest.main(verbosity=2)
