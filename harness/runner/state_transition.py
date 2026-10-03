#!/usr/bin/env python3
"""
State Transition Engine for Harness

Enforces all valid state transitions per Harness spec.
- Rejects undefined transitions
- Developer cannot directly set Ticket to COMPLETE
- Only Review PASS can complete Ticket
"""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass


class ProjectStatus(Enum):
    IN_PROGRESS = "IN_PROGRESS"
    PAUSED = "PAUSED"
    COMPLETE = "COMPLETE"


class PipelineStage(Enum):
    DISCOVERY = "DISCOVERY"
    SPEC = "SPEC"
    TICKETS = "TICKETS"
    IMPLEMENTATION = "IMPLEMENTATION"
    REVIEW = "REVIEW"


class StageStatus(Enum):
    IN_PROGRESS = "IN_PROGRESS"
    READY_FOR_GATE = "READY_FOR_GATE"


class TicketStatus(Enum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    COMPLETE = "COMPLETE"
    INVALIDATED = "INVALIDATED"
    PAUSED = "PAUSED"


class FindingStatus(Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"


class ReviewVerdict(Enum):
    PASS = "PASS"
    FIX_REQUIRED = "FIX_REQUIRED"
    USER_DECISION_REQUIRED = "USER_DECISION_REQUIRED"


class GateVerdict(Enum):
    PASS = "PASS"
    FIX_REQUIRED = "FIX_REQUIRED"
    USER_DECISION_REQUIRED = "USER_DECISION_REQUIRED"


class PauseReason(Enum):
    GATE_USER_DECISION_REQUIRED = "GATE_USER_DECISION_REQUIRED"
    REVIEW_USER_DECISION_REQUIRED = "REVIEW_USER_DECISION_REQUIRED"
    RETRY_LIMIT_REACHED = "RETRY_LIMIT_REACHED"
    PLAN_CHANGE_REQUIRES_DECISION = "PLAN_CHANGE_REQUIRES_DECISION"


@dataclass
class TransitionResult:
    success: bool
    new_state: Optional[Dict] = None
    error: Optional[str] = None


class StateTransitionEngine:
    """
    Enforces all valid state transitions for the Harness.
    
    State Model:
    - Project Status: IN_PROGRESS | PAUSED | COMPLETE
    - Pipeline Stage: DISCOVERY | SPEC | TICKETS | IMPLEMENTATION | REVIEW
    - Stage Status: IN_PROGRESS | READY_FOR_GATE
    - Active Ticket: T-<NNN> | null
    - Pause: {reason, decision_ref} | null
    - Tickets: {T-<NNN>: {status, review_attempts, active_findings}}
    - Findings: {F-<NNN>: {ticket_id, finding_key, status, ...}}
    """

    # Valid Planning Stage Transitions (DISCOVERY, SPEC, TICKETS)
    PLANNING_STAGE_TRANSITIONS = {
        ("DISCOVERY", "IN_PROGRESS"): ["READY_FOR_GATE"],
        ("DISCOVERY", "READY_FOR_GATE"): ["SPEC"],
        ("SPEC", "IN_PROGRESS"): ["READY_FOR_GATE"],
        ("SPEC", "READY_FOR_GATE"): ["TICKETS"],
        ("TICKETS", "IN_PROGRESS"): ["READY_FOR_GATE"],
        ("TICKETS", "READY_FOR_GATE"): ["IMPLEMENTATION"],
    }

    # Valid Gate Verdicts per Stage
    GATE_VERDICTS = {
        "DISCOVERY": [GateVerdict.PASS, GateVerdict.FIX_REQUIRED, GateVerdict.USER_DECISION_REQUIRED],
        "SPEC": [GateVerdict.PASS, GateVerdict.FIX_REQUIRED, GateVerdict.USER_DECISION_REQUIRED],
        "TICKETS": [GateVerdict.PASS, GateVerdict.FIX_REQUIRED, GateVerdict.USER_DECISION_REQUIRED],
    }

    # Valid Ticket Status Transitions
    TICKET_TRANSITIONS = {
        TicketStatus.TODO: [TicketStatus.IN_PROGRESS, TicketStatus.INVALIDATED],
        TicketStatus.IN_PROGRESS: [TicketStatus.READY_FOR_REVIEW, TicketStatus.PAUSED, TicketStatus.INVALIDATED],
        TicketStatus.READY_FOR_REVIEW: [TicketStatus.COMPLETE, TicketStatus.IN_PROGRESS, TicketStatus.PAUSED, TicketStatus.INVALIDATED],
        TicketStatus.COMPLETE: [],  # Terminal state
        TicketStatus.INVALIDATED: [TicketStatus.TODO],  # Can be re-planned
        TicketStatus.PAUSED: [TicketStatus.IN_PROGRESS, TicketStatus.INVALIDATED],
    }

    # Valid Project Status Transitions
    PROJECT_TRANSITIONS = {
        ProjectStatus.IN_PROGRESS: [ProjectStatus.PAUSED, ProjectStatus.COMPLETE],
        ProjectStatus.PAUSED: [ProjectStatus.IN_PROGRESS],
        ProjectStatus.COMPLETE: [],  # Terminal
    }

    # Stage progression order
    STAGE_ORDER = [
        PipelineStage.DISCOVERY,
        PipelineStage.SPEC,
        PipelineStage.TICKETS,
        PipelineStage.IMPLEMENTATION,
        PipelineStage.REVIEW,
    ]

    def __init__(self, project_root=None):
        self.project_root = Path(project_root or Path.cwd()).resolve()

    # ============================================================
    # PLANNING STAGE TRANSITIONS
    # ============================================================

    def advance_planning_stage(self, state: Dict, gate_verdict: GateVerdict) -> TransitionResult:
        """Advance planning stage based on gate verdict."""
        current_stage = PipelineStage(state["pipeline_stage"])
        current_status = StageStatus(state["stage_status"])

        if state["project_status"] != "IN_PROGRESS":
            return TransitionResult(False, error="Project is not in progress")
        # Only allow gate when stage_status is READY_FOR_GATE
        if current_status != StageStatus.READY_FOR_GATE:
            return TransitionResult(False, error=f"Stage {current_stage.value} not ready for gate (status: {current_status.value})")

        # Validate verdict
        if gate_verdict not in self.GATE_VERDICTS.get(current_stage.value, []):
            return TransitionResult(False, error=f"Invalid verdict {gate_verdict.value} for stage {current_stage.value}")

        if gate_verdict == GateVerdict.PASS:
            # Advance to next stage
            next_stage = self._get_next_planning_stage(current_stage)
            if next_stage is None:
                return TransitionResult(False, error=f"No next stage after {current_stage.value}")

            # If advancing from TICKETS to IMPLEMENTATION, validate all ticket dependencies
            if current_stage == PipelineStage.TICKETS and next_stage == PipelineStage.IMPLEMENTATION:
                dep_errors = self._validate_ticket_dependencies(state)
                if dep_errors:
                    return TransitionResult(False, error="; ".join(dep_errors))

            new_state = self._deep_copy_state(state)
            new_state["pipeline_stage"] = next_stage.value
            new_state["stage_status"] = StageStatus.IN_PROGRESS.value

            # If advancing to IMPLEMENTATION, need to start first available ticket
            if next_stage == PipelineStage.IMPLEMENTATION:
                # Find first TODO ticket to start (respecting dependencies)
                tickets = new_state.get("tickets", {})
                from dependency_scheduler import DependencyScheduler
                scheduler = DependencyScheduler(self.project_root)
                first_todo = scheduler.get_next_ticket(new_state, scheduler.load_ticket_files())
                if first_todo:
                    new_state["tickets"][first_todo]["status"] = TicketStatus.IN_PROGRESS.value
                    new_state["active_ticket_id"] = first_todo
                else:
                    # No tickets yet - this is allowed, but active_ticket_id must be set when work starts
                    new_state["active_ticket_id"] = None
            else:
                new_state["active_ticket_id"] = None  # Must be null in planning stages
            
            return TransitionResult(True, new_state)

        elif gate_verdict == GateVerdict.FIX_REQUIRED:
            # Stay in same stage, status back to IN_PROGRESS
            new_state = self._deep_copy_state(state)
            new_state["stage_status"] = StageStatus.IN_PROGRESS.value
            return TransitionResult(True, new_state)

        elif gate_verdict == GateVerdict.USER_DECISION_REQUIRED:
            # Pause project - caller must provide decision_ref
            return TransitionResult(False, error="USER_DECISION_REQUIRED requires pause_project call with decision_ref")

        return TransitionResult(False, error=f"Unhandled verdict: {gate_verdict}")

    def _get_next_planning_stage(self, current: PipelineStage) -> Optional[PipelineStage]:
        """Get next planning stage."""
        planning_stages = [PipelineStage.DISCOVERY, PipelineStage.SPEC, PipelineStage.TICKETS]
        try:
            idx = planning_stages.index(current)
            if idx + 1 < len(planning_stages):
                return planning_stages[idx + 1]
            # After TICKETS, go to IMPLEMENTATION
            if current == PipelineStage.TICKETS:
                return PipelineStage.IMPLEMENTATION
        except ValueError:
            pass
        return None

    def _validate_ticket_dependencies(self, state: Dict) -> List[str]:
        """Validate all ticket dependencies are satisfied before entering IMPLEMENTATION."""
        from dependency_scheduler import DependencyScheduler
        
        scheduler = DependencyScheduler(self.project_root)
        ticket_files = scheduler.load_ticket_files()
        
        if not ticket_files:
            return ["No ticket files found in .harness/tickets/"]
        
        errors = scheduler.validate_dependencies(ticket_files)
        
        # Check that all tickets in state have corresponding ticket files
        state_tickets = set(state.get("tickets", {}).keys())
        file_tickets = set(ticket_files.keys())
        
        missing_in_files = state_tickets - file_tickets
        if missing_in_files:
            errors.append(f"Tickets in state but not in .harness/tickets/: {', '.join(sorted(missing_in_files))}")
        
        return errors

    def set_stage_ready_for_gate(self, state: Dict) -> TransitionResult:
        """Mark current planning stage as ready for gate."""
        if state["project_status"] != "IN_PROGRESS":
            return TransitionResult(False, error="Project is not in progress")
        current_stage = state["pipeline_stage"]
        if current_stage not in [s.value for s in [PipelineStage.DISCOVERY, PipelineStage.SPEC, PipelineStage.TICKETS]]:
            return TransitionResult(False, error=f"Stage {current_stage} is not a planning stage")

        if state["stage_status"] != StageStatus.IN_PROGRESS.value:
            return TransitionResult(False, error=f"Stage {current_stage} already {state['stage_status']}")

        new_state = state.copy()
        new_state["stage_status"] = StageStatus.READY_FOR_GATE.value
        return TransitionResult(True, new_state)

    # ============================================================
    # TICKET TRANSITIONS (IMPLEMENTATION/REVIEW stages)
    # ============================================================

    def start_ticket(self, state: Dict, ticket_id: str) -> TransitionResult:
        """Start a ticket (TODO -> IN_PROGRESS)."""
        # Validate project state
        if state["pipeline_stage"] not in [PipelineStage.IMPLEMENTATION.value, PipelineStage.REVIEW.value]:
            return TransitionResult(False, error=f"Cannot start ticket in stage {state['pipeline_stage']}")

        if state["project_status"] != ProjectStatus.IN_PROGRESS.value:
            return TransitionResult(False, error=f"Project not in progress: {state['project_status']}")

        if state["project_status"] != "IN_PROGRESS":
            return TransitionResult(False, error="Project is not in progress")
        tickets = state.get("tickets", {})
        if ticket_id not in tickets:
            return TransitionResult(False, error=f"Ticket {ticket_id} not found")

        ticket = tickets[ticket_id]
        current_status = TicketStatus(ticket["status"])

        # Check valid transition
        if TicketStatus.IN_PROGRESS not in self.TICKET_TRANSITIONS.get(current_status, []):
            return TransitionResult(False, error=f"Cannot start ticket from {current_status.value}")

        # Check dependencies (all dependencies must be COMPLETE)
        # This requires ticket files - for now we check state only
        # Full implementation would read .harness/tickets/T-<NNN>.md

        # Check no other active ticket
        if state.get("active_ticket_id") and state["active_ticket_id"] != ticket_id:
            return TransitionResult(False, error=f"Another ticket {state['active_ticket_id']} is active")

        new_state = self._deep_copy_state(state)
        new_state["tickets"][ticket_id]["status"] = TicketStatus.IN_PROGRESS.value
        new_state["active_ticket_id"] = ticket_id
        new_state["stage_status"] = StageStatus.IN_PROGRESS.value
        return TransitionResult(True, new_state)

    def mark_ticket_ready_for_review(self, state: Dict, ticket_id: str) -> TransitionResult:
        """Mark ticket as READY_FOR_REVIEW (IN_PROGRESS -> READY_FOR_REVIEW)."""
        if state["project_status"] != "IN_PROGRESS":
            return TransitionResult(False, error="Project is not in progress")
        tickets = state.get("tickets", {})
        if ticket_id not in tickets:
            return TransitionResult(False, error=f"Ticket {ticket_id} not found")

        if state.get("active_ticket_id") != ticket_id:
            return TransitionResult(False, error=f"Ticket {ticket_id} is not active")

        ticket = tickets[ticket_id]
        current_status = TicketStatus(ticket["status"])

        if TicketStatus.READY_FOR_REVIEW not in self.TICKET_TRANSITIONS.get(current_status, []):
            return TransitionResult(False, error=f"Cannot mark ready for review from {current_status.value}")

        new_state = self._deep_copy_state(state)
        new_state["tickets"][ticket_id]["status"] = TicketStatus.READY_FOR_REVIEW.value
        return TransitionResult(True, new_state)

    def complete_ticket_via_review(self, state: Dict, ticket_id: str) -> TransitionResult:
        """
        Complete a ticket via Review PASS.
        DEVELOPER CANNOT CALL THIS DIRECTLY - only via review verdict PASS.
        """
        return TransitionResult(False, error="Completion requires Workflow review evidence")

    def invalidate_ticket(self, state: Dict, ticket_id: str) -> TransitionResult:
        """Invalidate a ticket (any -> INVALIDATED)."""
        if state["project_status"] != "IN_PROGRESS":
            return TransitionResult(False, error="Project is not in progress")
        tickets = state.get("tickets", {})
        if ticket_id not in tickets:
            return TransitionResult(False, error=f"Ticket {ticket_id} not found")

        ticket = tickets[ticket_id]
        current_status = TicketStatus(ticket["status"])

        if TicketStatus.INVALIDATED not in self.TICKET_TRANSITIONS.get(current_status, []):
            return TransitionResult(False, error=f"Cannot invalidate ticket from {current_status.value}")

        new_state = self._deep_copy_state(state)
        new_state["tickets"][ticket_id]["status"] = TicketStatus.INVALIDATED.value
        if state.get("active_ticket_id") == ticket_id:
            new_state["active_ticket_id"] = None
        return TransitionResult(True, new_state)

    def pause_ticket(self, state: Dict, ticket_id: str) -> TransitionResult:
        """Pause a ticket (IN_PROGRESS/READY_FOR_REVIEW -> PAUSED)."""
        if state["project_status"] != "IN_PROGRESS":
            return TransitionResult(False, error="Project is not in progress")
        tickets = state.get("tickets", {})
        if ticket_id not in tickets:
            return TransitionResult(False, error=f"Ticket {ticket_id} not found")

        ticket = tickets[ticket_id]
        current_status = TicketStatus(ticket["status"])

        if TicketStatus.PAUSED not in self.TICKET_TRANSITIONS.get(current_status, []):
            return TransitionResult(False, error=f"Cannot pause ticket from {current_status.value}")

        new_state = self._deep_copy_state(state)
        new_state["tickets"][ticket_id]["status"] = TicketStatus.PAUSED.value
        if state.get("active_ticket_id") == ticket_id:
            new_state["active_ticket_id"] = None
        return TransitionResult(True, new_state)

    def resume_ticket(self, state: Dict, ticket_id: str) -> TransitionResult:
        """Resume a paused ticket (PAUSED -> IN_PROGRESS)."""
        if state["project_status"] != "IN_PROGRESS":
            return TransitionResult(False, error="Project is not in progress")
        tickets = state.get("tickets", {})
        if ticket_id not in tickets:
            return TransitionResult(False, error=f"Ticket {ticket_id} not found")

        ticket = tickets[ticket_id]
        current_status = TicketStatus(ticket["status"])

        if TicketStatus.IN_PROGRESS not in self.TICKET_TRANSITIONS.get(current_status, []):
            return TransitionResult(False, error=f"Cannot resume ticket from {current_status.value}")

        if state.get("active_ticket_id"):
            return TransitionResult(False, error=f"Another ticket {state['active_ticket_id']} is active")

        new_state = self._deep_copy_state(state)
        new_state["tickets"][ticket_id]["status"] = TicketStatus.IN_PROGRESS.value
        new_state["active_ticket_id"] = ticket_id
        return TransitionResult(True, new_state)

    # ============================================================
    # REVIEW VERDICT PROCESSING
    # ============================================================

    def process_review_verdict(self, state: Dict, ticket_id: str, verdict: ReviewVerdict) -> TransitionResult:
        """Process review verdict and update state accordingly."""
        if state["project_status"] != "IN_PROGRESS":
            return TransitionResult(False, error="Project is not in progress")
        tickets = state.get("tickets", {})
        if ticket_id not in tickets:
            return TransitionResult(False, error=f"Ticket {ticket_id} not found")

        if state.get("active_ticket_id") != ticket_id:
            return TransitionResult(False, error=f"Ticket {ticket_id} is not active")

        ticket = tickets[ticket_id]
        if ticket["status"] != TicketStatus.READY_FOR_REVIEW.value:
            return TransitionResult(False, error=f"Ticket {ticket_id} not ready for review (status: {ticket['status']})")

        if verdict == ReviewVerdict.PASS:
            return TransitionResult(False, error="Completion requires Workflow review evidence")

        elif verdict == ReviewVerdict.FIX_REQUIRED:
            # Increment review_attempts, move back to IN_PROGRESS
            new_state = self._deep_copy_state(state)
            new_state["tickets"][ticket_id]["review_attempts"] += 1
            new_state["tickets"][ticket_id]["status"] = TicketStatus.IN_PROGRESS.value
            attempts = new_state["tickets"][ticket_id]["review_attempts"]

            # Build fix loop memory for the next implementation attempt
            fix_memory = self._build_fix_loop_memory(new_state, ticket_id, attempts)
            new_state["tickets"][ticket_id]["fix_loop_memory"] = fix_memory

            # Auto-pause at 3 attempts
            if attempts >= new_state["tickets"][ticket_id].get("retry_limit", 3):
                new_state["project_status"] = ProjectStatus.PAUSED.value
                ticket_num = ''.join(filter(str.isdigit, ticket_id))
                new_state["pause"] = {
                    "reason": PauseReason.RETRY_LIMIT_REACHED.value,
                    "decision_ref": f"DEC-{ticket_num.zfill(3)}"
                }

            return TransitionResult(True, new_state)

        elif verdict == ReviewVerdict.USER_DECISION_REQUIRED:
            # Pause project - caller provides decision_ref
            return TransitionResult(False, error="USER_DECISION_REQUIRED requires pause_project call")

        return TransitionResult(False, error=f"Unknown verdict: {verdict}")

    # ============================================================
    # GATE VERDICT PROCESSING (for planning stages)
    # ============================================================

    def process_gate_verdict(self, state: Dict, verdict: GateVerdict, decision_ref: Optional[str] = None) -> TransitionResult:
        """Process gate verdict for planning stages."""
        current_stage = PipelineStage(state["pipeline_stage"])

        if current_stage not in [PipelineStage.DISCOVERY, PipelineStage.SPEC, PipelineStage.TICKETS]:
            return TransitionResult(False, error=f"Gate verdict not applicable in stage {current_stage.value}")

        if state["stage_status"] != StageStatus.READY_FOR_GATE.value:
            return TransitionResult(False, error=f"Stage not ready for gate: {state['stage_status']}")

        if verdict == GateVerdict.PASS:
            return self.advance_planning_stage(state, verdict)

        elif verdict == GateVerdict.FIX_REQUIRED:
            new_state = self._deep_copy_state(state)
            new_state["stage_status"] = StageStatus.IN_PROGRESS.value
            return TransitionResult(True, new_state)

        elif verdict == GateVerdict.USER_DECISION_REQUIRED:
            if not decision_ref:
                return TransitionResult(False, error="USER_DECISION_REQUIRED requires decision_ref")
            new_state = self._deep_copy_state(state)
            new_state["project_status"] = ProjectStatus.PAUSED.value
            new_state["pause"] = {
                "reason": PauseReason.GATE_USER_DECISION_REQUIRED.value,
                "decision_ref": decision_ref
            }
            return TransitionResult(True, new_state)

        return TransitionResult(False, error=f"Unknown gate verdict: {verdict}")

    # ============================================================
    # PROJECT PAUSE/RESUME
    # ============================================================

    def pause_project(self, state: Dict, reason: PauseReason, decision_ref: str) -> TransitionResult:
        """Pause the project and create DEC artifact."""
        if state["project_status"] == ProjectStatus.PAUSED.value:
            return TransitionResult(False, error="Project already paused")

        if state["project_status"] == ProjectStatus.COMPLETE.value:
            return TransitionResult(False, error="Cannot pause completed project")

        # Validate reason
        try:
            PauseReason(reason)
        except ValueError:
            return TransitionResult(False, error=f"Invalid pause reason: {reason}")

        # Validate decision_ref format
        if not decision_ref or not decision_ref.startswith("DEC-"):
            return TransitionResult(False, error="Invalid decision_ref format (must be DEC-<NNN>)")

        new_state = self._deep_copy_state(state)
        new_state["project_status"] = ProjectStatus.PAUSED.value
        new_state["pause"] = {
            "reason": reason.value if isinstance(reason, PauseReason) else reason,
            "decision_ref": decision_ref
        }
        
        return TransitionResult(True, new_state)

    def resume_project(self, state: Dict) -> TransitionResult:
        return TransitionResult(False, error="Resume requires Workflow decision validation")

    # ============================================================
    # FINDING TRANSITIONS
    # ============================================================

    def add_finding(self, state: Dict, finding_id: str, finding_data: Dict) -> TransitionResult:
        """Add a new finding."""
        # Validate finding_key format
        finding_key = finding_data.get("finding_key", "")
        if not finding_key or not all(c.islower() or c.isdigit() or c == '-' for c in finding_key):
            return TransitionResult(False, error=f"Invalid finding_key format: {finding_key}")

        # Check ticket exists
        ticket_id = finding_data.get("ticket_id")
        if not ticket_id or ticket_id not in state.get("tickets", {}):
            return TransitionResult(False, error=f"Ticket {ticket_id} not found")

        new_state = self._deep_copy_state(state)
        new_state["findings"][finding_id] = finding_data

        # Add to ticket's active_findings
        if finding_id not in new_state["tickets"][ticket_id]["active_findings"]:
            new_state["tickets"][ticket_id]["active_findings"].append(finding_id)

        return TransitionResult(True, new_state)

    def update_finding_status(self, state: Dict, finding_id: str, new_status: FindingStatus) -> TransitionResult:
        """Update finding status (OPEN -> RESOLVED, RESOLVED -> REOPENED)."""
        if finding_id not in state.get("findings", {}):
            return TransitionResult(False, error=f"Finding {finding_id} not found")

        finding = state["findings"][finding_id]
        current_status = FindingStatus(finding["status"])

        # Valid transitions
        valid_transitions = {
            FindingStatus.OPEN: [FindingStatus.RESOLVED],
            FindingStatus.RESOLVED: [FindingStatus.REOPENED],
            FindingStatus.REOPENED: [FindingStatus.RESOLVED],
        }

        if new_status not in valid_transitions.get(current_status, []):
            return TransitionResult(False, error=f"Invalid finding transition: {current_status.value} -> {new_status.value}")

        new_state = self._deep_copy_state(state)
        new_state["findings"][finding_id]["status"] = new_status.value

        # Update ticket's active_findings
        ticket_id = finding.get("ticket_id")
        if ticket_id and ticket_id in new_state["tickets"]:
            active = new_state["tickets"][ticket_id]["active_findings"]
            if new_status == FindingStatus.RESOLVED:
                if finding_id in active:
                    active.remove(finding_id)
            elif new_status == FindingStatus.REOPENED:
                if finding_id not in active:
                    active.append(finding_id)
                # Update last_seen_attempt
                ticket = new_state["tickets"][ticket_id]
                new_state["findings"][finding_id]["last_seen_attempt"] = ticket["review_attempts"]
                new_state["findings"][finding_id]["reopen_count"] += 1

        return TransitionResult(True, new_state)

    # ============================================================
    # HELPER METHODS
    # ============================================================

    def _deep_copy_state(self, state: Dict) -> Dict:
        """Create a deep copy of state."""
        return json.loads(json.dumps(state))

    def _build_fix_loop_memory(self, state: Dict, ticket_id: str, attempt_number: int) -> Dict:
        """
        Build fix loop memory for the next implementation attempt.
        
        Includes:
        - Active findings for this ticket (with finding_key for continuity)
        - Previous fix summary (from last review's criteria evidence)
        - Failure reasons (from FAIL/UNVERIFIED criteria)
        - Does NOT load full review history
        - Uses finding_key for finding continuity across attempts
        """
        ticket = state["tickets"].get(ticket_id, {})
        findings = state.get("findings", {})
        
        # Get active findings for this ticket
        active_finding_ids = ticket.get("active_findings", [])
        active_findings = []
        for fid in active_finding_ids:
            if fid in findings:
                finding = findings[fid]
                active_findings.append({
                    "finding_id": fid,
                    "finding_key": finding.get("finding_key"),
                    "criterion_ref": finding.get("criterion_ref"),
                    "description": finding.get("description"),
                    "blocking": finding.get("blocking", True),
                    "status": finding.get("status"),
                    "first_detected_attempt": finding.get("first_detected_attempt"),
                    "last_seen_attempt": finding.get("last_seen_attempt"),
                    "reopen_count": finding.get("reopen_count", 0)
                })
        
        # Get previous attempt's failure info from ticket's fix_loop_memory if exists
        previous_memory = ticket.get("fix_loop_memory", {})
        # Check both fix_summary (from update_fix_loop_memory) and previous_fix_summary (from previous attempt's memory)
        previous_fix_summary = previous_memory.get("fix_summary") or previous_memory.get("previous_fix_summary", "")
        previous_failure_reasons = previous_memory.get("failure_reasons") or previous_memory.get("previous_failure_reasons", [])
        
        # Build failure reasons from current active findings (these are what caused FIX_REQUIRED)
        failure_reasons = []
        for af in active_findings:
            if af.get("blocking", True):
                failure_reasons.append({
                    "finding_key": af["finding_key"],
                    "criterion_ref": af["criterion_ref"],
                    "description": af["description"]
                })
        
        return {
            "attempt_number": attempt_number,
            "active_findings": active_findings,
            "active_finding_keys": [af["finding_key"] for af in active_findings],
            "failure_reasons": failure_reasons,
            "previous_fix_summary": previous_fix_summary,
            "previous_failure_reasons": previous_failure_reasons,
            "total_findings_count": len(active_findings),
            "blocking_findings_count": len([af for af in active_findings if af.get("blocking", True)])
        }

    def get_fix_loop_memory(self, state: Dict, ticket_id: str) -> Optional[Dict]:
        """Get fix loop memory for a ticket (for Implementation agent)."""
        ticket = state.get("tickets", {}).get(ticket_id)
        if not ticket:
            return None
        return ticket.get("fix_loop_memory")

    def update_fix_loop_memory(self, state: Dict, ticket_id: str, fix_summary: str) -> TransitionResult:
        """Update fix loop memory with the fix summary from Implementation."""
        if ticket_id not in state.get("tickets", {}):
            return TransitionResult(False, error=f"Ticket {ticket_id} not found")
        
        new_state = self._deep_copy_state(state)
        if "fix_loop_memory" not in new_state["tickets"][ticket_id]:
            new_state["tickets"][ticket_id]["fix_loop_memory"] = {}
        new_state["tickets"][ticket_id]["fix_loop_memory"]["fix_summary"] = fix_summary
        return TransitionResult(True, new_state)

    def validate_transition(self, from_state: Dict, to_state: Dict) -> Tuple[bool, Optional[str]]:
        """Validate that a transition is allowed (for testing/verification)."""
        # This is a post-hoc validation - checks if from_state -> to_state is valid
        # In practice, the engine methods above should be used to create transitions
        return False, "Generic transition validation is unsupported; use named workflow operations"


# ============================================================
# CONVENIENCE FUNCTIONS
# ============================================================

def create_initial_state() -> Dict:
    """Create initial state for a new project."""
    return {
        "schema_version": "1.1",
        "project_status": ProjectStatus.IN_PROGRESS.value,
        "pipeline_stage": PipelineStage.DISCOVERY.value,
        "stage_status": StageStatus.IN_PROGRESS.value,
        "active_ticket_id": None,
        "pause": None,
        "tickets": {},
        "findings": {}
    }


def is_terminal_state(state: Dict) -> bool:
    """Check if project is in terminal state."""
    return state["project_status"] == ProjectStatus.COMPLETE.value


def get_next_actionable_tickets(state: Dict) -> List[str]:
    """Get tickets that can be started (all dependencies COMPLETE)."""
    tickets = state.get("tickets", {})
    actionable = []
    for tid, ticket in tickets.items():
        if ticket["status"] == TicketStatus.TODO.value:
            # Check dependencies - would need ticket files
            actionable.append(tid)
    return actionable


import json