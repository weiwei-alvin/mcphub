#!/usr/bin/env python3
"""
Test Suite for Harness Runner
"""

from test_support import isolated, review_files

import subprocess
import json
import tempfile
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER = PROJECT_ROOT / "harness" / "runner" / "runner.py"
STATE_FILE = PROJECT_ROOT / ".harness" / "state.json"

def run_cmd(*args, input_data=None):
    """Run runner command and return (success, stdout, stderr)."""
    cmd = [sys.executable, str(RUNNER)] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT, input=input_data)
    return result.returncode == 0, result.stdout, result.stderr

def write_state(state):
    """Write state to file."""
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

@isolated
def test_valid_state_read():
    """Test reading valid state."""
    write_state({
        "schema_version": "1.1",
        "project_status": "IN_PROGRESS",
        "pipeline_stage": "DISCOVERY",
        "stage_status": "IN_PROGRESS",
        "active_ticket_id": None,
        "pause": None,
        "tickets": {},
        "findings": {}
    })
    success, out, err = run_cmd("read")
    assert success, f"Failed to read valid state: {err}"
    state = json.loads(out)
    assert state["project_status"] == "IN_PROGRESS"
    print("✓ test_valid_state_read passed")

@isolated
def test_invalid_state_rejected():
    """Test that invalid state is rejected."""
    write_state({
        "schema_version": "1.1",
        "project_status": "INVALID",
        "pipeline_stage": "DISCOVERY",
        "stage_status": "IN_PROGRESS",
        "active_ticket_id": None,
        "pause": None,
        "tickets": {},
        "findings": {}
    })
    success, out, err = run_cmd("validate")
    assert not success, "Should reject invalid state"
    assert "INVALID" in err
    print("✓ test_invalid_state_rejected passed")

@isolated
def test_atomic_write():
    """Test that writes are atomic (simulate crash during write)."""
    from runner import HarnessRunner
    from unittest.mock import patch
    runner=HarnessRunner(PROJECT_ROOT)
    state=runner.read_state(); before=STATE_FILE.read_bytes()
    state['tickets']['T-001']['review_attempts']=1
    with patch('storage.os.replace',side_effect=OSError('simulated disk failure')):
        assert not runner.write_state_atomic(state)
    assert STATE_FILE.read_bytes()==before


@isolated
def test_recover_from_state():
    """Test recovery from state after restart."""
    write_state({
        "schema_version": "1.1",
        "project_status": "IN_PROGRESS",
        "pipeline_stage": "IMPLEMENTATION",
        "stage_status": "IN_PROGRESS",
        "active_ticket_id": "T-001",
        "pause": None,
        "tickets": {"T-001": {"status": "IN_PROGRESS", "review_attempts": 0, "active_findings": []}},
        "findings": {}
    })
    success, out, err = run_cmd("recover")
    assert success, f"Recovery failed: {err}"
    recovery = json.loads(out)
    assert recovery["active_ticket_id"] == "T-001"
    assert recovery["pipeline_stage"] == "IMPLEMENTATION"
    print("✓ test_recover_from_state passed")

@isolated
def test_ticket_lifecycle():
    """Test ticket start -> ready_for_review -> complete lifecycle."""
    write_state({
        "schema_version": "1.1",
        "project_status": "IN_PROGRESS",
        "pipeline_stage": "IMPLEMENTATION",
        "stage_status": "IN_PROGRESS",
        "active_ticket_id": "T-001",
        "pause": None,
        "tickets": {"T-001": {"status": "IN_PROGRESS", "review_attempts": 0, "active_findings": []}},
        "findings": {}
    })
    # Must mark ready for review first
    success, out, err = run_cmd("mark-ticket-ready-for-review", "--ticket", "T-001")
    assert success, f"Mark ready for review failed: {err}"
    
    r,h = review_files(PROJECT_ROOT)
    success, out, err = run_cmd("review-verdict", "--ticket", "T-001", "--verdict", "PASS", "--review", str(r), "--handoff", str(h), "--trust-commands")
    assert success, f"Review verdict PASS failed: {err}"
    
    success, out, err = run_cmd("read")
    assert success
    state = json.loads(out)
    assert state["tickets"]["T-001"]["status"] == "COMPLETE"
    assert state["active_ticket_id"] is None
    assert state["project_status"] == "COMPLETE"
    print("✓ test_ticket_lifecycle passed")

