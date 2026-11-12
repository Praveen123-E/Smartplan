"""
Production Order lifecycle transition rules for PlantOps.

Centralizes valid state transitions so both the Order Service (Phase 5)
and the Validation Engine (Phase 4) enforce the exact same rules.
"""

from app.models.enums import OrderStatus


VALID_ORDER_TRANSITIONS: dict[str, set[str]] = {
    OrderStatus.DRAFT.value: {
        OrderStatus.RELEASED.value,
        OrderStatus.CANCELLED.value,
    },
    OrderStatus.RELEASED.value: {
        OrderStatus.PLANNED.value,
        OrderStatus.SCHEDULED.value,
        OrderStatus.INFEASIBLE.value,
        OrderStatus.CANCELLED.value,
    },
    OrderStatus.PLANNED.value: {
        OrderStatus.SCHEDULED.value,
        OrderStatus.INFEASIBLE.value,
        OrderStatus.CANCELLED.value,
    },
    OrderStatus.SCHEDULED.value: {
        OrderStatus.IN_PROGRESS.value,
        OrderStatus.DELAYED.value,
        OrderStatus.INFEASIBLE.value,
        OrderStatus.CANCELLED.value,
    },
    OrderStatus.IN_PROGRESS.value: {
        OrderStatus.COMPLETED.value,
        OrderStatus.DELAYED.value,
        OrderStatus.CANCELLED.value,
    },
    OrderStatus.DELAYED.value: {
        OrderStatus.SCHEDULED.value,
        OrderStatus.IN_PROGRESS.value,
        OrderStatus.COMPLETED.value,
        OrderStatus.CANCELLED.value,
    },
    OrderStatus.INFEASIBLE.value: {
        OrderStatus.RELEASED.value,
        OrderStatus.PLANNED.value,
        OrderStatus.SCHEDULED.value,
        OrderStatus.CANCELLED.value,
    },
    OrderStatus.COMPLETED.value: set(),
    OrderStatus.CANCELLED.value: set(),
}


def is_valid_order_transition(previous_state: str | None, new_state: str) -> bool:
    """Return True if transitioning from `previous_state` to `new_state` is allowed."""
    if previous_state is None or previous_state == new_state:
        return True
    allowed = VALID_ORDER_TRANSITIONS.get(previous_state, set())
    return new_state in allowed

