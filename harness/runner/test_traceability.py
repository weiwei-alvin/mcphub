#!/usr/bin/env python3
"""
Test Suite for Traceability ID System
"""

from test_support import isolated

import json
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from traceability import TraceabilityManager, EntityType, TraceabilityEntity, _entity_to_dict

def setup_test_data(base_dir: Path):
    """Create test traceability data."""
    manager = TraceabilityManager(base_dir)
    
    # Create scopes
    manager.create_scope("User Authentication", "Core authentication system")
    manager.create_scope("Admin Management", "Administrative features")
    
    # Create user stories
    manager.create_user_story("User Login", "Users can log in", ["S-001"])
    manager.create_user_story("Password Reset", "Reset forgotten passwords", ["S-001"])
    manager.create_user_story("Admin Dashboard", "Admin user management", ["S-002"])
    
    # Create tickets
    manager.create_ticket("Login endpoint", "POST /api/auth/login", story_ids=["US-001"])
    manager.create_ticket("Rate limiting", "Prevent brute force", story_ids=["US-001"])
    manager.create_ticket("Password reset flow", "Email token flow", story_ids=["US-002"])
    manager.create_ticket("CI/CD setup", "GitHub Actions workflow", scope_ids=["S-001"])
    
    return manager

@isolated
def test_scope_creation():
    """Test Scope creation with unique IDs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        manager = TraceabilityManager(base_dir)
        
        success, eid, err = manager.create_scope("Test Scope", "Description")
        assert success
        assert eid == "S-001"
        assert eid in manager._entities
        
        # Duplicate should fail
        success, eid, err = manager.create_scope("Another", "Desc", scope_id="S-001")
        assert not success
        assert "Duplicate" in err
        
        print("✓ test_scope_creation passed")

@isolated
def test_user_story_creation():
    """Test User Story creation with Scope traceability."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        manager = TraceabilityManager(base_dir)
        manager.create_scope("Auth", "Authentication")
        
        success, eid, err = manager.create_user_story("Login", "User login", ["S-001"])
        assert success
        assert eid == "US-001"
        
        # Verify traceability
        entity = manager.get_entity("US-001")
        assert entity.parent_ids == ["S-001"]
        
        # Verify reverse link
        scope = manager.get_entity("S-001")
        assert "US-001" in scope.child_ids
        
        # Non-existent scope should fail
        success, eid, err = manager.create_user_story("Test", "Desc", ["S-999"])
        assert not success
        assert "does not exist" in err
        
        print("✓ test_user_story_creation passed")

@isolated
def test_ticket_creation():
    """Test Ticket creation with User Story and Scope traceability."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        manager = TraceabilityManager(base_dir)
        manager.create_scope("Auth", "Authentication")
        manager.create_user_story("Login", "User login", ["S-001"])
        
        # Ticket tracing to User Story
        success, eid, err = manager.create_ticket("Login endpoint", "API endpoint", story_ids=["US-001"])
        assert success
        assert eid == "T-001"
        
        entity = manager.get_entity("T-001")
        assert entity.parent_ids == ["US-001"]
        
        # Verify reverse link
        story = manager.get_entity("US-001")
        assert "T-001" in story.child_ids
        
        # Ticket tracing to Scope (technical ticket)
        success, eid, err = manager.create_ticket("CI/CD", "Pipeline", scope_ids=["S-001"])
        assert success
        assert eid == "T-002"
        assert manager.get_entity("T-002").parent_ids == ["S-001"]
        
        # Ticket with no parent should fail
        success, eid, err = manager.create_ticket("Orphan", "No parent")
        assert not success
        assert "must trace to at least one" in err
        
        # Non-existent parent should fail
        success, eid, err = manager.create_ticket("Test", "Desc", story_ids=["US-999"])
        assert not success
        assert "does not exist" in err
        
        print("✓ test_ticket_creation passed")

@isolated
def test_traceability_chain():
    """Test full traceability chain (Scope -> Story -> Ticket)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        manager = setup_test_data(base_dir)
        
        # Trace from ticket to scope
        trace = manager.get_full_trace("T-001")
        assert trace["entity"].id == "T-001"
        ancestor_ids = [a.id for a in trace["ancestors"]]
        assert "US-001" in ancestor_ids
        assert "S-001" in ancestor_ids
        
        # Trace from scope to tickets
        trace = manager.get_full_trace("S-001")
        descendant_ids = [d.id for d in trace["descendants"]]
        assert "US-001" in descendant_ids
        assert "US-002" in descendant_ids
        assert "T-001" in descendant_ids
        assert "T-004" in descendant_ids  # Technical ticket
        
        print("✓ test_traceability_chain passed")

