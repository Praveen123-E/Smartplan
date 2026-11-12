"""
Audit Logging and State Change Traceability Service for PlantOps.

Provides simple helper functions so every service logs master-data edits,
order lifecycle changes, scheduling runs, and exception resolutions consistently.
"""

import json
from typing import Any
from sqlalchemy.orm import Session

from app.models.governance import AuditLog, StateChangeEvent


def _serialize(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)


def record_audit_log(
    db: Session,
    username: str,
    action: str,
    entity_type: str,
    entity_id: str,
    old_value: Any = None,
    new_value: Any = None,
    reason: str | None = None,
    user_id: str | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """Create an immutable `AuditLog` entry inside the current DB transaction."""
    entry = AuditLog(
        user_id=user_id,
        username=username,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=_serialize(old_value),
        new_value=_serialize(new_value),
        reason=reason,
        ip_address=ip_address,
    )
    db.add(entry)
    return entry


def record_state_change(
    db: Session,
    entity_type: str,
    entity_id: str,
    previous_state: str | None,
    new_state: str,
    changed_by: str,
    reason: str | None = None,
) -> StateChangeEvent:
    """Record an explicit lifecycle state transition in `state_change_events`."""
    event = StateChangeEvent(
        entity_type=entity_type,
        entity_id=entity_id,
        previous_state=previous_state,
        new_state=new_state,
        changed_by=changed_by,
        reason=reason,
    )
    db.add(event)
    return event

