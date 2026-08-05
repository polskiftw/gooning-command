from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .evidence_capture import evidence_for_pairs
from .evidence_qualification import mark_edges_qualified
from .evidence_store import EvidenceEdge, EvidenceStore
from .group_closure import ClosedGroup, certify_closed_groups, mark_frontier_complete
from .matcher import thresholds
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


def _edge_qualifies(edge: EvidenceEdge, slider: int) -> bool:
    limits = thresholds(slider)
    minimum = float(limits["minimum_similarity"])

    phash_score = None
    if edge.phash_distance is not None:
        phash_score = 100 * (1 - int(edge.phash_distance) / 64)

    pdq_score = None
    if edge.pdq_distance is not None:
        pdq_score = 100 * (1 - int(edge.pdq_distance) / 256)

    crop_score = edge.crop_similarity
    vpdq_score = None
    if (
        edge.vpdq_left_similarity is not None
        and edge.vpdq_right_similarity is not None
    ):
        vpdq_score = 100 * min(
            float(edge.vpdq_left_similarity),
            float(edge.vpdq_right_similarity),
        )

    # This mirrors the existing matcher. A pHash candidate may qualify because
    # its secondary PDQ/crop evidence supplies the strongest score.
    if (
        edge.phash_distance is not None
        and int(edge.phash_distance) <= int(limits["phash"])
    ):
        strongest = max(
            score for score in (phash_score, pdq_score, crop_score) if score is not None
        )
        if strongest >= minimum:
            return True

    if (
        edge.pdq_distance is not None
        and int(edge.pdq_distance) <= int(limits["pdq"])
        and pdq_score is not None
        and pdq_score >= minimum
    ):
        return True

    # Crop-qualified pairs bypass minimum_similarity in the legacy matcher.
    if crop_score is not None and crop_score / 100 >= float(limits["crop_ratio"]):
        return True

    if (
        vpdq_score is not None
        and edge.vpdq_left_similarity is not None
        and edge.vpdq_right_similarity is not None
        and min(
            float(edge.vpdq_left_similarity),
            float(edge.vpdq_right_similarity),
        ) >= float(limits["vpdq_match"])
        and vpdq_score >= minimum
    ):
        return True

    return False


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
    return edge if _edge_qualifies(edge, slider) else None


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

        # Persist all edges and qualification before certifying this member's
        # complete frontier. Repeated comparisons are idempotent in both tables.
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
