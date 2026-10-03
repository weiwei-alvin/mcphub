"""Disposable project fixtures. Never copy the operator's runtime state."""
import functools
import json
import os
from pathlib import Path
import shutil
import tempfile

SOURCE = Path(__file__).resolve().parents[2]

def fixture(root, count=1):
    shutil.copytree(SOURCE / 'harness', root / 'harness', ignore=shutil.ignore_patterns('__pycache__'))
    (root / '.harness/tickets').mkdir(parents=True)
    tickets = {}
    for n in range(1, count + 1):
        tid = f'T-{n:03}'
        dep = f'T-{n-1:03}' if n > 1 else ''
        (root / f'.harness/tickets/{tid}.md').write_text(f'---\nid: {tid}\ndepends_on: [{dep}]\n---\n# Test ticket\n', encoding='utf-8')
        tickets[tid] = dict(status='TODO', review_attempts=0, active_findings=[])
    state = dict(schema_version='1.1', project_status='IN_PROGRESS', pipeline_stage='TICKETS', stage_status='READY_FOR_GATE', active_ticket_id=None, pause=None, tickets=tickets, findings={})
    (root / '.harness/state.json').write_text(json.dumps(state), encoding='utf-8')
    return state

def isolated(fn):
    @functools.wraps(fn)
    def run():
        with tempfile.TemporaryDirectory(prefix='harness-test-') as tmp:
            root = Path(tmp)
            state = fixture(root)
            state.update(pipeline_stage='IMPLEMENTATION', active_ticket_id='T-001')
            state['tickets']['T-001']['status'] = 'IN_PROGRESS'
            state['stage_status'] = 'IN_PROGRESS'
            (root / '.harness/state.json').write_text(json.dumps(state), encoding='utf-8')
            old = Path.cwd()
            g = fn.__globals__
            saved = {key: g.get(key) for key in ('PROJECT_ROOT','RUNNER','VALIDATOR','STATE_FILE')}
            g.update(PROJECT_ROOT=root, RUNNER=root/'harness/runner/runner.py', VALIDATOR=root/'harness/runner/payload_validator.py', STATE_FILE=root/'.harness/state.json')
            try:
                os.chdir(root)
                return fn()
            finally:
                os.chdir(old)
                g.update(saved)
    return run

def review_files(root, verdict='PASS'):
    """Real assertion plus bound input payloads for legacy lifecycle regressions."""
    from runner import HarnessRunner
    from workflow import Workflow
    from storage import source_hash
    import sys
    runner=HarnessRunner(root); s=runner.read_state(); tid=s['active_ticket_id']
    # Each fixture declares exactly the state's tickets, not the operator's files.
    for existing in (root/'.harness/tickets').glob('T-*.md'):
        if existing.stem not in s['tickets']: existing.unlink()
    for key in s['tickets']:
        (root/f'.harness/tickets/{key}.md').write_text(f'---\nid: {key}\ndepends_on: []\n---\n',encoding='utf-8')
    (root/'calc.py').write_text('def add(a,b): return a+b\n',encoding='utf-8')
    (root/'check.py').write_text('from calc import add\nassert add(3,4)==7\n',encoding='utf-8')
    (root/'.harness/golden_path.json').write_text(json.dumps({'steps':[dict(id='GP-001',description='addition',user_story_ids=[],ticket_ids=[tid],verification_command=[sys.executable,'check.py'],expected_output='')]}),encoding='utf-8')
    common=dict(ticket_id=tid,review_round=s['tickets'][tid].get('review_total',0)+1,source_hash=source_hash(root))
    if verdict=='PASS': common['verification_id']=Workflow(runner,trusted=True).verify(tid)['verification_id']
    r=dict(**common,verdict=verdict,criteria=[dict(id='GP-001',status='PASS' if verdict=='PASS' else 'FAIL',critical=True)],findings=[] if verdict=='PASS' else [dict(finding_key='wrong-result',criterion_ref='GP-001',description='Bad result',blocking=True)])
    h=dict(**common,changes=[dict(file='calc.py',summary='addition')],verification=[dict(step='controlled',expected='exit 0',actual='exit 0',status='PASS')],dependencies=[])
    inbox=root/'.harness/inbox'; inbox.mkdir(exist_ok=True)
    rp=inbox/'review.json'; hp=inbox/'handoff.json'
    rp.write_text(json.dumps(r),encoding='utf-8'); hp.write_text(json.dumps(h),encoding='utf-8')
    return rp,hp
