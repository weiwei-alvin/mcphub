#!/usr/bin/env python3
"""
Test Suite for Dependency Scheduler
"""

from test_support import isolated

import json
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dependency_scheduler import DependencyScheduler, TicketInfo, TicketStatus

def setup_test_tickets(base_dir: Path):
    """Create test ticket files."""
    tickets_dir = base_dir / ".harness" / "tickets"
    tickets_dir.mkdir(parents=True, exist_ok=True)
    
    # T-001: No dependencies
    (tickets_dir / "T-001.md").write_text("""---
id: T-001
depends_on: []
---

# T-001: Setup project infrastructure

**What to build:** Initialize project structure

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent
""", encoding='utf-8')
    
    # T-002: Depends on T-001
    (tickets_dir / "T-002.md").write_text("""---
id: T-002
depends_on: [T-001]
---

# T-002: Implement authentication module

**What to build:** User authentication

**Blocked by:** T-001

**Status:** ready-for-agent
""", encoding='utf-8')
    
    # T-003: Depends on T-002
    (tickets_dir / "T-003.md").write_text("""---
id: T-003
depends_on: [T-002]
---

# T-003: Implement user profile API

**What to build:** CRUD API for user profiles

**Blocked by:** T-002

**Status:** ready-for-agent
""", encoding='utf-8')
    
    # T-004: Depends on T-001 and T-002
    (tickets_dir / "T-004.md").write_text("""---
id: T-004
depends_on: [T-001, T-002]
---

# T-004: Implement admin dashboard

**What to build:** Admin dashboard

**Blocked by:** T-001, T-002

**Status:** ready-for-agent
""", encoding='utf-8')

@isolated
def test_valid_dependencies():
    """Test valid dependency chain."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        setup_test_tickets(base_dir)
        
        scheduler = DependencyScheduler(base_dir)
        ticket_files = scheduler.load_ticket_files()
        
        errors = scheduler.validate_dependencies(ticket_files)
        assert len(errors) == 0, f"Unexpected errors: {errors}"
        print("✓ test_valid_dependencies passed")

@isolated
def test_non_existent_dependency():
    """Test rejection of non-existent dependencies."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        setup_test_tickets(base_dir)
        
        # Add ticket with non-existent dependency
        tickets_dir = base_dir / ".harness" / "tickets"
        (tickets_dir / "T-005.md").write_text("""---
id: T-005
depends_on: [T-999]
---

# T-005: Bad dependency
""", encoding='utf-8')
        
        scheduler = DependencyScheduler(base_dir)
        ticket_files = scheduler.load_ticket_files()
        
        errors = scheduler.validate_dependencies(ticket_files)
        assert len(errors) > 0
        assert any("non-existent" in e for e in errors)
        print("✓ test_non_existent_dependency passed")

@isolated
def test_circular_dependency():
    """Test rejection of circular dependencies."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        tickets_dir = base_dir / ".harness" / "tickets"
        tickets_dir.mkdir(parents=True, exist_ok=True)
        
        # Create circular dependency T-001 -> T-002 -> T-001
        (tickets_dir / "T-001.md").write_text("""---
id: T-001
depends_on: [T-002]
---
# T-001
""", encoding='utf-8')
        
        (tickets_dir / "T-002.md").write_text("""---
id: T-002
depends_on: [T-001]
---
# T-002
""", encoding='utf-8')
        
        scheduler = DependencyScheduler(base_dir)
        ticket_files = scheduler.load_ticket_files()
        
        errors = scheduler.validate_dependencies(ticket_files)
        assert len(errors) > 0
        assert any("Circular" in e for e in errors)
        print("✓ test_circular_dependency passed")

@isolated
def test_executable_tickets():
    """Test getting executable tickets."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        setup_test_tickets(base_dir)
        
        scheduler = DependencyScheduler(base_dir)
        ticket_files = scheduler.load_ticket_files()
        
        # State: T-001 COMPLETE, others TODO
        state = {
            "tickets": {
                "T-001": {"status": TicketStatus.COMPLETE.value, "review_attempts": 0, "active_findings": []},
                "T-002": {"status": TicketStatus.TODO.value, "review_attempts": 0, "active_findings": []},
                "T-003": {"status": TicketStatus.TODO.value, "review_attempts": 0, "active_findings": []},
                "T-004": {"status": TicketStatus.TODO.value, "review_attempts": 0, "active_findings": []},
            }
        }
        
        executable = scheduler.get_executable_tickets(state, ticket_files)
        # Only T-002 should be executable (depends on T-001 which is COMPLETE)
        assert executable == ["T-002"], f"Expected ['T-002'], got {executable}"
        
        # Test next ticket
        next_ticket = scheduler.get_next_ticket(state, ticket_files)
        assert next_ticket == "T-002"
        print("✓ test_executable_tickets passed")

