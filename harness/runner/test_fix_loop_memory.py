#!/usr/bin/env python3
"""
Test Suite for Fix Loop Memory
"""

from test_support import isolated

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from state_transition import StateTransitionEngine, TicketStatus, FindingStatus, ReviewVerdict, ProjectStatus, PipelineStage, StageStatus, PauseReason
from runner import HarnessRunner

@isolated
def test_fix_loop_memory_created():
    """Test that fix loop memory is created on FIX_REQUIRED."""
    runner = HarnessRunner()
    state = {
        "schema_version": "1.1",
        "project_status": ProjectStatus.IN_PROGRESS.value,
        "pipeline_stage": PipelineStage.IMPLEMENTATION.value,
        "stage_status": StageStatus.IN_PROGRESS.value,
        "active_ticket_id": "T-001",
        "pause": None,
        "tickets": {
            "T-001": {"status": TicketStatus.READY_FOR_REVIEW.value, "review_attempts": 0, "active_findings": ["F-001"]}
        },
        "findings": {
            "F-001": {
                "ticket_id": "T-001",
                "finding_key": "missing-null-check",
                "status": FindingStatus.OPEN.value,
                "first_detected_attempt": 1,
                "last_seen_attempt": 1,
                "reopen_count": 0
            }
        }
    }
    
    result = runner.transition_engine.process_review_verdict(state, "T-001", ReviewVerdict.FIX_REQUIRED)
    assert result.success
    assert "fix_loop_memory" in result.new_state["tickets"]["T-001"]
    memory = result.new_state["tickets"]["T-001"]["fix_loop_memory"]
    assert memory["attempt_number"] == 1
    assert len(memory["active_findings"]) == 1
    assert memory["active_finding_keys"] == ["missing-null-check"]
    assert memory["previous_fix_summary"] == ""
    print("✓ test_fix_loop_memory_created passed")

@isolated
def test_fix_loop_memory_continuity():
    """Test fix loop memory continuity across attempts."""
    runner = HarnessRunner()
    state = {
        "schema_version": "1.1",
        "project_status": ProjectStatus.IN_PROGRESS.value,
        "pipeline_stage": PipelineStage.IMPLEMENTATION.value,
        "stage_status": StageStatus.IN_PROGRESS.value,
        "active_ticket_id": "T-001",
        "pause": None,
        "tickets": {
            "T-001": {
                "status": TicketStatus.READY_FOR_REVIEW.value, 
                "review_attempts": 1, 
                "active_findings": ["F-001"],
                "fix_loop_memory": {
                    "attempt_number": 1,
                    "active_finding_keys": ["missing-null-check"],
                    "previous_fix_summary": "Fixed null check in login",
                    "previous_failure_reasons": [{"finding_key": "missing-null-check"}]
                }
            }
        },
        "findings": {
            "F-001": {
                "ticket_id": "T-001",
                "finding_key": "missing-null-check",
                "status": FindingStatus.OPEN.value,
                "first_detected_attempt": 1,
                "last_seen_attempt": 1,
                "reopen_count": 0
            }
        }
    }
    
    result = runner.transition_engine.process_review_verdict(state, "T-001", ReviewVerdict.FIX_REQUIRED)
    assert result.success
    memory = result.new_state["tickets"]["T-001"]["fix_loop_memory"]
    assert memory["attempt_number"] == 2
    assert memory["previous_fix_summary"] == "Fixed null check in login"
    assert len(memory["previous_failure_reasons"]) == 1
    assert memory["previous_failure_reasons"][0]["finding_key"] == "missing-null-check"
    print("✓ test_fix_loop_memory_continuity passed")

