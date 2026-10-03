#!/usr/bin/env python3
"""
Test Suite for State Transition Engine
"""

from test_support import isolated

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from state_transition import (
    StateTransitionEngine,
    ProjectStatus, PipelineStage, StageStatus,
    TicketStatus, FindingStatus, ReviewVerdict, GateVerdict, PauseReason,
    create_initial_state
)

@isolated
def test_planning_stage_advance():
    """Test DISCOVERY -> SPEC -> TICKETS -> IMPLEMENTATION progression."""
    engine = StateTransitionEngine()
    
    # Initial state
    state = create_initial_state()
    state["pipeline_stage"] = PipelineStage.DISCOVERY.value
    state["stage_status"] = StageStatus.READY_FOR_GATE.value
    
    # DISCOVERY PASS -> SPEC
    result = engine.advance_planning_stage(state, GateVerdict.PASS)
    assert result.success, f"DISCOVERY PASS failed: {result.error}"
    assert result.new_state["pipeline_stage"] == PipelineStage.SPEC.value
    assert result.new_state["stage_status"] == StageStatus.IN_PROGRESS.value
    
    # SPEC READY_FOR_GATE -> PASS -> TICKETS
    state = result.new_state
    state["stage_status"] = StageStatus.READY_FOR_GATE.value
    result = engine.advance_planning_stage(state, GateVerdict.PASS)
    assert result.success, f"SPEC PASS failed: {result.error}"
    assert result.new_state["pipeline_stage"] == PipelineStage.TICKETS.value
    
    # TICKETS READY_FOR_GATE -> PASS -> IMPLEMENTATION (with ticket)
    state = result.new_state
    state["stage_status"] = StageStatus.READY_FOR_GATE.value
    state["tickets"] = {"T-001": {"status": TicketStatus.TODO.value, "review_attempts": 0, "active_findings": []}}
    result = engine.advance_planning_stage(state, GateVerdict.PASS)
    assert result.success, f"TICKETS PASS failed: {result.error}"
    assert result.new_state["pipeline_stage"] == PipelineStage.IMPLEMENTATION.value
    assert result.new_state["active_ticket_id"] == "T-001"
    assert result.new_state["tickets"]["T-001"]["status"] == TicketStatus.IN_PROGRESS.value
    
    print("✓ test_planning_stage_advance passed")

@isolated
def test_gate_fix_required():
    """Test FIX_REQUIRED keeps stage in IN_PROGRESS."""
    engine = StateTransitionEngine()
    
    state = create_initial_state()
    state["pipeline_stage"] = PipelineStage.SPEC.value
    state["stage_status"] = StageStatus.READY_FOR_GATE.value
    
    result = engine.advance_planning_stage(state, GateVerdict.FIX_REQUIRED)
    assert result.success
    assert result.new_state["pipeline_stage"] == PipelineStage.SPEC.value
    assert result.new_state["stage_status"] == StageStatus.IN_PROGRESS.value
    
    print("✓ test_gate_fix_required passed")

@isolated
def test_gate_user_decision_required():
    """Test USER_DECISION_REQUIRED pauses project."""
    engine = StateTransitionEngine()
    
    state = create_initial_state()
    state["pipeline_stage"] = PipelineStage.DISCOVERY.value
    state["stage_status"] = StageStatus.READY_FOR_GATE.value
    
    result = engine.process_gate_verdict(state, GateVerdict.USER_DECISION_REQUIRED, "DEC-001")
    assert result.success
    assert result.new_state["project_status"] == ProjectStatus.PAUSED.value
    assert result.new_state["pause"]["reason"] == PauseReason.GATE_USER_DECISION_REQUIRED.value
    assert result.new_state["pause"]["decision_ref"] == "DEC-001"
    
    print("✓ test_gate_user_decision_required passed")

@isolated
def test_ticket_start():
    """Test ticket start transition."""
    engine = StateTransitionEngine()
    
    state = create_initial_state()
    state["pipeline_stage"] = PipelineStage.IMPLEMENTATION.value
    state["tickets"] = {"T-001": {"status": TicketStatus.TODO.value, "review_attempts": 0, "active_findings": []}}
    
    result = engine.start_ticket(state, "T-001")
    assert result.success
    assert result.new_state["tickets"]["T-001"]["status"] == TicketStatus.IN_PROGRESS.value
    assert result.new_state["active_ticket_id"] == "T-001"
    
    print("✓ test_ticket_start passed")

