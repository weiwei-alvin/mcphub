#!/usr/bin/env python3
"""
Ticket Dependency Scheduler for Harness

Manages ticket execution order based on declared dependencies.
- Only allows tickets with all dependencies COMPLETE to start
- Rejects non-existent dependencies
- Rejects circular dependencies
- Picks by approval order when multiple tickets ready
"""

import re
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass
from enum import Enum

from state_transition import TicketStatus


class DependencyError(Exception):
    """Exception for dependency-related errors."""
    pass


@dataclass
class TicketInfo:
    """Information about a ticket from its file."""
    ticket_id: str
    depends_on: List[str]
    status: TicketStatus
    approval_order: int  # Position in filename sort order (T-001.md, T-002.md, ...)


class DependencyScheduler:
    """
    Schedules ticket execution based on dependencies.
    
    Rules:
    - Only tickets with all dependencies COMPLETE can start
    - Non-existent dependencies are rejected
    - Circular dependencies are rejected
    - Multiple ready tickets: pick the smallest ticket filename (T-001 before T-002)
    """

    def __init__(self, project_root: Path = None):
        self.project_root = project_root or Path.cwd()
        self.tickets_dir = self.project_root / ".harness" / "tickets"

    def load_ticket_files(self) -> Dict[str, TicketInfo]:
        """Load all ticket files from .harness/tickets/ directory."""
        tickets = {}
        
        if not self.tickets_dir.exists():
            return tickets
        
        # Get files sorted by name (approval order)
        ticket_files = sorted(self.tickets_dir.glob("T-*.md"))
        
        for order, ticket_file in enumerate(ticket_files):
            try:
                ticket_info = self._parse_ticket_file(ticket_file, order)
                if ticket_info:
                    tickets[ticket_info.ticket_id] = ticket_info
            except Exception as e:
                raise DependencyError(f"Invalid ticket {ticket_file.name}: {e}") from e
        
        return tickets

    def _parse_ticket_file(self, ticket_file: Path, approval_order: int) -> Optional[TicketInfo]:
        """Parse a ticket markdown file."""
        content = ticket_file.read_text(encoding='utf-8')
        
        # Extract frontmatter (between ---)
        if not content.startswith('---'):
            raise DependencyError(f'Missing or malformed frontmatter/id: {ticket_file.name}')
        
        parts = content.split('---', 2)
        if len(parts) < 3:
            raise DependencyError(f'Missing or malformed frontmatter/id: {ticket_file.name}')
        
        frontmatter = parts[1].strip()
        
        # Parse YAML-like frontmatter
        ticket_id = None
        depends_on = []
        seen_dependencies = False
        
        for line in frontmatter.split('\n'):
            line = line.strip()
            if line.startswith('id:'):
                ticket_id = line[3:].strip()
            elif line.startswith('depends_on:'):
                # Parse depends_on: [T-001, T-002] or depends_on: []
                if seen_dependencies: raise DependencyError('Duplicate depends_on')
                seen_dependencies = True
                dep_str = line[11:].strip()
                if not re.fullmatch(r'\[(?:\s*T-\d{3,}(?:\s*,\s*T-\d{3,})*)?\s*\]', dep_str):
                    raise DependencyError('depends_on requires inline [T-001, T-002] or []; multiline/scalar format unsupported')
                if dep_str.startswith('[') and dep_str.endswith(']'):
                    dep_str = dep_str[1:-1].strip()
                    if dep_str:
                        depends_on = [d.strip() for d in dep_str.split(',')]
        
        if not ticket_id:
            raise DependencyError(f'Missing or malformed frontmatter/id: {ticket_file.name}')
        
        if not re.fullmatch(r'T-\d{3,}', ticket_id) or ticket_id != ticket_file.stem:
            raise DependencyError('Ticket id must match filename T-NNN.md')
        return TicketInfo(
            ticket_id=ticket_id,
            depends_on=depends_on,
            status=TicketStatus.TODO,  # Will be updated from state
            approval_order=approval_order
        )

    def validate_dependencies(self, tickets: Dict[str, TicketInfo]) -> List[str]:
        """
        Validate all dependencies.
        Returns list of errors (empty if valid).
        """
        errors = []
        ticket_ids = set(tickets.keys())
        
        for ticket_id, ticket in tickets.items():
            # Check non-existent dependencies
            for dep in ticket.depends_on:
                if dep not in ticket_ids:
                    errors.append(f"Ticket {ticket_id} depends on non-existent ticket {dep}")
        
        # Check circular dependencies
        cycles = self._find_circular_dependencies(tickets)
        for cycle in cycles:
            errors.append(f"Circular dependency detected: {' -> '.join(cycle)} -> {cycle[0]}")
        
        return errors

    def _find_circular_dependencies(self, tickets: Dict[str, TicketInfo]) -> List[List[str]]:
        """Find all circular dependencies using DFS."""
        visited = set()
        rec_stack = set()
        cycles = []
        path = []
        
        def dfs(node: str):
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            for dep in tickets[node].depends_on:
                if dep not in tickets:
                    continue
                if dep not in visited:
                    dfs(dep)
                elif dep in rec_stack:
                    # Found cycle
                    cycle_start = path.index(dep)
                    cycle = path[cycle_start:] + [dep]
                    if cycle not in cycles:
                        cycles.append(cycle)
            
            rec_stack.remove(node)
            path.pop()
        
        for ticket_id in tickets:
            if ticket_id not in visited:
                dfs(ticket_id)
        
        return cycles

    def get_executable_tickets(self, state: Dict, ticket_files: Dict[str, TicketInfo]) -> List[str]:
        """
        Get list of tickets that can be started now.
        Returns tickets sorted by approval order.
        """
        tickets_state = state.get("tickets", {})
        executable = []
        
        for ticket_id, ticket_file in ticket_files.items():
            # Check if ticket exists in state
            if ticket_id not in tickets_state:
                continue
            
            ticket_state = tickets_state[ticket_id]
            
            # Only TODO tickets can start
            if ticket_state["status"] != TicketStatus.TODO.value:
                continue
            
            # Check all dependencies are COMPLETE
            deps_complete = True
            for dep in ticket_file.depends_on:
                if dep not in tickets_state:
                    deps_complete = False
                    break
                if tickets_state[dep]["status"] != TicketStatus.COMPLETE.value:
                    deps_complete = False
                    break
            
            if deps_complete:
                executable.append((ticket_file.approval_order, ticket_id))
        
        # Sort by approval order
        executable.sort(key=lambda x: x[0])
        return [tid for _, tid in executable]

    def get_next_ticket(self, state: Dict, ticket_files: Dict[str, TicketInfo]) -> Optional[str]:
        """Get the next ticket to execute (by approval order)."""
        executable = self.get_executable_tickets(state, ticket_files)
        return executable[0] if executable else None

    def get_blocked_tickets(self, state: Dict, ticket_files: Dict[str, TicketInfo]) -> Dict[str, List[str]]:
        """
        Get tickets that are blocked and why.
        Returns dict: ticket_id -> list of blocking dependency IDs.
        """
        tickets_state = state.get("tickets", {})
        blocked = {}
        
        for ticket_id, ticket_file in ticket_files.items():
            if ticket_id not in tickets_state:
                continue
            
            ticket_state = tickets_state[ticket_id]
            
            # Skip if already in progress or complete
            if ticket_state["status"] in [TicketStatus.IN_PROGRESS.value, TicketStatus.COMPLETE.value]:
                continue
            
            # Check which dependencies are not complete
            blocking = []
            for dep in ticket_file.depends_on:
                if dep not in tickets_state:
                    blocking.append(f"{dep} (not found)")
                elif tickets_state[dep]["status"] != TicketStatus.COMPLETE.value:
                    blocking.append(f"{dep} ({tickets_state[dep]['status']})")
            
            if blocking:
                blocked[ticket_id] = blocking
        
        return blocked

    def can_start_ticket(self, state: Dict, ticket_id: str, ticket_files: Dict[str, TicketInfo]) -> Tuple[bool, Optional[str]]:
        """Check if a specific ticket can be started."""
        if ticket_id not in ticket_files:
            return False, f"Ticket {ticket_id} not found in ticket files"
        
        ticket_file = ticket_files[ticket_id]
        tickets_state = state.get("tickets", {})
        
        if ticket_id not in tickets_state:
            return False, f"Ticket {ticket_id} not in state"
        
        ticket_state = tickets_state[ticket_id]
        
        if ticket_state["status"] != TicketStatus.TODO.value:
            return False, f"Ticket {ticket_id} is {ticket_state['status']}, not TODO"
        
        # Check dependencies
        for dep in ticket_file.depends_on:
            if dep not in tickets_state:
                return False, f"Dependency {dep} not found in state"
            if tickets_state[dep]["status"] != TicketStatus.COMPLETE.value:
                return False, f"Dependency {dep} is {tickets_state[dep]['status']}, not COMPLETE"
        
        return True, None


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Ticket Dependency Scheduler")
    parser.add_argument("command", choices=[
        "validate", "executable", "next", "blocked", "can-start"
    ])
    parser.add_argument("--ticket", help="Ticket ID for can-start")
    
    parser.add_argument("--project-root",type=Path,default=Path.cwd())
    args = parser.parse_args()
    
    scheduler = DependencyScheduler(args.project_root)
    ticket_files = scheduler.load_ticket_files()
    
    if not ticket_files:
        print("No ticket files found in .harness/tickets/")
        if args.command == "validate":
            print("No dependencies to validate")
        sys.exit(1)
    
    # Load state
    state_file = args.project_root / ".harness/state.json"
    if state_file.exists():
        with open(state_file, 'r', encoding='utf-8') as f:
            state = json.load(f)
    else:
        state = {"tickets": {}}
    
    if args.command == "validate":
        errors = scheduler.validate_dependencies(ticket_files)
        if errors:
            print("Dependency validation errors:")
            for err in errors:
                print(f"  - {err}")
            sys.exit(1)
        else:
            print("All dependencies valid")
    
    elif args.command == "executable":
        executable = scheduler.get_executable_tickets(state, ticket_files)
        if executable:
            print("Executable tickets (in order):")
            for tid in executable:
                print(f"  {tid}")
        else:
            print("No tickets ready to execute")
    
    elif args.command == "next":
        next_ticket = scheduler.get_next_ticket(state, ticket_files)
        if next_ticket:
            print(next_ticket)
        else:
            print("No next ticket available")
    
    elif args.command == "blocked":
        blocked = scheduler.get_blocked_tickets(state, ticket_files)
        if blocked:
            print("Blocked tickets:")
            for tid, blockers in blocked.items():
                print(f"  {tid}: blocked by {', '.join(blockers)}")
        else:
            print("No blocked tickets")
    
    elif args.command == "can-start":
        if not args.ticket:
            print("--ticket required")
            sys.exit(1)
        can_start, reason = scheduler.can_start_ticket(state, args.ticket, ticket_files)
        if can_start:
            print(f"Ticket {args.ticket} can start")
        else:
            print(f"Ticket {args.ticket} cannot start: {reason}")
            sys.exit(1)


if __name__ == "__main__":
    import sys
    try:
        main()
    except (ValueError, OSError, DependencyError) as exc:
        print(f"Dependency error: {exc}",file=sys.stderr)
        sys.exit(1)