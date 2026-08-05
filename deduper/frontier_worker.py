from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .edge_rules import edge_qualifies
from .evidence_capture import evidence_for_pairs
from .evidence_qualification import mark_edges_qualified
from .evidence_store import EvidenceEdge, EvidenceStore
from .group_closure import ClosedGroup, certify_closed_groups, mark_frontier_complete
from .models import Asset


class FrontierCancelled(Exception):
    """Raised before the active asset receives frontier-complete certification."""


@dataclass(frozen=True)
class FrontierResult:
    seed_key: str
    slider: int
    members: tuple[str, ...]
    compared_assets: int
    edges_written: int
    group: ClosedGroup | None


def qualifying_edge(left: Asset, right: Asset, slider: int) -> EvidenceEdge | None:
    """Measure and qualify one asset pair using the production matcher rules."""
    measured = evidence_for_pairs(
        [left, right],
        [(left.key, right.key, 0.0, "frontier measurement")],
        slider,
    )
    if not measured:
        return None
    edge = measured[0]
    return edge if edge_qualifies(edge, slider) else None


def scan_closed_group(
    evidence: EvidenceStore,
    assets: Iterable[Asset],
    seed_key: str,
    slider: int,
    *,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[str, int, int], None] | None = None,
) -> FrontierResult:
    """Exhaust one connected component and publish it as soon as it is closed.

    Every dequeued member is compared against the entire current live inventory.
    Newly qualifying neighbors are appended to the frontier. A member receives
    coverage proof only after all comparisons complete, so cancellation cannot
    falsely close the component.
    """
    value = max(0, min(99, int(slider)))
    is_cancelled = cancelled or (lambda: False)
    materialized = [asset for asset in assets if not asset.deleted]
    by_key = {asset.key: asset for asset in materialized}
    if seed_key not in by_key:
        raise KeyError(f"seed asset is not live and hashed: {seed_key}")

    frontier = deque([seed_key])
    members = {seed_key}
    completed: set[str] = set()
    compared = 0
    written = 0

    while frontier:
        if is_cancelled():
            raise FrontierCancelled()
        current_key = frontier.popleft()
        if current_key in completed:
            continue
        current = by_key[current_key]
        found_edges: list[EvidenceEdge] = []

        for index, other in enumerate(materialized, 1):
            if is_cancelled():
                raise FrontierCancelled()
            if other.key == current_key:
                continue
            compared += 1
            edge = qualifying_edge(current, other, value)
            if edge is not None:
                found_edges.append(edge)
                if other.key not in members:
                    members.add(other.key)
                    frontier.append(other.key)
            if progress is not None:
                progress(current_key, index, len(materialized))

        written += evidence.upsert_edges(found_edges)
        mark_edges_qualified(evidence, found_edges, value)
        mark_frontier_complete(evidence, [current_key], value)
        completed.add(current_key)

    certified = certify_closed_groups(evidence, value)
    group = next((item for item in certified if seed_key in item.members), None)
    return FrontierResult(
        seed_key=seed_key,
        slider=value,
        members=tuple(sorted(members)),
        compared_assets=compared,
        edges_written=written,
        group=group,
    )
