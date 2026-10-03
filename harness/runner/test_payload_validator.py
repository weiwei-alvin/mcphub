#!/usr/bin/env python3
"""
Test Suite for Payload Validator
"""

from test_support import isolated

import json
import subprocess
import tempfile
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = PROJECT_ROOT / "harness" / "runner" / "payload_validator.py"
STATE_FILE = PROJECT_ROOT / ".harness" / "state.json"

def run_validator(payload_type: str, payload: dict) -> tuple[bool, list[str]]:
    """Run validator and return (valid, errors)."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(payload, f)
        temp_file = f.name
    
    try:
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), payload_type, "--file", temp_file],
            capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        errors = []
        if result.returncode != 0:
            for line in result.stdout.split('\n'):
                if line.startswith('  - '):
                    errors.append(line[4:])
            for line in result.stderr.split('\n'):
                if line.startswith('  - '):
                    errors.append(line[4:])
        return result.returncode == 0, errors
    finally:
        Path(temp_file).unlink(missing_ok=True)

def write_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

@isolated
def test_gate_valid():
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
    payload = {
        "stage": "DISCOVERY",
        "verdict": "PASS",
        "criteria": [{"id": "PLAN-1", "status": "PASS"}]
    }
    valid, errors = run_validator("gate", payload)
    assert valid, f"Valid gate rejected: {errors}"
    print("✓ test_gate_valid passed")

@isolated
def test_gate_missing_field():
    payload = {
        "stage": "DISCOVERY",
        "verdict": "PASS"
    }
    valid, errors = run_validator("gate", payload)
    assert not valid, "Should reject missing criteria"
    assert any("criteria" in e and "required" in e for e in errors)
    print("✓ test_gate_missing_field passed")

@isolated
def test_gate_invalid_enum():
    payload = {
        "stage": "INVALID",
        "verdict": "PASS",
        "criteria": [{"id": "PLAN-1", "status": "PASS"}]
    }
    valid, errors = run_validator("gate", payload)
    assert not valid
    assert any("INVALID" in e for e in errors)
    print("✓ test_gate_invalid_enum passed")

@isolated
def test_gate_extra_field():
    payload = {
        "stage": "DISCOVERY",
        "verdict": "PASS",
        "criteria": [{"id": "PLAN-1", "status": "PASS"}],
        "forbidden": "extra"
    }
    valid, errors = run_validator("gate", payload)
    assert not valid
    assert any("Additional properties" in e for e in errors)
    print("✓ test_gate_extra_field passed")

@isolated
def test_gate_stage_mismatch():
    write_state({
        "schema_version": "1.1",
        "project_status": "IN_PROGRESS",
        "pipeline_stage": "SPEC",
        "stage_status": "IN_PROGRESS",
        "active_ticket_id": None,
        "pause": None,
        "tickets": {},
        "findings": {}
    })
    payload = {
        "stage": "DISCOVERY",
        "verdict": "PASS",
        "criteria": [{"id": "PLAN-1", "status": "PASS"}]
    }
    valid, errors = run_validator("gate", payload)
    assert not valid
    assert any("Stage mismatch" in e for e in errors)
    print("✓ test_gate_stage_mismatch passed")

@isolated
def test_review_valid():
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
    payload = {
        "ticket_id": "T-001",
        "verdict": "PASS",
        "criteria": [{"id": "TKT-1", "status": "PASS", "critical": True}],
        "findings": []
    }
    valid, errors = run_validator("review", payload)
    assert valid, f"Valid review rejected: {errors}"
    print("✓ test_review_valid passed")

@isolated
def test_review_wrong_ticket():
    payload = {
        "ticket_id": "T-999",
        "verdict": "PASS",
        "criteria": [{"id": "TKT-1", "status": "PASS", "critical": True}],
        "findings": []
    }
    valid, errors = run_validator("review", payload)
    assert not valid
    assert any("Ticket mismatch" in e for e in errors)
    print("✓ test_review_wrong_ticket passed")

@isolated
def test_review_non_active_ticket():
    write_state({
        "schema_version": "1.1",
        "project_status": "IN_PROGRESS",
        "pipeline_stage": "IMPLEMENTATION",
        "stage_status": "IN_PROGRESS",
        "active_ticket_id": "T-001",
        "pause": None,
        "tickets": {"T-001": {"status": "COMPLETE", "review_attempts": 0, "active_findings": []}},
        "findings": {}
    })
    payload = {
        "ticket_id": "T-001",
        "verdict": "PASS",
        "criteria": [{"id": "TKT-1", "status": "PASS", "critical": True}],
        "findings": []
    }
    valid, errors = run_validator("review", payload)
    assert not valid
    assert any("not ready for review" in e for e in errors)
    print("✓ test_review_non_active_ticket passed")

@isolated
def test_finding_valid():
    payload = {
        "finding_key": "missing-null-check",
        "criterion_ref": "TKT-1",
        "description": "Missing null check",
        "blocking": True,
        "evidence": "line 42"
    }
    valid, errors = run_validator("finding", payload)
    assert valid, f"Valid finding rejected: {errors}"
    print("✓ test_finding_valid passed")

@isolated
def test_finding_invalid_key():
    payload = {
        "finding_key": "Missing-Null-Check",
        "criterion_ref": "TKT-1",
        "description": "Missing null check",
        "blocking": True,
        "evidence": "line 42"
    }
    valid, errors = run_validator("finding", payload)
    assert not valid
    assert any("finding_key" in e and "match" in e for e in errors)
    print("✓ test_finding_invalid_key passed")

@isolated
def test_handoff_valid():
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
    payload = {
        "ticket_id": "T-001",
        "changes": [{"file": "src/auth.py", "summary": "Added null check"}],
        "verification": [{"step": "pytest", "expected": "pass", "actual": "pass", "status": "PASS"}],
        "dependencies": ["auth"]
    }
    valid, errors = run_validator("handoff", payload)
    assert valid, f"Valid handoff rejected: {errors}"
    print("✓ test_handoff_valid passed")

@isolated
def test_handoff_fail_verification():
    payload = {
        "ticket_id": "T-001",
        "changes": [{"file": "src/auth.py", "summary": "Added null check"}],
        "verification": [{"step": "pytest", "expected": "pass", "actual": "fail", "status": "FAIL"}],
        "dependencies": ["auth"]
    }
    valid, errors = run_validator("handoff", payload)
    assert not valid
    assert any("FAIL" in e and "not one of" in e for e in errors)
    print("✓ test_handoff_fail_verification passed")

@isolated
def test_change_impact_valid():
    payload = {
        "change_type": "BEHAVIORAL",
        "source": "SPEC.md",
        "affected_tickets": [{"ticket_id": "T-001", "action": "IMPACTED", "reason": "flow changed"}]
    }
    valid, errors = run_validator("change-impact", payload)
    assert valid, f"Valid change-impact rejected: {errors}"
    print("✓ test_change_impact_valid passed")

@isolated
def test_change_impact_nonexistent_ticket():
    payload = {
        "change_type": "BEHAVIORAL",
        "source": "SPEC.md",
        "affected_tickets": [{"ticket_id": "T-999", "action": "IMPACTED", "reason": "flow changed"}]
    }
    valid, errors = run_validator("change-impact", payload)
    assert not valid
    assert any("not found in state" in e for e in errors)
    print("✓ test_change_impact_nonexistent_ticket passed")

@isolated
def test_non_behavioral_requires_none():
    payload = {
        "change_type": "NON_BEHAVIORAL",
        "source": "SPEC.md",
        "affected_tickets": [{"ticket_id": "T-001", "action": "IMPACTED", "reason": "wording"}]
    }
    valid, errors = run_validator("change-impact", payload)
    assert not valid
    # Schema should enforce NONE for NON_BEHAVIORAL
    print("✓ test_non_behavioral_requires_none passed")

def run_all_tests():
    tests = [
        test_gate_valid,
        test_gate_missing_field,
        test_gate_invalid_enum,
        test_gate_extra_field,
        test_gate_stage_mismatch,
        test_review_valid,
        test_review_wrong_ticket,
        test_review_non_active_ticket,
        test_finding_valid,
        test_finding_invalid_key,
        test_handoff_valid,
        test_handoff_fail_verification,
        test_change_impact_valid,
        test_change_impact_nonexistent_ticket,
        test_non_behavioral_requires_none,
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