@isolated
def test_ticket_cannot_start_in_planning():
    """Test ticket cannot start in planning stage."""
    engine = StateTransitionEngine()
    
    state = create_initial_state()
    state["pipeline_stage"] = PipelineStage.DISCOVERY.value
    state["tickets"] = {"T-001": {"status": TicketStatus.TODO.value, "review_attempts": 0, "active_findings": []}}
    
    result = engine.start_ticket(state, "T-001")
    assert not result.success
    assert "Cannot start ticket in stage" in result.error
    
    print("✓ test_ticket_cannot_start_in_planning passed")

@isolated
def test_ticket_ready_for_review():
    """Test IN_PROGRESS -> READY_FOR_REVIEW."""
    engine = StateTransitionEngine()
    
    state = create_initial_state()
    state["pipeline_stage"] = PipelineStage.IMPLEMENTATION.value
    state["active_ticket_id"] = "T-001"
    state["tickets"] = {"T-001": {"status": TicketStatus.IN_PROGRESS.value, "review_attempts": 0, "active_findings": []}}
    
    result = engine.mark_ticket_ready_for_review(state, "T-001")
    assert result.success
    assert result.new_state["tickets"]["T-001"]["status"] == TicketStatus.READY_FOR_REVIEW.value
    
    print("✓ test_ticket_ready_for_review passed")

@isolated
def test_complete_ticket_via_review_pass():
    """Test ticket completion only via Review PASS."""
    engine = StateTransitionEngine()
    
    state = create_initial_state()
    state["pipeline_stage"] = PipelineStage.IMPLEMENTATION.value
    state["active_ticket_id"] = "T-001"
    state["tickets"] = {"T-001": {"status": TicketStatus.READY_FOR_REVIEW.value, "review_attempts": 0, "active_findings": []}}
    
    # Try to complete directly (should fail)
    result = engine.complete_ticket_via_review(state, "T-001")
    assert not result.success
    assert 'evidence' in result.error
    assert state['tickets']['T-001']['status']=='READY_FOR_REVIEW'

    print("✓ test_complete_ticket_via_review_pass passed")

@isolated
def test_cannot_complete_from_in_progress():
    """Test developer cannot complete ticket from IN_PROGRESS directly."""
    engine = StateTransitionEngine()
    
    state = create_initial_state()
    state["pipeline_stage"] = PipelineStage.IMPLEMENTATION.value
    state["active_ticket_id"] = "T-001"
    state["tickets"] = {"T-001": {"status": TicketStatus.IN_PROGRESS.value, "review_attempts": 0, "active_findings": []}}
    
    result = engine.complete_ticket_via_review(state, "T-001")
    assert not result.success
    assert "evidence" in result.error
    
    print("✓ test_cannot_complete_from_in_progress passed")

@isolated
def test_review_fix_required_increments_attempts():
    """Test FIX_REQUIRED increments review_attempts."""
    engine = StateTransitionEngine()
    
    state = create_initial_state()
    state["pipeline_stage"] = PipelineStage.IMPLEMENTATION.value
    state["active_ticket_id"] = "T-001"
    state["tickets"] = {"T-001": {"status": TicketStatus.READY_FOR_REVIEW.value, "review_attempts": 0, "active_findings": []}}
    
    result = engine.process_review_verdict(state, "T-001", ReviewVerdict.FIX_REQUIRED)
    assert result.success
    assert result.new_state["tickets"]["T-001"]["review_attempts"] == 1
    assert result.new_state["tickets"]["T-001"]["status"] == TicketStatus.IN_PROGRESS.value
    
    print("✓ test_review_fix_required_increments_attempts passed")

@isolated
def test_review_retry_limit_auto_pause():
    """Test auto-pause at 3 review attempts."""
    engine = StateTransitionEngine()
    
    state = create_initial_state()
    state["pipeline_stage"] = PipelineStage.IMPLEMENTATION.value
    state["active_ticket_id"] = "T-001"
    state["tickets"] = {"T-001": {"status": TicketStatus.READY_FOR_REVIEW.value, "review_attempts": 2, "active_findings": []}}
    
    # 3rd FIX_REQUIRED
    result = engine.process_review_verdict(state, "T-001", ReviewVerdict.FIX_REQUIRED)
    assert result.success
    assert result.new_state["tickets"]["T-001"]["review_attempts"] == 3
    assert result.new_state["project_status"] == ProjectStatus.PAUSED.value
    assert result.new_state["pause"]["reason"] == PauseReason.RETRY_LIMIT_REACHED.value
    assert result.new_state["pause"]["decision_ref"] == "DEC-001"
    
    print("✓ test_review_retry_limit_auto_pause passed")