@isolated
def test_duplicate_id_rejection():
    """Test that duplicate IDs are rejected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        manager = TraceabilityManager(base_dir)
        
        manager.create_scope("Scope 1", "Desc")
        
        # Try to create another with same ID
        success, eid, err = manager.create_scope("Scope 2", "Desc", scope_id="S-001")
        assert not success
        assert "Duplicate" in err
        
        manager.create_user_story("Story", "Desc", ["S-001"])
        success, eid, err = manager.create_user_story("Story 2", "Desc", ["S-001"], story_id="US-001")
        assert not success
        assert "Duplicate" in err
        
        print("✓ test_duplicate_id_rejection passed")

@isolated
def test_dangling_reference_detection():
    """Test detection of dangling references."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        manager = TraceabilityManager(base_dir)
        
        # Manually corrupt data to create dangling reference
        manager.create_scope("Auth", "Authentication")
        manager.create_user_story("Login", "User login", ["S-001"])
        
        # Corrupt: add non-existent parent
        manager._entities["US-001"].parent_ids.append("S-999")
        manager._save()
        
        errors = manager.validate_all()
        assert any("non-existent parent" in e for e in errors)
        
        print("✓ test_dangling_reference_detection passed")

@isolated
def test_cycle_detection():
    """Test circular dependency detection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        manager = TraceabilityManager(base_dir)
        
        manager.create_scope("Auth", "Authentication")
        manager.create_user_story("Login", "User login", ["S-001"])
        
        # Create cycle: S-001 -> US-001 -> S-001
        manager._entities["S-001"].parent_ids.append("US-001")
        manager._entities["US-001"].child_ids.append("S-001")
        manager._save()
        
        errors = manager.validate_all()
        assert any("Cycle detected" in e for e in errors)
        
        print("✓ test_cycle_detection passed")

@isolated
def test_orphan_user_story():
    """Test detection of User Story without Scope parent."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        manager = TraceabilityManager(base_dir)
        
        # Manually create orphan story
        manager._entities["US-001"] = TraceabilityEntity(
            id="US-001", type=EntityType.USER_STORY, title="Orphan", parent_ids=[]
        )
        manager._save()
        
        errors = manager.validate_all()
        assert any("has no Scope parent" in e for e in errors)
        
        print("✓ test_orphan_user_story passed")

@isolated
def test_orphan_ticket():
    """Test detection of Ticket without parent."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        manager = TraceabilityManager(base_dir)
        
        # Manually create orphan ticket
        manager._entities["T-001"] = TraceabilityEntity(
            id="T-001", type=EntityType.TICKET, title="Orphan", parent_ids=[]
        )
        manager._save()
        
        errors = manager.validate_all()
        assert any("has no User Story or Scope parent" in e for e in errors)
        
        print("✓ test_orphan_ticket passed")

@isolated
def test_report_generation():
    """Test TRACEABILITY.md report generation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        manager = setup_test_data(base_dir)
        
        report = manager.generate_markdown()
        assert "# Traceability Matrix" in report
        assert "## Scopes" in report
        assert "## User Stories" in report
        assert "## Tickets" in report
        assert "S-001" in report
        assert "US-001" in report
        assert "T-001" in report
        assert "Traces to" in report
        
        print("✓ test_report_generation passed")

@isolated
def test_id_format_validation():
    """Test ID format validation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        manager = TraceabilityManager(base_dir)
        
        # Valid formats
        assert manager._validate_id_format("S-001", EntityType.SCOPE)[0]
        assert manager._validate_id_format("US-001", EntityType.USER_STORY)[0]
        assert manager._validate_id_format("T-001", EntityType.TICKET)[0]
        
        # Invalid formats
        assert not manager._validate_id_format("X-001")[0]
        assert not manager._validate_id_format("S-1")[0]  # Too few digits
        assert not manager._validate_id_format("US-001", EntityType.TICKET)[0]  # Wrong type
        
        print("✓ test_id_format_validation passed")

def run_all_tests():
    tests = [
        test_scope_creation,
        test_user_story_creation,
        test_ticket_creation,
        test_traceability_chain,
        test_duplicate_id_rejection,
        test_dangling_reference_detection,
        test_cycle_detection,
        test_orphan_user_story,
        test_orphan_ticket,
        test_report_generation,
        test_id_format_validation,
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