@isolated
def test_executable_multiple_ready():
    """Test multiple tickets ready - picks by approval order."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        setup_test_tickets(base_dir)
        
        scheduler = DependencyScheduler(base_dir)
        ticket_files = scheduler.load_ticket_files()
        
        # State: T-001 COMPLETE, T-002 COMPLETE, others TODO
        state = {
            "tickets": {
                "T-001": {"status": TicketStatus.COMPLETE.value, "review_attempts": 0, "active_findings": []},
                "T-002": {"status": TicketStatus.COMPLETE.value, "review_attempts": 0, "active_findings": []},
                "T-003": {"status": TicketStatus.TODO.value, "review_attempts": 0, "active_findings": []},
                "T-004": {"status": TicketStatus.TODO.value, "review_attempts": 0, "active_findings": []},
            }
        }
        
        executable = scheduler.get_executable_tickets(state, ticket_files)
        # Both T-003 and T-004 should be ready
        # T-003 has approval_order 2, T-004 has approval_order 3
        assert executable == ["T-003", "T-004"], f"Expected ['T-003', 'T-004'], got {executable}"
        
        next_ticket = scheduler.get_next_ticket(state, ticket_files)
        assert next_ticket == "T-003"  # First by approval order
        print("✓ test_executable_multiple_ready passed")

@isolated
def test_blocked_tickets():
    """Test getting blocked tickets with reasons."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        setup_test_tickets(base_dir)
        
        scheduler = DependencyScheduler(base_dir)
        ticket_files = scheduler.load_ticket_files()
        
        # State: only T-001 COMPLETE
        state = {
            "tickets": {
                "T-001": {"status": TicketStatus.COMPLETE.value, "review_attempts": 0, "active_findings": []},
                "T-002": {"status": TicketStatus.TODO.value, "review_attempts": 0, "active_findings": []},
                "T-003": {"status": TicketStatus.TODO.value, "review_attempts": 0, "active_findings": []},
                "T-004": {"status": TicketStatus.TODO.value, "review_attempts": 0, "active_findings": []},
            }
        }
        
        blocked = scheduler.get_blocked_tickets(state, ticket_files)
        
        # T-002 should NOT be blocked (dependency COMPLETE)
        assert "T-002" not in blocked
        
        # T-003 blocked by T-002 (TODO)
        assert "T-003" in blocked
        assert any("T-002" in b and "TODO" in b for b in blocked["T-003"])
        
        # T-004 blocked by T-002 (TODO) - T-001 is COMPLETE
        assert "T-004" in blocked
        assert any("T-002" in b and "TODO" in b for b in blocked["T-004"])
        
        print("✓ test_blocked_tickets passed")

@isolated
def test_can_start_ticket():
    """Test can_start_ticket check."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        setup_test_tickets(base_dir)
        
        scheduler = DependencyScheduler(base_dir)
        ticket_files = scheduler.load_ticket_files()
        
        state = {
            "tickets": {
                "T-001": {"status": TicketStatus.COMPLETE.value, "review_attempts": 0, "active_findings": []},
                "T-002": {"status": TicketStatus.TODO.value, "review_attempts": 0, "active_findings": []},
                "T-003": {"status": TicketStatus.TODO.value, "review_attempts": 0, "active_findings": []},
            }
        }
        
        # T-002 should be startable
        can_start, reason = scheduler.can_start_ticket(state, "T-002", ticket_files)
        assert can_start, f"T-002 should start: {reason}"
        
        # T-003 should not be startable (T-002 is TODO)
        can_start, reason = scheduler.can_start_ticket(state, "T-003", ticket_files)
        assert not can_start
        assert "T-002" in reason and "TODO" in reason
        
        # Non-existent ticket
        can_start, reason = scheduler.can_start_ticket(state, "T-999", ticket_files)
        assert not can_start
        assert "not found" in reason
        
        print("✓ test_can_start_ticket passed")

@isolated
def test_approval_order():
    """Test that approval order is based on file naming."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        tickets_dir = base_dir / ".harness" / "tickets"
        tickets_dir.mkdir(parents=True, exist_ok=True)
        
        # Create tickets in non-alphabetical order to test approval order
        (tickets_dir / "T-003.md").write_text("""---
id: T-003
depends_on: []
---
# T-003
""", encoding='utf-8')
        
        (tickets_dir / "T-001.md").write_text("""---
id: T-001
depends_on: []
---
# T-001
""", encoding='utf-8')
        
        (tickets_dir / "T-002.md").write_text("""---
id: T-002
depends_on: []
---
# T-002
""", encoding='utf-8')
        
        scheduler = DependencyScheduler(base_dir)
        ticket_files = scheduler.load_ticket_files()
        
        # Should be sorted by filename: T-001, T-002, T-003
        assert ticket_files["T-001"].approval_order == 0
        assert ticket_files["T-002"].approval_order == 1
        assert ticket_files["T-003"].approval_order == 2
        
        print("✓ test_approval_order passed")

def run_all_tests():
    tests = [
        test_valid_dependencies,
        test_non_existent_dependency,
        test_circular_dependency,
        test_executable_tickets,
        test_executable_multiple_ready,
        test_blocked_tickets,
        test_can_start_ticket,
        test_approval_order,
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