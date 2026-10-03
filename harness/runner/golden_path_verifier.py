#!/usr/bin/env python3
"""
Incremental Golden Path Verification for Harness

Verifies executable golden path segments as vertical slices complete.
Does NOT require full E2E per ticket.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
from enum import Enum


class VerificationStatus(Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    UNVERIFIED = "UNVERIFIED"


@dataclass
class GoldenPathStep:
    """A step in the V1 golden path."""
    id: str
    description: str
    user_story_ids: List[str]
    ticket_ids: List[str]  # Tickets that implement this step
    verification_command: str  # Command to verify this step
    expected_output: str


@dataclass
class VerificationResult:
    """Result of a verification step."""
    step_id: str
    status: VerificationStatus
    output: str
    error: Optional[str] = None
    returncode: Optional[int] = None
    stderr: str = ""


class GoldenPathVerifier:
    """
    Verifies golden path incrementally as vertical slices complete.
    
    Rules:
    - When a vertical slice (Ticket) completes, verify the golden path steps it enables
    - Don't require full E2E per ticket
    - Record results in handoff verification
    - Mark UNVERIFIED if cannot execute
    - Final integrated verification still required at the end
    """

    def __init__(self, project_root: Path = None, *, trusted=False, timeout=60):
        self.project_root = Path(project_root or Path.cwd()).resolve()
        self.trusted = trusted
        self.timeout = timeout
        self.harness_dir = self.project_root / ".harness"
        self.spec_file = self.project_root / "SPEC.md"
        self.golden_path_file = self.harness_dir / "golden_path.json"
        self.state_file = self.harness_dir / "state.json"
        self._golden_path: List[GoldenPathStep] = []
        self._load_golden_path()
        seen=set()
        for step in self._golden_path:
            if not isinstance(step.id,str) or not step.id or step.id in seen:
                raise ValueError('Golden Path IDs must be nonempty and unique')
            seen.add(step.id)
            if not isinstance(step.ticket_ids,list) or not all(isinstance(x,str) for x in step.ticket_ids):
                raise ValueError('ticket_ids must be an array of strings')
            cmd=step.verification_command
            if not isinstance(cmd,(str,list)) or (isinstance(cmd,list) and (not cmd or not all(isinstance(x,str) and x for x in cmd))):
                raise ValueError('verification_command must be a string or nonempty argv array')


    def _load_golden_path(self):
        """Load golden path from SPEC.md or golden_path.json."""
        # First try golden_path.json
        if self.golden_path_file.exists():
            from storage import project_settings
            project_settings(self.project_root)  # validates top-level keys and settings
            try:
                with open(self.golden_path_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._golden_path = [GoldenPathStep(**step) for step in data.get("steps", [])]
                return
            except Exception as exc:
                raise ValueError(f"Invalid golden_path.json: {exc}") from exc
        
        # Try to parse from SPEC.md
        if self.spec_file.exists():
            self._parse_spec_golden_path()

    def _parse_spec_golden_path(self):
        """Parse golden path from SPEC.md."""
        content = self.spec_file.read_text(encoding='utf-8')
        
        # Look for "Golden Path" or "V1 Golden Path" section
        lines = content.split('\n')
        in_golden_path = False
        
        for line in lines:
            if "golden path" in line.lower() or "v1 golden path" in line.lower():
                in_golden_path = True
                continue
            if in_golden_path and line.startswith("## "):
                break  # Next section
            if in_golden_path and line.strip().startswith("- "):
                # Parse step: "- GP-001: User logs in with valid credentials (US-001, T-001, T-002) - `python -c "print('LOGIN_OK')"` - Expected: LOGIN_OK"
                step_text = line.strip()[2:].strip()
                try:
                    self._parse_golden_path_step(step_text)
                except ValueError as e:
                    raise ValueError(f"Golden Path parse error at line: '{line.strip()}': {e}")
    
    def _parse_golden_path_step(self, step_text: str):
        """Parse a single golden path step line. Raises ValueError if format is invalid."""
        import re
        
        # Pattern: GP-NNN: Description (US-XXX, T-YYY) - `command` - Expected: output
        pattern = r'^(GP-\d+):\s*(.+?)\s*\(([^)]+)\)\s*-\s*`([^`]+)`\s*-\s*Expected:\s*(.+)$'
        match = re.match(pattern, step_text)
        
        if not match:
            # Try simpler pattern without expected
            pattern2 = r'^(GP-\d+):\s*(.+?)\s*\(([^)]+)\)\s*-\s*`([^`]+)`\s*$'
            match = re.match(pattern2, step_text)
            expected = ""
            if not match:
                raise ValueError(f"Invalid Golden Path step format: '{step_text}'. Expected: 'GP-NNN: Description (US-XXX, T-YYY) - `command` - Expected: output'")
        
        if len(match.groups()) == 4:
            step_id, description, refs, command = match.groups()
            expected = ""
        else:
            step_id, description, refs, command, expected = match.groups()
        
        # Parse references (US-001, T-001, T-002)
        user_story_ids = []
        ticket_ids = []
        for ref in refs.split(","):
            ref = ref.strip()
            if ref.startswith("US-"):
                user_story_ids.append(ref)
            elif ref.startswith("T-"):
                ticket_ids.append(ref)
        
        step = GoldenPathStep(
            id=step_id,
            description=description,
            user_story_ids=user_story_ids,
            ticket_ids=ticket_ids,
            verification_command=command,
            expected_output=expected
        )
        self._golden_path.append(step)

    def save_golden_path(self):
        """Save golden path to file."""
        self.harness_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "version": "1.0",
            "steps": [
                {
                    "id": s.id,
                    "description": s.description,
                    "user_story_ids": s.user_story_ids,
                    "ticket_ids": s.ticket_ids,
                    "verification_command": s.verification_command,
                    "expected_output": s.expected_output
                }
                for s in self._golden_path
            ]
        }
        with open(self.golden_path_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get_all_steps(self) -> List[GoldenPathStep]:
        return list(self._golden_path)

    def get_steps_for_tickets(self, completed_ticket_ids: List[str]) -> List[GoldenPathStep]:
        """Get golden path steps that are enabled by completed tickets."""
        enabled_steps = []
        for step in self._golden_path:
            # Check if all ticket_ids for this step are completed
            if all(tid in completed_ticket_ids for tid in step.ticket_ids):
                enabled_steps.append(step)
        return enabled_steps

    def verify_steps(self, step_ids: List[str]) -> List[VerificationResult]:
        """Verify specific golden path steps."""
        results = []
        
        for step_id in step_ids:
            step = next((s for s in self._golden_path if s.id == step_id), None)
            if not step:
                results.append(VerificationResult(
                    step_id=step_id,
                    status=VerificationStatus.FAILED,
                    output="",
                    error=f"Step {step_id} not found"
                ))
                continue
            
            if not step.verification_command:
                results.append(VerificationResult(
                    step_id=step_id,
                    status=VerificationStatus.UNVERIFIED,
                    output="",
                    error="No verification command defined"
                ))
                continue
            
            from command_execution import execute
            try:
                result = execute(step.verification_command, self.project_root, trusted=self.trusted, timeout=self.timeout)
                passed = result['status'] == 'PASSED'
                error = result.get('error') or (result['stderr'] if not passed else None)
                if passed and step.expected_output and step.expected_output not in result['stdout']:
                    passed = False
                    error = f"Expected output not found: {step.expected_output}"
                results.append(VerificationResult(step_id, VerificationStatus.PASSED if passed else VerificationStatus.FAILED,
                    result['stdout'], error, result['returncode'], result['stderr']))
            except Exception as exc:
                results.append(VerificationResult(step_id, VerificationStatus.FAILED, '', str(exc)))

        return results

    def verify_incremental(self, completed_ticket_ids: List[str]) -> Dict:
        """Verify all newly enabled golden path steps."""
        enabled_steps = self.get_steps_for_tickets(completed_ticket_ids)
        step_ids = [s.id for s in enabled_steps]
        
        if not step_ids:
            return {
                "verified_steps": [],
                "unverified_steps": [],
                "all_passed": False,
                "message": "No enabled verification; not acceptance evidence"
            }
        
        results = self.verify_steps(step_ids)
        
        passed = [r for r in results if r.status == VerificationStatus.PASSED]
        failed = [r for r in results if r.status == VerificationStatus.FAILED]
        unverified = [r for r in results if r.status == VerificationStatus.UNVERIFIED]
        
        return {
            "verified_steps": [r.step_id for r in passed],
            "failed_steps": [{"step_id": r.step_id, "error": r.error} for r in failed],
            "unverified_steps": [{"step_id": r.step_id, "reason": r.error} for r in unverified],
            "all_passed": len(failed) == 0 and len(unverified) == 0
        }

    def verify_final_integrated(self) -> Dict:
        """Run final integrated verification (all golden path steps)."""
        if not self._golden_path:
            return {
                "status": "UNVERIFIED",
                "message": "No golden path defined in SPEC.md"
            }
        
        step_ids = [s.id for s in self._golden_path]
        results = self.verify_steps(step_ids)
        
        passed = [r for r in results if r.status == VerificationStatus.PASSED]
        failed = [r for r in results if r.status == VerificationStatus.FAILED]
        unverified = [r for r in results if r.status == VerificationStatus.UNVERIFIED]
        
        return {
            "status": "PASSED" if len(failed) == 0 and len(unverified) == 0 else "FAILED",
            "total_steps": len(step_ids),
            "passed": len(passed),
            "failed": len(failed),
            "unverified": len(unverified),
            "details": [
                {
                    "step_id": r.step_id,
                    "status": r.status.value,
                    "output": r.output,
                    "returncode": r.returncode,
                    "stderr": r.stderr,
                    "error": r.error
                }
                for r in results
            ]
        }


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Golden Path Verifier")
    parser.add_argument("command", choices=[
        "verify-incremental", "verify-final", "list-steps"
    ])
    parser.add_argument("--tickets", help="Completed ticket IDs, comma-separated")
    
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--trust-commands", action="store_true", help="Authorize host execution; cwd is not a sandbox")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    verifier = GoldenPathVerifier(args.project_root, trusted=args.trust_commands, timeout=args.timeout)
    
    if args.command == "list-steps":
        if not verifier._golden_path:
            print("No golden path defined")
            return
        for step in verifier._golden_path:
            print(f"{step.id}: {step.description}")
            print(f"  Tickets: {', '.join(step.ticket_ids) if step.ticket_ids else 'None'}")
            print(f"  Command: {step.verification_command or 'None'}")
            print()
    
    elif args.command == "verify-incremental":
        if not args.tickets:
            print("--tickets required")
            return 1
        ticket_ids = [t.strip() for t in args.tickets.split(",")]
        result = verifier.verify_incremental(ticket_ids)
        print(json.dumps(result, indent=2))
        if not result.get("all_passed", True):
            return 1
    
    elif args.command == "verify-final":
        result = verifier.verify_final_integrated()
        print(json.dumps(result, indent=2))
        if result.get("status") != "PASSED":
            return 1


if __name__ == "__main__":
    import sys
    try:
        sys.exit(main())
    except (ValueError, OSError) as exc:
        print(f"Verification error: {exc}", file=sys.stderr)
        sys.exit(1)