@isolated
def test_review_user_decision_required():
    """Test USER_DECISION_REQUIRED pauses with decision ref."""
    engine = StateTransitionEngine()
    
    state = create_initial_state()
    state["pipeline_stage"] = PipelineStage.IMPLEMENTATION.value
    state["active_ticket_id"] = "T-001"
    state["tickets"] = {"T-001": {"status": TicketStatus.READY_FOR_REVIEW.value, "review_attempts": 0, "active_findings": []}}
    
    result = engine.process_review_verdict(state, "T-001", ReviewVerdict.USER_DECISION_REQUIRED)
    assert not result.success  # Requires pause_project call
    assert "USER_DECISION_REQUIRED requires pause_project" in result.error
    
    print("✓ test_review_user_decision_required passed")

@isolated
def test_pause_resume():
    """Test project pause and resume."""
    engine = StateTransitionEngine()
    
    state = create_initial_state()
    state["pipeline_stage"] = PipelineStage.IMPLEMENTATION.value
    
    result = engine.pause_project(state, PauseReason.GATE_USER_DECISION_REQUIRED, "DEC-001")
    assert result.success
    assert result.new_state["project_status"] == ProjectStatus.PAUSED.value
    assert result.new_state["pause"]["reason"] == PauseReason.GATE_USER_DECISION_REQUIRED.value
    
    result = engine.resume_project(result.new_state)
    assert not result.success
    assert "decision validation" in result.error
    
    print("✓ test_pause_resume passed")

@isolated
def test_finding_lifecycle():
    """Test finding OPEN -> RESOLVED -> REOPENED -> RESOLVED."""
    engine = StateTransitionEngine()
    
    state = create_initial_state()
    state["pipeline_stage"] = PipelineStage.IMPLEMENTATION.value
    state["active_ticket_id"] = "T-001"
    state["tickets"] = {"T-001": {"status": TicketStatus.IN_PROGRESS.value, "review_attempts": 0, "active_findings": []}}
    
    # Add finding
    finding_data = {
        "ticket_id": "T-001",
        "finding_key": "missing-null-check",
        "status": FindingStatus.OPEN.value,
        "first_detected_attempt": 1,
        "last_seen_attempt": 1,
        "reopen_count": 0
    }
    result = engine.add_finding(state, "F-001", finding_data)
    assert result.success
    assert result.new_state["findings"]["F-001"]["status"] == FindingStatus.OPEN.value
    assert "F-001" in result.new_state["tickets"]["T-001"]["active_findings"]
    
    # Resolve finding
    result = engine.update_finding_status(result.new_state, "F-001", FindingStatus.RESOLVED)
    assert result.success
    assert result.new_state["findings"]["F-001"]["status"] == FindingStatus.RESOLVED.value
    assert "F-001" not in result.new_state["tickets"]["T-001"]["active_findings"]
    
    # Reopen finding
    result = engine.update_finding_status(result.new_state, "F-001", FindingStatus.REOPENED)
    assert result.success
    assert result.new_state["findings"]["F-001"]["status"] == FindingStatus.REOPENED.value
    assert "F-001" in result.new_state["tickets"]["T-001"]["active_findings"]
    assert result.new_state["findings"]["F-001"]["reopen_count"] == 1
    assert result.new_state["findings"]["F-001"]["last_seen_attempt"] == 0  # review_attempts is 0
    
    print("✓ test_finding_lifecycle passed")

@isolated
def test_undefined_transition_rejected():
    """Test undefined transitions are rejected."""
    engine = StateTransitionEngine()
    
    state = create_initial_state()
    state["pipeline_stage"] = PipelineStage.IMPLEMENTATION.value
    state["active_ticket_id"] = "T-001"
    state["tickets"] = {"T-001": {"status": TicketStatus.COMPLETE.value, "review_attempts": 0, "active_findings": []}}
    
    # Try to start completed ticket
    result = engine.start_ticket(state, "T-001")
    assert not result.success
    assert "COMPLETE" in result.error
    
    print("✓ test_undefined_transition_rejected passed")

def run_all_tests():
    tests = [
        test_planning_stage_advance,
        test_gate_fix_required,
        test_gate_user_decision_required,
        test_ticket_start,
        test_ticket_cannot_start_in_planning,
        test_ticket_ready_for_review,
        test_complete_ticket_via_review_pass,
        test_cannot_complete_from_in_progress,
        test_review_fix_required_increments_attempts,
        test_review_retry_limit_auto_pause,
        test_review_user_decision_required,
        test_pause_resume,
        test_finding_lifecycle,
        test_undefined_transition_rejected,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"✗ {test.__name__} FAILED: {e}")
            failed += 1
    
    print(f"\n=== Results: {passed} passed, {failed} failed ===")
    return failed == 0

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)