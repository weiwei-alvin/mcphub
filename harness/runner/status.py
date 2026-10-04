#!/usr/bin/env python3
"""
Harness Status Command

Displays project status, stage, tickets progress, review attempts, blocking findings.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from state_transition import active_tickets
from traceability import TraceabilityManager, EntityType


class HarnessStatus:
    """Displays comprehensive project status."""

    def __init__(self, project_root: Path = None):
        self.project_root = project_root or Path.cwd()
        self.harness_dir = self.project_root / ".harness"
        self.state_file = self.harness_dir / "state.json"
        self.trace_manager = TraceabilityManager(self.project_root)

    def load_state(self) -> Optional[Dict]:
        """Load state from file."""
        if not self.state_file.exists():
            return None
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return None

    def get_status(self) -> Dict:
        """Get comprehensive status."""
        state = self.load_state()
        if not state:
            return {"error": "No valid state found"}

        # Ticket statistics
        tickets = state.get("tickets", {})
        total_tickets = len(tickets)
        ticket_status_counts = {}
        review_attempts = {}
        active_findings = {}
        
        for tid, ticket in tickets.items():
            status = ticket.get("status", "UNKNOWN")
            ticket_status_counts[status] = ticket_status_counts.get(status, 0) + 1
            review_attempts[tid] = ticket.get("review_attempts", 0)
            active_findings[tid] = ticket.get("active_findings", [])

        # Findings statistics
        findings = state.get("findings", {})
        finding_status_counts = {}
        for fid, finding in findings.items():
            fstatus = finding.get("status", "UNKNOWN")
            finding_status_counts[fstatus] = finding_status_counts.get(fstatus, 0) + 1

        # Same unresolved definition as the completion workflow (do not trust index alone).
        blocking_findings = [dict(finding_id=fid, ticket_id=f['ticket_id'],
            finding_key=f.get('finding_key'), criterion_ref=f.get('criterion_ref'))
            for fid, f in findings.items()
            if f.get('status') in ('OPEN','REOPENED') and f.get('blocking',True)]

        # Traceability stats
        trace_entities = self.trace_manager.list_entities()
        scopes = [e for e in trace_entities if e.type == EntityType.SCOPE]
        stories = [e for e in trace_entities if e.type == EntityType.USER_STORY]
        trace_tickets = [e for e in trace_entities if e.type == EntityType.TICKET]

        # Completed tickets with traceability
        completed_ticket_ids = [tid for tid, t in tickets.items() if t.get("status") == "COMPLETE"]
        completed_traceable = [tid for tid in completed_ticket_ids if tid in [t.id for t in trace_tickets]]

        # Pause info
        pause_info = None
        if state.get("pause"):
            pause_info = {
                "reason": state["pause"].get("reason"),
                "decision_ref": state["pause"].get("decision_ref")
            }

        return {
            "project_status": state.get("project_status"),
            "pipeline_stage": state.get("pipeline_stage"),
            "stage_status": state.get("stage_status"),
            "active_ticket_id": state.get("active_ticket_id"),
            "active_tickets": active_tickets(state),
            "pause": pause_info,
            "tickets": {
                "total": total_tickets,
                "by_status": ticket_status_counts,
                "completed": completed_ticket_ids,
                "completed_with_traceability": completed_traceable,
                "review_attempts": review_attempts,
                "blocking_findings_count": len(blocking_findings),
                "blocking_findings": blocking_findings
            },
            "findings": {
                "total": len(findings),
                "by_status": finding_status_counts
            },
            "traceability": {
                "scopes": len(scopes),
                "user_stories": len(stories),
                "tickets": len(trace_tickets),
                "coverage": {
                    "tickets_with_traceability": len([t for t in trace_tickets if t.id in tickets]),
                    "total_tickets_in_state": total_tickets
                }
            }
        }

    def print_status(self):
        """Print formatted status."""
        status = self.get_status()
        
        if "error" in status:
            print(f"Error: {status['error']}")
            return
        
        print("=" * 60)
        print("HARNESS PROJECT STATUS")
        print("=" * 60)
        
        # Project status
        print(f"\nProject Status: {status['project_status']}")
        print(f"Pipeline Stage: {status['pipeline_stage']} ({status['stage_status']})")
        if len(status['active_tickets']) > 1:
            print(f"Active Tickets: {', '.join(status['active_tickets'])} (focus: {status['active_ticket_id']})")
        elif status['active_ticket_id']:
            print(f"Active Ticket: {status['active_ticket_id']}")
        
        if status['pause']:
            print(f"\n⚠️  PAUSED: {status['pause']['reason']}")
            print(f"   Decision Ref: {status['pause']['decision_ref']}")
        
        # Tickets
        print(f"\n--- Tickets ({status['tickets']['total']} total) ---")
        for status_name, count in status['tickets']['by_status'].items():
            print(f"  {status_name}: {count}")
        
        if status['tickets']['completed']:
            print(f"  Completed: {', '.join(status['tickets']['completed'])}")
        
        # Review attempts
        print("\n--- Review Attempts ---")
        for tid, attempts in status['tickets']['review_attempts'].items():
            if attempts > 0:
                print(f"  {tid}: {attempts} cumulative FIX_REQUIRED reviews")
        
        # Blocking findings
        if status['tickets']['blocking_findings']:
            print(f"\n--- Blocking Findings ({status['tickets']['blocking_findings_count']}) ---")
            for bf in status['tickets']['blocking_findings']:
                print(f"  {bf['finding_id']} ({bf['finding_key']}) on {bf['ticket_id']} - criterion: {bf['criterion_ref']}")
        else:
            print("\n--- Blocking Findings: 0 ---")
        
        # Findings summary
        print("\n--- Findings ---")
        for fstatus, count in status['findings']['by_status'].items():
            print(f"  {fstatus}: {count}")
        
        # Traceability
        print("\n--- Traceability ---")
        print(f"  Scopes: {status['traceability']['scopes']}")
        print(f"  User Stories: {status['traceability']['user_stories']}")
        print(f"  Tickets (in traceability): {status['traceability']['tickets']}")
        cov = status['traceability']['coverage']
        print(f"  Coverage: {cov['tickets_with_traceability']}/{cov['total_tickets_in_state']} tickets traceable")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Harness Status")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    parser.add_argument("--project-root",type=Path,default=Path.cwd())
    args = parser.parse_args()
    status_cmd = HarnessStatus(args.project_root)
    
    if args.json:
        print(json.dumps(status_cmd.get_status(), indent=2, ensure_ascii=False))
    else:
        status_cmd.print_status()
    return 1 if "error" in status_cmd.get_status() else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())