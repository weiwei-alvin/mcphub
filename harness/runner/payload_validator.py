#!/usr/bin/env python3
"""
Payload Validator for Harness Runner

Validates agent-submitted payloads against JSON schemas and Harness rules.
Runner MUST NOT auto-fix agent payloads - validation failures are hard errors.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from jsonschema import validate, ValidationError, Draft202012Validator
from state_transition import active_tickets, is_active

HARNESS_DIR = Path(".harness")
SCHEMA_DIR = Path("harness")
STATE_FILE = HARNESS_DIR / "state.json"

# Payload types and their schema files
PAYLOAD_SCHEMAS = {
    "gate": "gate-result.schema.json",
    "review": "review-result.schema.json",
    "finding": "finding.schema.json",
    "handoff": "handoff.schema.json",
    "change-impact": "change-impact.schema.json",
}


class PayloadValidator:
    def __init__(self, project_root: Path = None):
        self.project_root = project_root or Path.cwd()
        self.schema_dir = self.project_root / SCHEMA_DIR
        self.harness_dir = self.project_root / HARNESS_DIR
        self.state_file = self.harness_dir / "state.json"
        self._validators = {}
        self._load_schemas()

    def _load_schemas(self):
        """Load and compile all schema validators."""
        from schema_validation import validator
        for payload_type, schema_file in PAYLOAD_SCHEMAS.items():
            self._validators[payload_type] = validator(self.schema_dir, schema_file)

    def validate_schema(self, payload_type: str, payload: Dict) -> Tuple[bool, Optional[str]]:
        """Validate payload against its JSON schema."""
        if payload_type not in self._validators:
            return False, f"Unknown payload type: {payload_type}"

        validator = self._validators[payload_type]
        try:
            validator.validate(payload)
            return True, None
        except ValidationError as e:
            return False, self._format_validation_error(e)
        except Exception as e:
            return False, f"Schema reference error: {e}"

    def _format_validation_error(self, e: ValidationError) -> str:
        """Format validation error for readability."""
        path = " -> ".join(str(p) for p in e.absolute_path) if e.absolute_path else "(root)"
        return f"[{path}] {e.message}"

    def read_state(self) -> Optional[Dict]:
        """Read current state."""
        if not self.state_file.exists():
            return None
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return None

    def validate_gate_payload(self, payload: Dict) -> Tuple[bool, List[str]]:
        """Validate gate-result payload with Harness rules."""
        errors = []

        # Schema validation
        valid, error = self.validate_schema("gate", payload)
        if not valid:
            errors.append(f"Schema: {error}")
            return False, errors

        state = self.read_state()
        if not state:
            errors.append("No valid state found")
            return False, errors

        # Check stage matches current pipeline stage
        payload_stage = payload.get("stage")
        current_stage = state.get("pipeline_stage")
        if payload_stage != current_stage:
            errors.append(
                f"Stage mismatch: payload targets '{payload_stage}' but current stage is '{current_stage}'"
            )

        # If PASS, all criteria must be PASS (enforced by schema, but double-check)
        if payload.get("verdict") == "PASS":
            for criterion in payload.get("criteria", []):
                if criterion.get("status") != "PASS":
                    errors.append(
                        f"Criterion {criterion.get('id')} is {criterion.get('status')} but verdict is PASS"
                    )

        # If USER_DECISION_REQUIRED, decision_context required (schema enforces)
        if payload.get("verdict") == "USER_DECISION_REQUIRED":
            if not payload.get("decision_context"):
                errors.append("USER_DECISION_REQUIRED requires decision_context")

        return len(errors) == 0, errors

    def validate_review_payload(self, payload: Dict) -> Tuple[bool, List[str]]:
        """Validate review-result payload with Harness rules."""
        errors = []

        # Schema validation
        valid, error = self.validate_schema("review", payload)
        if not valid:
            errors.append(f"Schema: {error}")
            return False, errors

        state = self.read_state()
        if not state:
            errors.append("No valid state found")
            return False, errors

        # Check ticket_id matches active ticket
        payload_ticket = payload.get("ticket_id")
        active = active_tickets(state)
        if not is_active(state, payload_ticket):
            errors.append(
                f"Ticket mismatch: payload targets '{payload_ticket}' but active ticket is '{', '.join(active) or None}'"
            )

        # Check ticket is in IMPLEMENTATION or REVIEW stage
        current_stage = state.get("pipeline_stage")
        if current_stage not in ["IMPLEMENTATION", "REVIEW"]:
            errors.append(f"Review only allowed in IMPLEMENTATION/REVIEW stage, current: {current_stage}")

        # Check ticket exists and is IN_PROGRESS or READY_FOR_REVIEW
        tickets = state.get("tickets", {})
        if payload_ticket not in tickets:
            errors.append(f"Ticket {payload_ticket} not found in state")
        else:
            ticket_status = tickets[payload_ticket].get("status")
            if ticket_status not in ["IN_PROGRESS", "READY_FOR_REVIEW"]:
                errors.append(f"Ticket {payload_ticket} status is {ticket_status}, not ready for review")

        # PASS verdict: no blocking findings, all critical criteria PASS (schema enforces)
        # FIX_REQUIRED: at least one blocking finding (schema enforces)
        # USER_DECISION_REQUIRED: decision_context required (schema enforces)

        return len(errors) == 0, errors

    def validate_finding_payload(self, payload: Dict) -> Tuple[bool, List[str]]:
        """Validate finding payload."""
        errors = []

        # Schema validation
        valid, error = self.validate_schema("finding", payload)
        if not valid:
            errors.append(f"Schema: {error}")
            return False, errors

        # Additional rules from finding.schema.json description
        finding_key = payload.get("finding_key", "")
        if finding_key and not finding_key.islower():
            errors.append(f"finding_key must be lowercase slug: {finding_key}")

        return len(errors) == 0, errors

    def validate_handoff_payload(self, payload: Dict) -> Tuple[bool, List[str]]:
        """Validate handoff payload with Harness rules."""
        errors = []

        # Schema validation
        valid, error = self.validate_schema("handoff", payload)
        if not valid:
            errors.append(f"Schema: {error}")
            return False, errors

        state = self.read_state()
        if not state:
            errors.append("No valid state found")
            return False, errors

        # Check ticket_id matches active ticket
        payload_ticket = payload.get("ticket_id")
        active = active_tickets(state)
        if not is_active(state, payload_ticket):
            errors.append(
                f"Ticket mismatch: payload targets '{payload_ticket}' but active ticket is '{', '.join(active) or None}'"
            )

        # Check ticket is IN_PROGRESS or READY_FOR_REVIEW
        tickets = state.get("tickets", {})
        if payload_ticket in tickets:
            ticket_status = tickets[payload_ticket].get("status")
            if ticket_status not in ["IN_PROGRESS", "READY_FOR_REVIEW"]:
                errors.append(f"Ticket {payload_ticket} status is {ticket_status}, not ready for handoff")

        # Verification steps must not have FAIL status (per handoff.schema.json)
        for step in payload.get("verification", []):
            if step.get("status") == "FAIL":
                errors.append(f"Verification step '{step.get('step')}' has FAIL status - must fix before handoff")

        return len(errors) == 0, errors

    def validate_change_impact_payload(self, payload: Dict) -> Tuple[bool, List[str]]:
        """Validate change-impact payload."""
        errors = []

        # Schema validation
        valid, error = self.validate_schema("change-impact", payload)
        if not valid:
            errors.append(f"Schema: {error}")
            return False, errors

        state = self.read_state()
        if not state:
            errors.append("No valid state found")
            return False, errors

        # Check all affected_tickets exist in state
        tickets = state.get("tickets", {})
        for affected in payload.get("affected_tickets", []):
            ticket_id = affected.get("ticket_id")
            if ticket_id not in tickets:
                errors.append(f"Affected ticket {ticket_id} not found in state")

        return len(errors) == 0, errors

    def validate(self, payload_type: str, payload: Dict) -> Tuple[bool, List[str]]:
        """Main validation entry point."""
        validators = {
            "gate": self.validate_gate_payload,
            "review": self.validate_review_payload,
            "finding": self.validate_finding_payload,
            "handoff": self.validate_handoff_payload,
            "change-impact": self.validate_change_impact_payload,
        }

        if payload_type not in validators:
            return False, [f"Unknown payload type: {payload_type}"]

        return validators[payload_type](payload)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Harness Payload Validator")
    parser.add_argument("type", choices=list(PAYLOAD_SCHEMAS.keys()), help="Payload type to validate")
    parser.add_argument("--file", "-f", help="JSON file to validate (default: stdin)")
    parser.add_argument("--strict", action="store_true", help="Exit with error code on validation failure")

    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args()

    # Read payload
    if args.file:
        with open(args.file, 'r', encoding='utf-8') as f:
            payload = json.load(f)
    else:
        payload = json.load(sys.stdin)

    validator = PayloadValidator(args.project_root)
    valid, errors = validator.validate(args.type, payload)

    if valid:
        print(f"✓ {args.type} payload is valid")
        sys.exit(0)
    else:
        print(f"✗ {args.type} payload validation failed:")
        for err in errors:
            print(f"  - {err}")
        if args.strict:
            sys.exit(1)
        else:
            sys.exit(2)


if __name__ == "__main__":
    main()