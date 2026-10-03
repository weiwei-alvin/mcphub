"""Evidence-consuming workflow for one operator's trusted local project.

Artifacts are written before the state commit. Unreferenced artifacts after a
failed commit are not accepted evidence. Same-user file edits are outside this
accidental-error boundary; hashes are freshness checks, not signatures.
"""
import copy
import json
from pathlib import Path
import re
import uuid
from dependency_scheduler import DependencyScheduler
from golden_path_verifier import GoldenPathVerifier
from payload_validator import PayloadValidator
from state_transition import create_initial_state, GateVerdict, PauseReason
from storage import atomic_json, digest, plan_hash, source_hash
from schema_validation import validator

class Workflow:
    def __init__(self, runner, *, trusted=False, timeout=60):
        self.runner=runner
        self.root=runner.project_root
        self.directory=runner.harness_dir
        self.trusted=trusted
        self.timeout=timeout

    def state(self):
        s=self.runner.read_state()
        if s is None: raise ValueError('No valid state')
        return s

    def commit(self,s):
        if not self.runner.write_state_atomic(s): raise RuntimeError('State commit failed; operation not completed')

    def initialize(self):
        if self.runner.state_file.exists(): raise ValueError('State already exists; init refuses to overwrite')
        tickets=self.graph()
        if not tickets: raise ValueError('Create .harness/tickets/T-NNN.md before init')
        s=create_initial_state()
        s.update(pipeline_stage='TICKETS',stage_status='IN_PROGRESS')
        s['tickets']={tid:dict(status='TODO',review_attempts=0,active_findings=[]) for tid in tickets}
        self.commit(s)

    def graph(self,s=None):
        scheduler=self.runner.dependency_scheduler
        tickets=scheduler.load_ticket_files()
        errors=scheduler.validate_dependencies(tickets)
        if s is not None and set(tickets)!=set(s['tickets']): errors.append('Ticket files and state ticket IDs differ')
        if errors: raise ValueError('; '.join(errors))
        return tickets

    def coverage_errors(self,tickets):
        """Each ticket needs an executable GP step limited to itself and its prerequisites.

        verify-ticket only enables steps whose tickets are all COMPLETE or active, so a
        step that also names a later ticket can never verify the earlier one.
        """
        steps=GoldenPathVerifier(self.root).get_all_steps()
        errors=[f'{x.id} references unknown tickets {sorted(set(x.ticket_ids)-set(tickets))}' for x in steps if set(x.ticket_ids)-set(tickets)]
        def ancestors(tid,seen=None):
            seen=set() if seen is None else seen
            for dep in tickets[tid].depends_on:
                if dep in tickets and dep not in seen: seen.add(dep); ancestors(dep,seen)
            return seen
        for tid in sorted(tickets):
            allowed=ancestors(tid)|{tid}
            if not any(tid in x.ticket_ids and set(x.ticket_ids)<=allowed and x.verification_command for x in steps):
                errors.append(f'{tid} has no Golden Path step covering only itself and its prerequisites {sorted(allowed-{tid})}; add one with ticket_ids limited to that set')
        return errors

    def check_plan(self,s):
        """Refuse work on a plan that changed after TICKETS gate approval."""
        approved=(s.get('approved_plan') or {}).get('sha256')
        if not approved or s['project_status']!='IN_PROGRESS': return
        current=plan_hash(self.root)
        if current==approved: return
        self.prepare_pause(s,'PLAN_CHANGE_REQUIRES_DECISION',plan=current)
        self.commit(s)
        raise ValueError(f"Approved plan (tickets, golden_path.json or SPEC.md) changed after TICKETS gate; project paused as {s['pause']['decision_ref']}. Review the change, then run decide --option CONTINUE --rationale ... --source ... and resume, or revert the change and resume")

    def active(self,s,tid, ready=False):
        if s['project_status']!='IN_PROGRESS': raise ValueError('Project is not in progress')
        if not tid or s['active_ticket_id']!=tid: raise ValueError('Wrong active ticket')
        t=s['tickets'][tid]
        allowed=('READY_FOR_REVIEW',) if ready else ('IN_PROGRESS','READY_FOR_REVIEW')
        if t['status'] not in allowed: raise ValueError('Ticket not ready for this operation')
        return t

    def artifact(self, folder, data):
        identifier=uuid.uuid4().hex
        path=self.directory/folder/f'{identifier}.json'
        atomic_json(path,data)
        return {'path':str(path.relative_to(self.directory).as_posix()),'sha256':digest(path)}

    def read_artifact(self,ref):
        if not ref: raise ValueError('Missing controlled verification evidence')
        path=(self.directory/ref['path']).resolve()
        if not path.is_relative_to(self.directory.resolve()): raise ValueError('Artifact outside runtime directory')
        if digest(path)!=ref['sha256']: raise ValueError('Artifact changed or missing')
        return json.loads(path.read_text(encoding='utf-8'))

    def verify(self,tid):
        s=self.state(); self.check_plan(s); t=self.active(s,tid)
        self.graph(s)
        before=source_hash(self.root)
        v=GoldenPathVerifier(self.root,trusted=self.trusted,timeout=self.timeout)
        completed=[k for k,x in s['tickets'].items() if x['status']=='COMPLETE']+[tid]
        steps=v.get_steps_for_tickets(completed)
        if not steps or not any(tid in step.ticket_ids for step in steps):
            raise ValueError(f'{tid} has no enabled Golden Path step; each ticket needs a step whose ticket_ids are only {tid} and its prerequisites')
        results=v.verify_steps([x.id for x in steps])
        if before!=source_hash(self.root): raise ValueError('Project changed during verification; rerun after stabilizing files')
        evidence=dict(ticket_id=tid,review_round=t.get('review_total',0)+1,source_hash=before,
            verification_id=uuid.uuid4().hex, all_passed=all(x.status.value=='PASSED' for x in results),
            results=[dict(step_id=x.step_id,status=x.status.value,stdout=x.output,stderr=x.stderr,returncode=x.returncode,error=x.error) for x in results])
        t['verification']=self.artifact('verifications',evidence)
        self.commit(s)
        if not evidence['all_passed']: raise ValueError('Required verification FAIL or UNVERIFIED; receipt saved, completion blocked')
        return evidence

    def binding(self,payload,tid,t,current):
        expected={'ticket_id':tid,'review_round':t.get('review_total',0)+1,'source_hash':current}
        for key,value in expected.items():
            if payload.get(key)!=value: raise ValueError(f'Evidence binding mismatch: {key}')

    def review(self,tid,verdict,review_path,handoff_path):
        s=self.state(); self.check_plan(s); t=self.active(s,tid,ready=True)
        files=self.graph(s)
        if not review_path: raise ValueError('Missing review payload; PASS string is not evidence')
        review=json.loads(Path(review_path).read_text(encoding='utf-8'))
        pv=PayloadValidator(self.root)
        valid,errors=pv.validate('review',review)
        if not valid: raise ValueError('; '.join(errors))
        if review['verdict']!=verdict: raise ValueError('CLI verdict and review payload disagree')
        current=source_hash(self.root)
        self.binding(review,tid,t,current)
        handoff=None
        if verdict=='PASS':
            if not handoff_path: raise ValueError('Missing handoff payload')
            handoff=json.loads(Path(handoff_path).read_text(encoding='utf-8'))
            valid,errors=pv.validate('handoff',handoff)
            if not valid: raise ValueError('; '.join(errors))
            self.binding(handoff,tid,t,current)
            receipt=self.read_artifact(t.get('verification'))
            self.binding(receipt,tid,t,current)
            if not receipt.get('all_passed') or not receipt.get('results') or any(x['status']!='PASSED' or x['returncode']!=0 for x in receipt['results']):
                raise ValueError('Required verification did not pass')
            for payload in (review,handoff):
                if payload.get('verification_id')!=receipt['verification_id']: raise ValueError('Wrong verification_id')
            if any(x['status']!='PASS' for x in handoff['verification']): raise ValueError('Handoff contains UNVERIFIED required evidence')
            expected_ids={x['step_id'] for x in receipt['results']}
            criteria={x['id']:x for x in review['criteria']}
            if len(criteria)!=len(review['criteria']): raise ValueError('Duplicate review criteria')
            for cid in expected_ids:
                if cid not in criteria or criteria[cid]['status']!='PASS' or not criteria[cid]['critical']:
                    raise ValueError(f'Missing or failed required criterion: {cid}')
            for item in review['criteria']:
                if item['id'] not in expected_ids and item['critical']:
                    if item['status']!='PASS' or not item.get('source','').strip() or not item.get('limitations','').strip():
                        raise ValueError('Manual required criteria need PASS, source and limitations')
            unresolved=[f for f in s['findings'].values() if f['ticket_id']==tid and f['status'] in ('OPEN','REOPENED') and f.get('blocking',True)]
            if unresolved: raise ValueError('Unresolved blocking findings remain; resolve after fixing and re-review')
            last=all(k==tid or x['status']=='COMPLETE' for k,x in s['tickets'].items())
            if last:
                final=GoldenPathVerifier(self.root,trusted=self.trusted,timeout=self.timeout).verify_final_integrated()
                if final.get('status')!='PASSED': raise ValueError('Final integrated verification failed: '+json.dumps(final))
                s['final_verification']=self.artifact('verifications',dict(source_hash=current,**final))
            t['status']='COMPLETE'
            s['active_ticket_id']=None
            if last: s.update(project_status='COMPLETE',pipeline_stage='REVIEW')
            else:
                nxt=self.runner.dependency_scheduler.get_next_ticket(s,files)
                if not nxt: raise ValueError('No executable next ticket; completion not committed')
                s['active_ticket_id']=nxt; s['tickets'][nxt]['status']='IN_PROGRESS'
                s['pipeline_stage']='IMPLEMENTATION'
        elif verdict=='FIX_REQUIRED':
            t['review_attempts']+=1
            t['status']='IN_PROGRESS'
            self.findings(s,tid,review['findings'],t.get('review_total',0)+1)
            t['fix_loop_memory']=self.runner.transition_engine._build_fix_loop_memory(s,tid,t['review_attempts'])
            if t['review_attempts']>=t.get('retry_limit',3): self.prepare_pause(s,'RETRY_LIMIT_REACHED')
        elif verdict=='USER_DECISION_REQUIRED':
            self.prepare_pause(s,'REVIEW_USER_DECISION_REQUIRED',context=review['decision_context'])
        else: raise ValueError('Invalid review verdict')
        t['review_total']=t.get('review_total',0)+1
        t.setdefault('review_history',[]).append(self.artifact('reviews',dict(review=review,handoff=handoff)))
        if source_hash(self.root)!=current: raise ValueError('Source changed during review/final verification')
        self.commit(s)

    def findings(self,s,tid,items,round_number):
        for item in items:
            fid=next((k for k,f in s['findings'].items() if f['ticket_id']==tid and f['finding_key']==item['finding_key']),None)
            if fid is None:
                fid=f"F-{max([int(k[2:]) for k in s['findings']]+[0])+1:03}"
                s['findings'][fid]=dict(ticket_id=tid,status='OPEN',first_detected_attempt=round_number,last_seen_attempt=round_number,reopen_count=0,**item)
            else:
                finding=s['findings'][fid]
                if finding['status']=='RESOLVED': finding['status']='REOPENED'; finding['reopen_count']+=1
                finding.update(item,last_seen_attempt=round_number)
        s['tickets'][tid]['active_findings']=[k for k,f in s['findings'].items() if f['ticket_id']==tid and f['status'] in ('OPEN','REOPENED') and f.get('blocking',True)]

    @staticmethod
    def supported_option(reason):
        return 'CONTINUE' if reason in ('RETRY_LIMIT_REACHED','PLAN_CHANGE_REQUIRES_DECISION') else 'FIX_REQUIRED'

    def prepare_pause(self,s,reason,decision_ref=None,context=None,plan=None):
        PauseReason(reason)
        if decision_ref is None:
            existing=[int(p.stem[4:]) for p in (self.directory/'decisions').glob('DEC-*.*') if re.fullmatch(r'DEC-\d{3,}',p.stem)]
            decision_ref=f'DEC-{max(existing+[0])+1:03}'
        if not re.fullmatch(r'DEC-\d{3,}',decision_ref): raise ValueError('decision_ref must be DEC-NNN')
        path=self.directory/'decisions'/f'{decision_ref}.json'
        if path.exists() or path.with_suffix('.md').exists(): raise ValueError('Decision reference already exists; use a new ID')
        pause_id=uuid.uuid4().hex
        option=self.supported_option(reason)
        if context and any(x['label']!=option for x in context['options']): raise ValueError(f'Only supported decision option is {option}')
        data=dict(decision_ref=decision_ref,pause_id=pause_id,reason=reason,ticket_id=s['active_ticket_id'],pipeline_stage=s['pipeline_stage'],options=[option],resolved=False,chosen_option='',rationale='',source='',context=context)
        if plan: data['plan_hash']=plan
        validator(self.root/'harness','decision.schema.json').validate(data)
        atomic_json(path,data)
        s.update(project_status='PAUSED',pause=dict(reason=reason,decision_ref=decision_ref,pause_id=pause_id))

    def pause(self,reason,decision_ref):
        s=self.state()
        if s['project_status']!='IN_PROGRESS': raise ValueError('Project not in progress')
        if reason=='PLAN_CHANGE_REQUIRES_DECISION': raise ValueError('Plan-change pauses are created automatically by verify-ticket/review-verdict')
        self.prepare_pause(s,reason,decision_ref)
        self.commit(s)

    def decision(self,s):
        if s['project_status']!='PAUSED' or not s['pause']: raise ValueError('Project not paused')
        pause=s['pause']; path=self.directory/'decisions'/f"{pause['decision_ref']}.json"
        data=json.loads(path.read_text(encoding='utf-8'))
        validator(self.root/'harness','decision.schema.json').validate(data)
        for key in ('pause_id','reason','decision_ref'):
            if data.get(key)!=pause.get(key): raise ValueError('Decision belongs to a different pause')
        if data['ticket_id']!=s['active_ticket_id'] or data['pipeline_stage']!=s['pipeline_stage']: raise ValueError('Decision context mismatch')
        expected=self.supported_option(pause['reason'])
        if data['options']!=[expected]: raise ValueError('Unsupported decision options')
        return path,data

    def decide(self,option,rationale,source):
        s=self.state(); path,d=self.decision(s)
        if option not in d['options'] or not rationale or not rationale.strip() or not source or not source.strip(): raise ValueError('Provide a supported --option, nonblank --rationale and --source')
        if d['resolved']: raise ValueError('Decision already resolved')
        d.update(resolved=True,chosen_option=option,rationale=rationale,source=source)
        atomic_json(path,d)

    def resume(self):
        s=self.state(); path,d=self.decision(s)
        if not d['resolved'] or d['chosen_option'] not in d['options'] or not d['rationale'].strip() or not d['source'].strip(): raise ValueError('Decision unresolved or blank')
        if d['reason']=='PLAN_CHANGE_REQUIRES_DECISION': self.accept_plan(s,d)
        t=s['tickets'].get(s['active_ticket_id'])
        if t:
            t['status']='IN_PROGRESS'
            if d['reason']=='RETRY_LIMIT_REACHED': t['retry_limit']=t['review_attempts']+3
        s.update(project_status='IN_PROGRESS',pause=None,stage_status='IN_PROGRESS')
        self.commit(s)

    def accept_plan(self,s,d):
        current=plan_hash(self.root)
        if current!=d.get('plan_hash'):
            self.prepare_pause(s,'PLAN_CHANGE_REQUIRES_DECISION',plan=current); self.commit(s)
            raise ValueError(f"Plan changed again after {d['decision_ref']} was prepared; review the new change under {s['pause']['decision_ref']}")
        files=self.runner.dependency_scheduler.load_ticket_files()
        removed=set(s['tickets'])-set(files)
        if removed: raise ValueError(f'Removing approved tickets is not supported: {sorted(removed)}')
        for tid in sorted(set(files)-set(s['tickets'])): s['tickets'][tid]=dict(status='TODO',review_attempts=0,active_findings=[])
        errors=self.runner.dependency_scheduler.validate_dependencies(files)+self.coverage_errors(files)
        if errors: raise ValueError('Changed plan is invalid; fix it (a new decision will be required): '+'; '.join(errors))
        s['approved_plan']=dict(sha256=current)

    def gate(self,verdict,decision_ref=None):
        s=self.state()
        if s['project_status']!='IN_PROGRESS': raise ValueError('Project not in progress')
        tickets_pass=s['pipeline_stage']=='TICKETS' and verdict=='PASS'
        if s['pipeline_stage']=='TICKETS': files=self.graph(s)
        if tickets_pass:
            errors=self.coverage_errors(files)
            if errors: raise ValueError('TICKETS gate refused: '+'; '.join(errors))
        result=self.runner.transition_engine.process_gate_verdict(s,GateVerdict(verdict),decision_ref)
        if not result.success: raise ValueError(result.error)
        if tickets_pass: result.new_state['approved_plan']=dict(sha256=plan_hash(self.root))
        if verdict=='USER_DECISION_REQUIRED': self.prepare_pause(result.new_state,'GATE_USER_DECISION_REQUIRED',decision_ref)
        self.commit(result.new_state)