@isolated
def test_review_attempts_increment():
    """Test review attempts increment and auto-pause at 3."""
    write_state({
        "schema_version": "1.1",
        "project_status": "IN_PROGRESS",
        "pipeline_stage": "IMPLEMENTATION",
        "stage_status": "IN_PROGRESS",
        "active_ticket_id": "T-002",
        "pause": None,
        "tickets": {
            "T-001": {"status": "COMPLETE", "review_attempts": 0, "active_findings": []},
            "T-002": {"status": "READY_FOR_REVIEW", "review_attempts": 2, "active_findings": []}
        },
        "findings": {}
    })
    r,h = review_files(PROJECT_ROOT, "FIX_REQUIRED")
    success, out, err = run_cmd("review-verdict", "--ticket", "T-002", "--verdict", "FIX_REQUIRED", "--review", str(r))
    assert success, f"Increment failed: {err}"
    
    success, out, err = run_cmd("read")
    state = json.loads(out)
    assert state["tickets"]["T-002"]["review_attempts"] == 3
    assert state["project_status"] == "PAUSED"
    assert state["pause"]["reason"] == "RETRY_LIMIT_REACHED"
    print("✓ test_review_attempts_increment passed")

@isolated
def test_pause_resume():
    """Test pause and resume."""
    write_state({
        "schema_version": "1.1",
        "project_status": "IN_PROGRESS",
        "pipeline_stage": "IMPLEMENTATION",
        "stage_status": "IN_PROGRESS",
        "active_ticket_id": "T-001",
        "pause": None,
        "tickets": {"T-001": {"status": "IN_PROGRESS", "review_attempts": 0, "active_findings": []}},
        "findings": {}
    })
    success, out, err = run_cmd("pause", "--reason", "GATE_USER_DECISION_REQUIRED", "--decision-ref", "DEC-001")
    assert success, f"Pause failed: {err}"
    
    success, out, err = run_cmd("read")
    state = json.loads(out)
    assert state["project_status"] == "PAUSED"
    assert state["pause"]["reason"] == "GATE_USER_DECISION_REQUIRED"
    assert state["pause"]["decision_ref"] == "DEC-001"
    
    success, out, err = run_cmd("resume")
    assert not success, "Blank decision must be refused"
    success, out, err = run_cmd("decide", "--option", "FIX_REQUIRED", "--rationale", "Return to fixes", "--source", "test operator")
    assert success, err
    success, out, err = run_cmd("resume")
    assert success, f"Resume failed: {err}"
    
    success, out, err = run_cmd("read")
    state = json.loads(out)
    assert state["project_status"] == "IN_PROGRESS"
    assert state["pause"] is None
    print("✓ test_pause_resume passed")

@isolated
def test_findings_open_resolved():
    """Test finding OPEN -> RESOLVED lifecycle."""
    write_state({
        "schema_version": "1.1",
        "project_status": "IN_PROGRESS",
        "pipeline_stage": "IMPLEMENTATION",
        "stage_status": "IN_PROGRESS",
        "active_ticket_id": "T-001",
        "pause": None,
        "tickets": {"T-001": {"status": "IN_PROGRESS", "review_attempts": 0, "active_findings": []}},
        "findings": {}
    })
    finding_data = json.dumps({
        "ticket_id": "T-001",
        "finding_key": "test-issue",
        "status": "OPEN",
        "first_detected_attempt": 1,
        "last_seen_attempt": 1,
        "reopen_count": 0
    })
    success, out, err = run_cmd("add-finding", "--finding-id", "F-001", "--finding-data", finding_data)
    assert success, f"Add finding failed: {err}"
    
    success, out, err = run_cmd("read")
    state = json.loads(out)
    assert "F-001" in state["findings"]
    assert state["findings"]["F-001"]["status"] == "OPEN"
    assert "F-001" in state["tickets"]["T-001"]["active_findings"]
    
    success, out, err = run_cmd("resolve-finding", "--finding-id", "F-001")
    assert success, f"Resolve finding failed: {err}"
    
    success, out, err = run_cmd("read")
    state = json.loads(out)
    assert state["findings"]["F-001"]["status"] == "RESOLVED"
    assert "F-001" not in state["tickets"]["T-001"]["active_findings"]
    print("✓ test_findings_open_resolved passed")

@isolated
def test_runner_only_modifies_state():
    """Verify only runner modifies state (no direct agent writes)."""
    from runner import HarnessRunner
    first=HarnessRunner(PROJECT_ROOT); second=HarnessRunner(PROJECT_ROOT)
    a=first.read_state(); b=second.read_state()
    a['tickets']['T-001']['review_attempts']=1
    assert first.write_state_atomic(a)
    assert not second.write_state_atomic(b)
    assert json.loads(STATE_FILE.read_text())['tickets']['T-001']['review_attempts']==1


def run_all_tests():
    """Run all tests."""
    tests = [
        test_valid_state_read,
        test_invalid_state_rejected,
        test_atomic_write,
        test_recover_from_state,
        test_ticket_lifecycle,
        test_review_attempts_increment,
        test_pause_resume,
        test_findings_open_resolved,
        test_runner_only_modifies_state,
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