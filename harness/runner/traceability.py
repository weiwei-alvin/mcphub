#!/usr/bin/env python3
"""
Traceability ID System for Harness

Manages stable IDs for:
- Scope (S-<NNN>) - Product scope items
- User Story (US-<NNN>) - User-facing stories
- Ticket (T-<NNN>) - Implementation tickets

Enforces:
- Unique IDs across all types
- Traceability: US → Scope, Ticket → US/Scope
- No dangling references
- Duplicate detection
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, asdict
from enum import Enum


class EntityType(Enum):
    SCOPE = "S"
    USER_STORY = "US"
    TICKET = "T"


@dataclass
class TraceabilityEntity:
    """Base traceability entity."""
    id: str
    type: EntityType
    title: str
    description: str = ""
    parent_ids: List[str] = None  # Traceability links
    child_ids: List[str] = None   # Reverse links
    status: str = "ACTIVE"
    
    def __post_init__(self):
        if self.parent_ids is None:
            self.parent_ids = []
        if self.child_ids is None:
            self.child_ids = []


class TraceabilityManager:
    """
    Manages traceability IDs and relationships.
    
    ID Format:
    - Scope: S-001, S-002, ...
    - User Story: US-001, US-002, ...
    - Ticket: T-001, T-002, ...
    
    Traceability Rules:
    - Every User Story must trace to at least one Scope
    - Every Ticket must trace to at least one User Story or approved requirement
    - No duplicate IDs
    - No dangling references
    """

    def __init__(self, project_root: Path = None):
        self.project_root = project_root or Path.cwd()
        self.trace_dir = self.project_root / ".harness" / "traceability"
        self.trace_file = self.trace_dir / "traceability.json"
        self._entities: Dict[str, TraceabilityEntity] = {}
        self._id_counters = {EntityType.SCOPE: 0, EntityType.USER_STORY: 0, EntityType.TICKET: 0}
        self._load()

    def _load(self):
        """Load traceability data from file."""
        if not self.trace_file.exists():
            return
        
        try:
            with open(self.trace_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            for entity_data in data.get("entities", []):
                entity = TraceabilityEntity(
                    id=entity_data["id"],
                    type=EntityType(entity_data["type"]),
                    title=entity_data["title"],
                    description=entity_data.get("description", ""),
                    parent_ids=entity_data.get("parent_ids", []),
                    child_ids=entity_data.get("child_ids", []),
                    status=entity_data.get("status", "ACTIVE")
                )
                self._entities[entity.id] = entity
                # Update counters
                self._update_counter(entity.id)
            
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Failed to load traceability: {e}")

    def _update_counter(self, entity_id: str):
        """Update ID counter based on existing ID."""
        match = re.match(r'^(S|US|T)-(\d+)$', entity_id)
        if match:
            prefix, num = match.groups()
            etype = EntityType(prefix)
            self._id_counters[etype] = max(self._id_counters[etype], int(num))

    def _save(self):
        """Save traceability data to file."""
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        
        data = {
            "version": "1.0",
            "entities": [
                {
                    "id": e.id,
                    "type": e.type.value,
                    "title": e.title,
                    "description": e.description,
                    "parent_ids": e.parent_ids,
                    "child_ids": e.child_ids,
                    "status": e.status
                }
                for e in self._entities.values()
            ]
        }
        
        with open(self.trace_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _generate_id(self, entity_type: EntityType) -> str:
        """Generate next available ID for entity type."""
        self._id_counters[entity_type] += 1
        return f"{entity_type.value}-{self._id_counters[entity_type]:03d}"

    def _validate_id_format(self, entity_id: str, expected_type: EntityType = None) -> Tuple[bool, Optional[str]]:
        """Validate ID format."""
        match = re.match(r'^(S|US|T)-(\d{3,})$', entity_id)
        if not match:
            return False, f"Invalid ID format: {entity_id} (expected S-###, US-###, or T-###)"
        
        prefix = match.group(1)
        if expected_type and prefix != expected_type.value:
            return False, f"ID {entity_id} is type {prefix}, expected {expected_type.value}"
        
        return True, None

    def create_scope(self, title: str, description: str = "", scope_id: str = None) -> Tuple[bool, str, Optional[str]]:
        """Create a new Scope."""
        if scope_id is None:
            scope_id = self._generate_id(EntityType.SCOPE)
        else:
            valid, err = self._validate_id_format(scope_id, EntityType.SCOPE)
            if not valid:
                return False, "", err
            if scope_id in self._entities:
                return False, "", f"Duplicate Scope ID: {scope_id}"
            self._update_counter(scope_id)
        
        entity = TraceabilityEntity(
            id=scope_id,
            type=EntityType.SCOPE,
            title=title,
            description=description
        )
        self._entities[scope_id] = entity
        self._save()
        return True, scope_id, None

    def create_user_story(self, title: str, description: str = "", scope_ids: List[str] = None, story_id: str = None) -> Tuple[bool, str, Optional[str]]:
        """Create a new User Story linked to Scope(s)."""
        if story_id is None:
            story_id = self._generate_id(EntityType.USER_STORY)
        else:
            valid, err = self._validate_id_format(story_id, EntityType.USER_STORY)
            if not valid:
                return False, "", err
            if story_id in self._entities:
                return False, "", f"Duplicate User Story ID: {story_id}"
            self._update_counter(story_id)
        
        # Validate scope_ids exist
        if scope_ids:
            for sid in scope_ids:
                if sid not in self._entities:
                    return False, "", f"Scope {sid} does not exist"
                if self._entities[sid].type != EntityType.SCOPE:
                    return False, "", f"{sid} is not a Scope"
        
        entity = TraceabilityEntity(
            id=story_id,
            type=EntityType.USER_STORY,
            title=title,
            description=description,
            parent_ids=scope_ids or []
        )
        
        # Add reverse links
        if scope_ids:
            for sid in scope_ids:
                self._entities[sid].child_ids.append(story_id)
        
        self._entities[story_id] = entity
        self._save()
        return True, story_id, None

    def create_ticket(self, title: str, description: str = "", story_ids: List[str] = None, scope_ids: List[str] = None, ticket_id: str = None) -> Tuple[bool, str, Optional[str]]:
        """Create a new Ticket linked to User Story(s) or Scope(s)."""
        if ticket_id is None:
            ticket_id = self._generate_id(EntityType.TICKET)
        else:
            valid, err = self._validate_id_format(ticket_id, EntityType.TICKET)
            if not valid:
                return False, "", err
            if ticket_id in self._entities:
                return False, "", f"Duplicate Ticket ID: {ticket_id}"
            self._update_counter(ticket_id)
        
        parent_ids = []
        
        # Validate and collect story_ids
        if story_ids:
            for sid in story_ids:
                if sid not in self._entities:
                    return False, "", f"User Story {sid} does not exist"
                if self._entities[sid].type != EntityType.USER_STORY:
                    return False, "", f"{sid} is not a User Story"
                parent_ids.append(sid)
        
        # Validate and collect scope_ids (for technical tickets)
        if scope_ids:
            for sid in scope_ids:
                if sid not in self._entities:
                    return False, "", f"Scope {sid} does not exist"
                if self._entities[sid].type != EntityType.SCOPE:
                    return False, "", f"{sid} is not a Scope"
                parent_ids.append(sid)
        
        # Must have at least one parent
        if not parent_ids:
            return False, "", "Ticket must trace to at least one User Story or Scope"
        
        entity = TraceabilityEntity(
            id=ticket_id,
            type=EntityType.TICKET,
            title=title,
            description=description,
            parent_ids=parent_ids
        )
        
        # Add reverse links
        for pid in parent_ids:
            self._entities[pid].child_ids.append(ticket_id)
        
        self._entities[ticket_id] = entity
        self._save()
        return True, ticket_id, None

    def get_entity(self, entity_id: str) -> Optional[TraceabilityEntity]:
        """Get entity by ID."""
        return self._entities.get(entity_id)

    def get_children(self, entity_id: str) -> List[TraceabilityEntity]:
        """Get direct children of an entity."""
        entity = self._entities.get(entity_id)
        if not entity:
            return []
        return [self._entities[cid] for cid in entity.child_ids if cid in self._entities]

    def get_parents(self, entity_id: str) -> List[TraceabilityEntity]:
        """Get direct parents of an entity."""
        entity = self._entities.get(entity_id)
        if not entity:
            return []
        return [self._entities[pid] for pid in entity.parent_ids if pid in self._entities]

    def get_full_trace(self, entity_id: str) -> Dict:
        """Get full traceability chain for an entity."""
        entity = self._entities.get(entity_id)
        if not entity:
            return {}
        
        # Trace up (ancestors)
        ancestors = []
        visited = set()
        def trace_up(eid: str):
            if eid in visited:
                return
            visited.add(eid)
            for pid in self._entities.get(eid, TraceabilityEntity(id="", type=EntityType.SCOPE, title="")).parent_ids:
                if pid in self._entities:
                    ancestors.append(self._entities[pid])
                    trace_up(pid)
        
        trace_up(entity_id)
        
        # Trace down (descendants)
        descendants = []
        visited.clear()
        def trace_down(eid: str):
            if eid in visited:
                return
            visited.add(eid)
            for cid in self._entities.get(eid, TraceabilityEntity(id="", type=EntityType.SCOPE, title="")).child_ids:
                if cid in self._entities:
                    descendants.append(self._entities[cid])
                    trace_down(cid)
        
        trace_down(entity_id)
        
        return {
            "entity": entity,
            "ancestors": ancestors,
            "descendants": descendants
        }

    def validate_all(self) -> List[str]:
        """Validate entire traceability graph."""
        errors = []
        
        # Check for duplicate IDs (shouldn't happen with dict)
        # Check all references exist
        for entity in self._entities.values():
            for pid in entity.parent_ids:
                if pid not in self._entities:
                    errors.append(f"{entity.id}: references non-existent parent {pid}")
            
            for cid in entity.child_ids:
                if cid not in self._entities:
                    errors.append(f"{entity.id}: references non-existent child {cid}")
        
        # Check traceability rules
        for entity in self._entities.values():
            if entity.type == EntityType.USER_STORY and not entity.parent_ids:
                errors.append(f"User Story {entity.id} has no Scope parent")
            
            if entity.type == EntityType.TICKET and not entity.parent_ids:
                errors.append(f"Ticket {entity.id} has no User Story or Scope parent")
        
        # Check for cycles
        cycles = self._find_cycles()
        for cycle in cycles:
            errors.append(f"Cycle detected: {' -> '.join(cycle)} -> {cycle[0]}")
        
        return errors

    def _find_cycles(self) -> List[List[str]]:
        """Find cycles in the traceability graph."""
        visited = set()
        rec_stack = set()
        cycles = []
        path = []
        
        def dfs(node: str):
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            for cid in self._entities.get(node, TraceabilityEntity(id="", type=EntityType.SCOPE, title="")).child_ids:
                if cid not in self._entities:
                    continue
                if cid not in visited:
                    dfs(cid)
                elif cid in rec_stack:
                    cycle_start = path.index(cid)
                    cycle = path[cycle_start:] + [cid]
                    if cycle not in cycles:
                        cycles.append(cycle)
            
            rec_stack.remove(node)
            path.pop()
        
        for eid in self._entities:
            if eid not in visited:
                dfs(eid)
        
        return cycles

    def generate_markdown(self) -> str:
        """Generate TRACEABILITY.md report."""
        lines = ["# Traceability Matrix\n"]
        
        # Group by type
        scopes = [e for e in self._entities.values() if e.type == EntityType.SCOPE]
        stories = [e for e in self._entities.values() if e.type == EntityType.USER_STORY]
        tickets = [e for e in self._entities.values() if e.type == EntityType.TICKET]
        
        # Scopes
        lines.append("## Scopes\n")
        for s in sorted(scopes, key=lambda x: x.id):
            lines.append(f"### {s.id}: {s.title}")
            if s.description:
                lines.append(f"{s.description}")
            lines.append(f"**User Stories:** {', '.join(s.child_ids) if s.child_ids else 'None'}")
            lines.append(f"**Status:** {s.status}")
            lines.append("")
        
        # User Stories
        lines.append("## User Stories\n")
        for us in sorted(stories, key=lambda x: x.id):
            lines.append(f"### {us.id}: {us.title}")
            if us.description:
                lines.append(f"{us.description}")
            scope_links = ", ".join(us.parent_ids) if us.parent_ids else "None"
            lines.append(f"**Scope:** {scope_links}")
            ticket_links = ", ".join(us.child_ids) if us.child_ids else "None"
            lines.append(f"**Tickets:** {ticket_links}")
            lines.append(f"**Status:** {us.status}")
            lines.append("")
        
        # Tickets
        lines.append("## Tickets\n")
        for t in sorted(tickets, key=lambda x: x.id):
            lines.append(f"### {t.id}: {t.title}")
            if t.description:
                lines.append(f"{t.description}")
            parent_links = ", ".join(t.parent_ids) if t.parent_ids else "None"
            lines.append(f"**Traces to:** {parent_links}")
            lines.append(f"**Status:** {t.status}")
            lines.append("")
        
        return "\n".join(lines)

    def list_entities(self, entity_type: EntityType = None) -> List[TraceabilityEntity]:
        """List all entities, optionally filtered by type."""
        if entity_type:
            return [e for e in self._entities.values() if e.type == entity_type]
        return list(self._entities.values())


def _entity_to_dict(entity: TraceabilityEntity) -> dict:
    """Convert entity to dict with serializable types."""
    d = asdict(entity)
    d["type"] = entity.type.value
    return d


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Traceability ID Manager")
    parser.add_argument("command", choices=[
        "create-scope", "create-story", "create-ticket",
        "get", "trace", "validate", "report", "list"
    ])
    parser.add_argument("--id", help="Entity ID")
    parser.add_argument("--title", help="Title")
    parser.add_argument("--description", help="Description")
    parser.add_argument("--scope", help="Scope ID(s), comma-separated")
    parser.add_argument("--story", help="User Story ID(s), comma-separated")
    parser.add_argument("--type", choices=["scope", "story", "ticket"], help="Entity type for list")
    
    parser.add_argument("--project-root",type=Path,default=Path.cwd())
    args = parser.parse_args()
    manager = TraceabilityManager(args.project_root)
    
    if args.command == "create-scope":
        if not args.title:
            print("--title required")
            return 1
        success, eid, err = manager.create_scope(args.title, args.description or "", args.id)
        if success:
            print(f"Created Scope: {eid}")
        else:
            print(f"Error: {err}")
            return 1
    
    elif args.command == "create-story":
        if not args.title:
            print("--title required")
            return 1
        scope_ids = [s.strip() for s in args.scope.split(",")] if args.scope else []
        success, eid, err = manager.create_user_story(args.title, args.description or "", scope_ids, args.id)
        if success:
            print(f"Created User Story: {eid}")
        else:
            print(f"Error: {err}")
            return 1
    
    elif args.command == "create-ticket":
        if not args.title:
            print("--title required")
            return 1
        story_ids = [s.strip() for s in args.story.split(",")] if args.story else []
        scope_ids = [s.strip() for s in args.scope.split(",")] if args.scope else []
        success, eid, err = manager.create_ticket(args.title, args.description or "", story_ids, scope_ids, args.id)
        if success:
            print(f"Created Ticket: {eid}")
        else:
            print(f"Error: {err}")
            return 1
    
    elif args.command == "get":
        if not args.id:
            print("--id required")
            return 1
        entity = manager.get_entity(args.id)
        if entity:
            print(json.dumps(_entity_to_dict(entity), indent=2, ensure_ascii=False))
        else:
            print(f"Entity {args.id} not found")
            return 1
    
    elif args.command == "trace":
        if not args.id:
            print("--id required")
            return 1
        trace = manager.get_full_trace(args.id)
        if trace:
            print(json.dumps({
                "entity": _entity_to_dict(trace["entity"]),
                "ancestors": [_entity_to_dict(a) for a in trace["ancestors"]],
                "descendants": [_entity_to_dict(d) for d in trace["descendants"]]
            }, indent=2, ensure_ascii=False))
        else:
            print(f"Entity {args.id} not found")
            return 1
    
    elif args.command == "validate":
        errors = manager.validate_all()
        if errors:
            print("Validation errors:")
            for err in errors:
                print(f"  - {err}")
            return 1
        else:
            print("All traceability rules valid")
    
    elif args.command == "report":
        print(manager.generate_markdown())
    
    elif args.command == "list":
        etype = None
        if args.type == "scope":
            etype = EntityType.SCOPE
        elif args.type == "story":
            etype = EntityType.USER_STORY
        elif args.type == "ticket":
            etype = EntityType.TICKET
        
        entities = manager.list_entities(etype)
        for e in sorted(entities, key=lambda x: x.id):
            parents = ", ".join(e.parent_ids) if e.parent_ids else "None"
            print(f"{e.id} [{e.type.value}]: {e.title} (parents: {parents})")


if __name__ == "__main__":
    import sys
    sys.exit(main())