@isolated
def test_fix_loop_memory_not_full_history():
    """Test that fix loop memory doesn't load full review history."""
    runner = HarnessRunner()
    state = {
        "schema_version": "1.1",
        "project_status": ProjectStatus.IN_PROGRESS.value,
        "pipeline_stage": PipelineStage.IMPLEMENTATION.value,
        "stage_status": StageStatus.IN_PROGRESS.value,
        "active_ticket_id": "T-001",
        "pause": None,
        "tickets": {
            "T-001": {"status": TicketStatus.READY_FOR_REVIEW.value, "review_attempts": 0, "active_findings": ["F-001"]}
        },
        "findings": {
            "F-001": {
                "ticket_id": "T-001",
                "finding_key": "missing-null-check",
                "status": FindingStatus.OPEN.value,
                "first_detected_attempt": 1,
                "last_seen_attempt": 1,
                "reopen_count": 0
            }
        }
    }
    
    result = runner.transition_engine.process_review_verdict(state, "T-001", ReviewVerdict.FIX_REQUIRED)
    memory = result.new_state["tickets"]["T-001"]["fix_loop_memory"]
    
    # Should not contain full review history
    assert "review_history" not in memory
    assert "full_criteria" not in memory
    # Should only contain relevant context
    assert "active_findings" in memory
    assert "failure_reasons" in memory
    assert "previous_fix_summary" in memory
    assert "previous_failure_reasons" in memory
    print("✓ test_fix_loop_memory_not_full_history passed")

@isolated
def test_finding_key_continuity():
    """Test that finding_key is used for continuity across attempts."""
    runner = HarnessRunner()
    state = {
        "schema_version": "1.1",
        "project_status": ProjectStatus.IN_PROGRESS.value,
        "pipeline_stage": PipelineStage.IMPLEMENTATION.value,
        "stage_status": StageStatus.IN_PROGRESS.value,
        "active_ticket_id": "T-001",
        "pause": None,
        "tickets": {
            "T-001": {"status": TicketStatus.READY_FOR_REVIEW.value, "review_attempts": 1, "active_findings": ["F-001", "F-002"]}
        },
        "findings": {
            "F-001": {
                "ticket_id": "T-001",
                "finding_key": "missing-null-check",
                "status": FindingStatus.OPEN.value,
                "first_detected_attempt": 1,
                "last_seen_attempt": 1,
                "reopen_count": 0
            },
            "F-002": {
                "ticket_id": "T-001",
                "finding_key": "weak-password",
                "status": FindingStatus.REOPENED.value,
                "first_detected_attempt": 1,
                "last_seen_attempt": 2,
                "reopen_count": 1
            }
        }
    }
    
    result = runner.transition_engine.process_review_verdict(state, "T-001", ReviewVerdict.FIX_REQUIRED)
    memory = result.new_state["tickets"]["T-001"]["fix_loop_memory"]
    
    # Both findings should be present with their finding_keys
    finding_keys = memory["active_finding_keys"]
    assert "missing-null-check" in finding_keys
    assert "weak-password" in finding_keys
    assert len(finding_keys) == 2
    
    # Reopened finding should have reopen_count > 0
    reopened_finding = next(af for af in memory["active_findings"] if af["finding_key"] == "weak-password")
    assert reopened_finding["reopen_count"] == 1
    
    print("✓ test_finding_key_continuity passed")

@isolated
def test_runner_commands():
    """Test runner fix-loop-memory commands."""
    from runner import HarnessRunner
    
    import subprocess
    command=[sys.executable,str(Path.cwd()/'harness/runner/runner.py')]
    p=subprocess.run(command+['update-fix-memory','--ticket','T-001','--finding-data','Fixed arithmetic'],capture_output=True,text=True)
    assert p.returncode==0, p.stderr
    p=subprocess.run(command+['fix-loop-memory','--ticket','T-001'],capture_output=True,text=True)
    assert p.returncode==0, p.stderr
    assert json.loads(p.stdout)['fix_summary']=='Fixed arithmetic'


def run_all_tests():
    tests = [
        test_fix_loop_memory_created,
        test_fix_loop_memory_continuity,
        test_fix_loop_memory_not_full_history,
        test_finding_key_continuity,
        test_runner_commands,
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