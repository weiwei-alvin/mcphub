#!/usr/bin/env python3
"""
Harness Runner - Minimal Runtime State Manager

Responsibilities:
- Read and validate .harness/state.json against state.schema.json
- Only Runner modifies Runtime State (atomic writes)
- Recover process from state after restart
- Enforce state transitions per Harness spec
"""

import json
import sys
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, List
from jsonschema import validate, ValidationError

HARNESS_DIR = Path(".harness")
STATE_FILE = HARNESS_DIR / "state.json"
SCHEMA_FILE = Path("harness/state.schema.json")

# Import state transition engine
from state_transition import (
    StateTransitionEngine,
    ProjectStatus, PipelineStage, StageStatus,
    TicketStatus, FindingStatus, ReviewVerdict, GateVerdict, PauseReason,
    create_initial_state
)
from dependency_scheduler import DependencyScheduler


class HarnessRunner:
    def __init__(self, project_root: Path = None):
        self.project_root = Path(project_root or Path.cwd()).resolve()
        self._read_digest = None
        self.harness_dir = self.project_root / HARNESS_DIR
        self.state_file = self.harness_dir / "state.json"
        self.schema_file = self.project_root / SCHEMA_FILE
        self._schema = None
        self.transition_engine = StateTransitionEngine(self.project_root)
        self.dependency_scheduler = DependencyScheduler(self.project_root)

    def load_schema(self) -> Dict:
        """Load and cache the JSON schema."""
        if self._schema is None:
            with open(self.schema_file, 'r', encoding='utf-8') as f:
                self._schema = json.load(f)
        return self._schema

    def validate_state(self, state: Dict) -> tuple[bool, Optional[str]]:
        """Validate state against schema. Returns (is_valid, error_message)."""
        try:
            from schema_validation import validator
            validator(self.schema_file.parent, self.schema_file.name).validate(state)
            return True, None
        except Exception as e:
            return False, str(e)

    def read_state(self) -> Optional[Dict]:
        """Read and validate state.json. Returns state dict or None if invalid/missing."""
        if not self.state_file.exists():
            return None
        try:
            from storage import digest
            raw = self.state_file.read_bytes()
            import hashlib
            self._read_digest = hashlib.sha256(raw).hexdigest()
            state = json.loads(raw)
            valid, error = self.validate_state(state)
            if not valid:
                print(f"State validation failed: {error}", file=sys.stderr)
                return None
            return state
        except json.JSONDecodeError as e:
            print(f"State file corrupted: {e}", file=sys.stderr)
            return None

    def write_state_atomic(self, state: Dict) -> bool:
        """Write state.json atomically. Returns success."""
        valid, error = self.validate_state(state)
        if not valid:
            print(f"State validation failed before write: {error}", file=sys.stderr)
            return False

        self.harness_dir.mkdir(parents=True, exist_ok=True)

        from storage import state_lock, digest, atomic_json
        try:
            with state_lock(self.harness_dir):
                if digest(self.state_file) != self._read_digest:
                    raise RuntimeError("Stale writer conflict: state changed since read; reload and retry")
                atomic_json(self.state_file, state)
                self._read_digest = digest(self.state_file)
            return True
        except Exception as e:
            print(f"Atomic write failed: {e}", file=sys.stderr)
            return False

    def get_current_stage(self) -> Optional[str]:
        """Get current pipeline stage from state."""
        state = self.read_state()
        return state.get("pipeline_stage") if state else None

    def get_project_status(self) -> Optional[str]:
        """Get project status from state."""
        state = self.read_state()
        return state.get("project_status") if state else None

    def get_active_ticket(self) -> Optional[str]:
        """Get active ticket ID from state."""
        state = self.read_state()
        return state.get("active_ticket_id") if state else None

    def get_tickets(self) -> Dict:
        """Get all tickets from state."""
        state = self.read_state()
        return state.get("tickets", {}) if state else {}

    def get_findings(self) -> Dict:
        """Get all findings from state."""
        state = self.read_state()
        return state.get("findings", {}) if state else {}

    def can_start_ticket(self, ticket_id: str) -> tuple[bool, Optional[str]]:
        """Check if a ticket can start (all dependencies COMPLETE)."""
        state = self.read_state()
        if not state:
            return False, "No valid state"

        tickets = state.get("tickets", {})
        ticket = tickets.get(ticket_id)
        if not ticket:
            return False, f"Ticket {ticket_id} not found"

        # Check if already in progress or complete
        if ticket["status"] in [TicketStatus.IN_PROGRESS.value, TicketStatus.COMPLETE.value, TicketStatus.INVALIDATED.value]:
            return False, f"Ticket {ticket_id} already {ticket['status']}"

        # Check no other active ticket
        if state.get("active_ticket_id") and state["active_ticket_id"] != ticket_id:
            return False, f"Another ticket {state['active_ticket_id']} is active"

        # Check stage
        if state["pipeline_stage"] not in [PipelineStage.IMPLEMENTATION.value, PipelineStage.REVIEW.value]:
            return False, f"Cannot start ticket in stage {state['pipeline_stage']}"

        return True, None

    def start_ticket(self, ticket_id: str) -> bool:
        """Start a ticket (TODO -> IN_PROGRESS) via transition engine after dependency check."""
        state = self.read_state()
        if not state:
            return False

        # Check dependencies via scheduler
        from workflow import Workflow
        ticket_files = Workflow(self).graph(state)
        can_start, reason = self.dependency_scheduler.can_start_ticket(state, ticket_id, ticket_files)
        if not can_start:
            print(f"Start ticket failed: {reason}", file=sys.stderr)
            return False

        # Use transition engine for state transition
        result = self.transition_engine.start_ticket(state, ticket_id)
        if result.success:
            return self.write_state_atomic(result.new_state)
        else:
            print(f"Start ticket failed: {result.error}", file=sys.stderr)
            return False

    def _complete_ticket_internal(self, ticket_id: str) -> bool:
        """Internal: Complete a ticket via Review PASS (only allowed path to COMPLETE)."""
        print("Completion requires Workflow review evidence", file=sys.stderr)
        return False

    def pause_project(self, reason: str, decision_ref: str) -> bool:
        """Pause project with reason and decision reference."""
        from workflow import Workflow
        try:
            Workflow(self).pause(reason, decision_ref)
            return True
        except (ValueError, OSError, RuntimeError) as exc:
            print(str(exc), file=sys.stderr)
            return False

    def resume_project(self) -> bool:
        from workflow import Workflow
        try:
            Workflow(self).resume()
            return True
        except (ValueError, OSError, RuntimeError) as exc:
            print(str(exc), file=sys.stderr)
            return False

    def increment_review_attempts(self, ticket_id: str):
        print("Use review-verdict with a review payload", file=sys.stderr)
        return False, 0

    def add_finding(self, finding_id: str, finding_data: Dict) -> bool:
        """Add or update a finding via transition engine."""
        state = self.read_state()
        if not state:
            return False

        result = self.transition_engine.add_finding(state, finding_id, finding_data)
        if result.success:
            return self.write_state_atomic(result.new_state)
        else:
            print(f"Add finding failed: {result.error}", file=sys.stderr)
            return False

    def resolve_finding(self, finding_id: str) -> bool:
        """Mark finding as RESOLVED via transition engine."""
        state = self.read_state()
        if not state:
            return False

        result = self.transition_engine.update_finding_status(state, finding_id, FindingStatus.RESOLVED)
        if result.success:
            return self.write_state_atomic(result.new_state)
        else:
            print(f"Resolve finding failed: {result.error}", file=sys.stderr)
            return False

    def recover_from_state(self) -> Optional[Dict]:
        """Recover process from state after restart. Returns recovery info."""
        state = self.read_state()
        if not state:
            return None

        return {
            "project_status": state["project_status"],
            "pipeline_stage": state["pipeline_stage"],
            "stage_status": state["stage_status"],
            "active_ticket_id": state["active_ticket_id"],
            "pause": state.get("pause"),
            "tickets": state["tickets"],
            "findings": state["findings"]
        }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Harness Runner")
    parser.add_argument("command", choices=[
        "read", "validate", "start-ticket", "complete-ticket",
        "pause", "resume", "recover", "increment-review",
        "add-finding", "resolve-finding",
        "gate-verdict", "review-verdict", "ready-for-review",
        "set-ready-for-gate", "mark-ticket-ready-for-review",
        "executable-tickets", "next-ticket", "blocked-tickets", "validate-deps",
        "fix-loop-memory", "update-fix-memory", "init", "verify-ticket", "snapshot", "decide"
    ])
    parser.add_argument("--ticket", help="Ticket ID")
    parser.add_argument("--reason", help="Pause reason")
    parser.add_argument("--decision-ref", help="Decision reference")
    parser.add_argument("--finding-id", help="Finding ID")
    parser.add_argument("--finding-data", help="Finding data as JSON")
    parser.add_argument("--verdict", help="Verdict (PASS, FIX_REQUIRED, USER_DECISION_REQUIRED)")

    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--review", type=Path)
    parser.add_argument("--handoff", type=Path)
    parser.add_argument("--trust-commands", action="store_true")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--option")
    parser.add_argument("--rationale")
    parser.add_argument("--source")
    args = parser.parse_args()
    runner = HarnessRunner(args.project_root)
    from workflow import Workflow
    workflow = Workflow(runner, trusted=args.trust_commands, timeout=args.timeout)
    if args.command in ("complete-ticket", "ready-for-review", "increment-review"):
        parser.error("Unsupported command; use mark-ticket-ready-for-review and review-verdict --review --handoff")
    if args.command in ("init", "verify-ticket", "snapshot", "decide"):
        if args.command == "init": workflow.initialize()
        elif args.command == "snapshot":
            from storage import source_hash
            print(source_hash(runner.project_root))
        elif args.command == "verify-ticket": print(json.dumps(workflow.verify(args.ticket), indent=2))
        else: workflow.decide(args.option, args.rationale, args.source)
        return

    if args.command == "read":
        state = runner.read_state()
        if state:
            print(json.dumps(state, indent=2, ensure_ascii=False))
        else:
            print("No valid state found", file=sys.stderr)
            sys.exit(1)

    elif args.command == "validate":
        state = runner.read_state()
        if state:
            print("State is valid")
        else:
            print("State is invalid or missing", file=sys.stderr)
            sys.exit(1)

    elif args.command == "start-ticket":
        if not args.ticket:
            print("--ticket required", file=sys.stderr)
            sys.exit(1)
        if runner.start_ticket(args.ticket):
            print(f"Started ticket {args.ticket}")
        else:
            print(f"Failed to start ticket {args.ticket}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "pause":
        if not args.reason or not args.decision_ref:
            print("--reason and --decision-ref required", file=sys.stderr)
            sys.exit(1)
        if runner.pause_project(args.reason, args.decision_ref):
            print("Project paused")
        else:
            print("Failed to pause project", file=sys.stderr)
            sys.exit(1)

    elif args.command == "resume":
        if runner.resume_project():
            print("Project resumed")
        else:
            print("Failed to resume project", file=sys.stderr)
            sys.exit(1)

    elif args.command == "recover":
        recovery = runner.recover_from_state()
        if recovery:
            print(json.dumps(recovery, indent=2, ensure_ascii=False))
        else:
            print("No valid state to recover from", file=sys.stderr)
            sys.exit(1)

    elif args.command == "increment-review":
        if not args.ticket:
            print("--ticket required", file=sys.stderr)
            sys.exit(1)
        success, attempts = runner.increment_review_attempts(args.ticket)
        if success:
            print(f"Review attempts for {args.ticket}: {attempts}")
        else:
            print(f"Failed to increment review attempts", file=sys.stderr)
            sys.exit(1)

    elif args.command == "add-finding":
        if not args.finding_id or not args.finding_data:
            print("--finding-id and --finding-data required", file=sys.stderr)
            sys.exit(1)
        finding_data = json.loads(args.finding_data)
        if runner.add_finding(args.finding_id, finding_data):
            print(f"Added finding {args.finding_id}")
        else:
            print(f"Failed to add finding", file=sys.stderr)
            sys.exit(1)

    elif args.command == "resolve-finding":
        if not args.finding_id:
            print("--finding-id required", file=sys.stderr)
            sys.exit(1)
        if runner.resolve_finding(args.finding_id):
            print(f"Resolved finding {args.finding_id}")
        else:
            print(f"Failed to resolve finding", file=sys.stderr)
            sys.exit(1)

    elif args.command == "gate-verdict":
        if not args.verdict:
            print("--verdict required", file=sys.stderr)
            sys.exit(1)
        state = runner.read_state()
        if not state:
            print("No valid state", file=sys.stderr)
            sys.exit(1)
        try:
            verdict = GateVerdict(args.verdict)
        except ValueError:
            print(f"Invalid verdict: {args.verdict}", file=sys.stderr)
            sys.exit(1)
        workflow.gate(args.verdict, args.decision_ref)
        print(f"Gate verdict {args.verdict} processed")

    elif args.command == "review-verdict":
        if not args.ticket or not args.verdict:
            print("--ticket and --verdict required", file=sys.stderr)
            sys.exit(1)
        workflow.review(args.ticket, args.verdict, args.review, args.handoff)
        print(f"Review verdict {args.verdict} processed for {args.ticket}")

    elif args.command == "set-ready-for-gate":
        state = runner.read_state()
        if not state:
            print("No valid state", file=sys.stderr)
            sys.exit(1)
        result = runner.transition_engine.set_stage_ready_for_gate(state)
        if result.success:
            if runner.write_state_atomic(result.new_state):
                print(f"Stage {state['pipeline_stage']} ready for gate")
            else:
                print("Failed to write state", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"Failed: {result.error}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "mark-ticket-ready-for-review":
        if not args.ticket:
            print("--ticket required", file=sys.stderr)
            sys.exit(1)
        state = runner.read_state()
        if not state:
            print("No valid state", file=sys.stderr)
            sys.exit(1)
        result = runner.transition_engine.mark_ticket_ready_for_review(state, args.ticket)
        if result.success:
            if runner.write_state_atomic(result.new_state):
                print(f"Ticket {args.ticket} marked ready for review")
            else:
                print("Failed to write state", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"Failed: {result.error}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "executable-tickets":
        state = runner.read_state()
        if not state:
            print("No valid state", file=sys.stderr)
            sys.exit(1)
        ticket_files = runner.dependency_scheduler.load_ticket_files()
        executable = runner.dependency_scheduler.get_executable_tickets(state, ticket_files)
        if executable:
            print("Executable tickets (in approval order):")
            for tid in executable:
                print(f"  {tid}")
        else:
            print("No tickets ready to execute")

    elif args.command == "next-ticket":
        state = runner.read_state()
        if not state:
            print("No valid state", file=sys.stderr)
            sys.exit(1)
        ticket_files = runner.dependency_scheduler.load_ticket_files()
        next_ticket = runner.dependency_scheduler.get_next_ticket(state, ticket_files)
        if next_ticket:
            print(next_ticket)
        else:
            print("No next ticket available")

    elif args.command == "blocked-tickets":
        state = runner.read_state()
        if not state:
            print("No valid state", file=sys.stderr)
            sys.exit(1)
        ticket_files = runner.dependency_scheduler.load_ticket_files()
        blocked = runner.dependency_scheduler.get_blocked_tickets(state, ticket_files)
        if blocked:
            print("Blocked tickets:")
            for tid, blockers in blocked.items():
                print(f"  {tid}: blocked by {', '.join(blockers)}")
        else:
            print("No blocked tickets")

    elif args.command == "validate-deps":
        ticket_files = runner.dependency_scheduler.load_ticket_files()
        errors = runner.dependency_scheduler.validate_dependencies(ticket_files)
        if errors:
            print("Dependency validation errors:")
            for err in errors:
                print(f"  - {err}")
            sys.exit(1)
        else:
            print("All dependencies valid")

    elif args.command == "fix-loop-memory":
        if not args.ticket:
            print("--ticket required", file=sys.stderr)
            sys.exit(1)
        state = runner.read_state()
        if not state:
            print("No valid state", file=sys.stderr)
            sys.exit(1)
        memory = runner.transition_engine.get_fix_loop_memory(state, args.ticket)
        if memory:
            print(json.dumps(memory, indent=2, ensure_ascii=False))
        else:
            print(f"No fix loop memory for ticket {args.ticket}")

    elif args.command == "update-fix-memory":
        if not args.ticket or not args.finding_data:
            print("--ticket and --finding-data (fix summary) required", file=sys.stderr)
            sys.exit(1)
        state = runner.read_state()
        if not state:
            print("No valid state", file=sys.stderr)
            sys.exit(1)
        fix_summary = args.finding_data
        result = runner.transition_engine.update_fix_loop_memory(state, args.ticket, fix_summary)
        if result.success:
            if runner.write_state_atomic(result.new_state):
                print(f"Updated fix loop memory for {args.ticket}")
            else:
                print("Failed to write state", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"Failed: {result.error}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Harness error: {exc}", file=sys.stderr)
        sys.exit(1)