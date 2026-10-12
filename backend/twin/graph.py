"""
twin/graph.py — Digital twin graph: parent/child entity relationships.

The graph is a simple directed acyclic graph (DAG) stored as an adjacency
list. The AHU is the root; fans, coils, filter, damper are children;
motor/bearings/belt are grandchildren.

This mirrors how real BMS asset models (Brick Schema, Project Haystack)
structure equipment hierarchies.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from .model import TwinEntity, OperatingState
from config import settings


class DigitalTwinGraph:
    """
    Directed acyclic graph of TwinEntity nodes.

    - Nodes are keyed by entity.id
    - Edges: parent_id → [child_ids]
    - Health rolls up bottom-to-top after each analytics pass
    """

    def __init__(self) -> None:
        self._nodes: dict[str, TwinEntity] = {}
        self._children: dict[str, list[str]] = defaultdict(list)
        self._root_id: Optional[str] = None

    # ── Graph construction ───────────────────────────────────────────────────

    def add_entity(self, entity: TwinEntity) -> None:
        """Add an entity to the graph. If it has a parent, register the edge."""
        self._nodes[entity.id] = entity
        if entity.parent_id is not None:
            self._children[entity.parent_id].append(entity.id)
        else:
            self._root_id = entity.id  # The AHU root

    # ── Accessors ────────────────────────────────────────────────────────────

    def get(self, entity_id: str) -> Optional[TwinEntity]:
        return self._nodes.get(entity_id)

    def all_entities(self) -> list[TwinEntity]:
        return list(self._nodes.values())

    def children_of(self, entity_id: str) -> list[TwinEntity]:
        return [self._nodes[cid] for cid in self._children.get(entity_id, []) if cid in self._nodes]

    def leaves(self) -> list[TwinEntity]:
        """Return entities with no children (sensor-bearing leaf nodes)."""
        return [e for e in self._nodes.values() if not self._children.get(e.id)]

    @property
    def root(self) -> Optional[TwinEntity]:
        return self._nodes.get(self._root_id) if self._root_id else None

    # ── Health roll-up ───────────────────────────────────────────────────────

    def rollup_health(self) -> None:
        """
        Bottom-up health roll-up across the graph.

        Leaf nodes: health already set by analytics engine from signal scores.
        Parent nodes: weighted average of direct children (weights from config).
        Root (AHU): weighted combination of top-level components.
        """
        self._rollup_recursive(self._root_id)

    def _rollup_recursive(self, entity_id: Optional[str]) -> float:
        """DFS post-order traversal; returns the entity's computed health value."""
        if entity_id is None:
            return 1.0

        entity = self._nodes.get(entity_id)
        if entity is None:
            return 1.0

        child_ids = self._children.get(entity_id, [])
        if not child_ids:
            # Leaf: health already set by analytics, just return it
            return entity.health.value

        # Recurse first (post-order)
        child_scores: list[tuple[TwinEntity, float]] = []
        for cid in child_ids:
            child_health = self._rollup_recursive(cid)
            child_entity = self._nodes[cid]
            child_scores.append((child_entity, child_health))

        # Weighted roll-up at this level
        weight_map = _component_weights()
        total_weight = 0.0
        weighted_sum = 0.0
        for child_entity, child_health in child_scores:
            w = weight_map.get(child_entity.id, 1.0 / len(child_scores))
            weighted_sum += w * child_health
            total_weight += w

        composite = weighted_sum / total_weight if total_weight > 0 else 1.0
        entity.health.value = composite
        entity.health.update_state(settings.health_warning_threshold, settings.health_critical_threshold)
        return composite

    # ── Serialisation ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Full graph serialisation for the /api/twin endpoint."""
        return {
            "root_id": self._root_id,
            "entities": {eid: e.to_dict() for eid, e in self._nodes.items()},
            "edges": {parent: children for parent, children in self._children.items()},
        }

    def health_summary(self) -> dict:
        """Compact health snapshot for polling/WebSocket."""
        return {
            eid: {
                "health": round(e.health.value, 4),
                "state": e.health.state.value,
                "fault": e.health.dominant_fault.value,
                "rul_days": round(e.health.rul_days, 1) if e.health.rul_days is not None else None,
            }
            for eid, e in self._nodes.items()
        }


def _component_weights() -> dict[str, float]:
    """
    Map entity IDs to their health contribution weight at the AHU level.
    Weights reflect operational criticality (supply fan most critical).
    """
    return {
        "ahu-01.supplyFan":   settings.weight_supply_fan,
        "ahu-01.coolingCoil": settings.weight_cooling_coil,
        "ahu-01.filterBank":  settings.weight_filter,
        "ahu-01.returnFan":   settings.weight_return_fan,
        "ahu-01.heatingCoil": settings.weight_heating_coil,
        "ahu-01.damper":      settings.weight_damper,
    }
