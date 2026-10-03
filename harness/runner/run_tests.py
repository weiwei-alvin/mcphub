"""Single local/CI entry point; machine-readable results and immutable-state check."""
import argparse
import contextlib
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[2]

def protected():
    paths=list((ROOT/'.harness').rglob('*'))
    paths.extend([ROOT/'docs/TECHNICAL_REVIEW_2026-09-29.md',ROOT/'03_Codex-Experiments/technical-review-2026-09-29/audit_results.json',ROOT/'03_Codex-Experiments/technical-review-2026-09-29/audit_probe.py'])
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}

def implementation():
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'harness').rglob('*') if p.is_file() and '__pycache__' not in p.parts}

class Result(unittest.TextTestResult):
    def __init__(self,*args,**kwargs): super().__init__(*args,**kwargs); self.records=[]
    def startTest(self,test): self.started=time.monotonic(); super().startTest(test)
    def record(self,test,status,error=None): self.records.append(dict(test=str(test),status=status,error=error,seconds=time.monotonic()-self.started))
    def addSuccess(self,test): super().addSuccess(test); self.record(test,'PASS')
    def addFailure(self,test,err): super().addFailure(test,err); self.record(test,'FAIL',self._exc_info_to_string(err,test))
    def addError(self,test,err): super().addError(test,err); self.record(test,'ERROR',self._exc_info_to_string(err,test))
    def addSubTest(self,test,subtest,err):
        super().addSubTest(test,subtest,err)
        if err: self.record(subtest,'FAIL',self._exc_info_to_string(err,test))

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--output',type=Path,default=ROOT/'03_Codex-Experiments/reliability-repair-2026-09-29/results.json'); parser.add_argument('--legacy-only',action='store_true'); args=parser.parse_args()
    os.environ['PYTHONUTF8']='1'; os.environ['PYTHONDONTWRITEBYTECODE']='1'; sys.dont_write_bytecode=True
    before=protected(); code_before=implementation(); suite=unittest.TestSuite()
    for name in ('test_runner','test_state_transition','test_payload_validator','test_dependency_scheduler','test_traceability','test_fix_loop_memory'):
        module=importlib.import_module(name)
        for key,fn in vars(module).items():
            if key.startswith('test_') and callable(fn): suite.addTest(unittest.FunctionTestCase(fn,description=name+'.'+key))
    import test_reliability
    if not args.legacy_only: suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(test_reliability))
    if not args.legacy_only:
        import test_review_fixes
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(test_review_fixes))
    log=io.StringIO()
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=Result).run(suite)
    after=protected()
    code_after=implementation()
    data=dict(python=sys.version,platform=sys.platform,tests_run=result.testsRun,success=result.wasSuccessful() and before==after and code_before==code_after,implementation_unchanged=code_before==code_after,implementation_hashes=code_after,protected_unchanged=before==after,protected_before=before,protected_after=after,tests=result.records,cli_events=test_reliability.EVENTS,fixture_artifacts=test_reliability.FIXTURES)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
    args.output.with_suffix('.log').write_text(log.getvalue(),encoding='utf-8')
    print(log.getvalue()); print(f'PROTECTED_UNCHANGED={before==after}; RESULTS={args.output}')
    return 0 if data['success'] else 1

if __name__=='__main__': sys.exit(main())
