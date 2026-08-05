from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .evidence_qualification import qualified_edge_rows
from .evidence_store import EvidenceStore
from .frontier_worker import FrontierCancelled, FrontierResult, scan_closed_group
from .group_closure import ensure_closure_schema, ready_group_members
from .models import Asset


@dataclass(frozen=True)
class GroupScheduleResult:
    slider: int
    groups_completed: int
    assets_completed: int
    comparisons: int
    edges_written: int


GroupProgress = Callable[[FrontierResult, int], None]


def _candidate_seed_keys(evidence: EvidenceStore, slider: int) -> list[str]:
    keys: set[str] = set()
    for row in qualified_edge_rows(evidence, slider):
        keys.add(str(row["left_key"]))
        keys.add(str(row["right_key"]))
    return sorted(keys)


def _covered_keys(evidence: EvidenceStore, slider: int) -> set[str]:
    ensure_closure_schema(evidence)
    fingerprint = evidence.get_state("inventory_fingerprint")
    if not fingerprint:
        return set()
    with evidence._lock:
        rows = evidence.connection.execute(
            """
            SELECT asset_key
            FROM asset_frontier_coverage
            WHERE slider = ? AND inventory_fingerprint = ?
            """,
            (max(0, min(99, int(slider))), fingerprint),
        ).fetchall()
    return {str(row["asset_key"]) for row in rows}


def run_group_seed_schedule(
    evidence: EvidenceStore,
    assets: Iterable[Asset],
    slider: int,
    *,
    cancelled: Callable[[], bool] | None = None,
    progress: GroupProgress | None = None,
) -> GroupScheduleResult:
    """Close duplicate components one at a time and resume safely.

    Seeds come from already-qualified matcher evidence. Each seed invokes the
    frontier worker, which expands through every newly discovered neighbor and
    certifies only after all member frontiers are exhausted. Assets already
    covered for the current inventory snapshot are skipped on resume.
    """
    value = max(0, min(99, int(slider)))
    is_cancelled = cancelled or (lambda: False)
    materialized = [asset for asset in assets if not asset.deleted]
    live_keys = {asset.key for asset in materialized}
    seeds = [key for key in _candidate_seed_keys(evidence, value) if key in live_keys]

    covered = _covered_keys(evidence, value)
    completed_groups = 0
    completed_assets = 0
    comparisons = 0
    edges_written = 0

    evidence.set_state("group_schedule_slider", str(value))
    evidence.set_state("group_schedule_status", "running")

    for seed in seeds:
        if is_cancelled():
            evidence.set_state("group_schedule_status", "cancelled")
            raise FrontierCancelled()
        if seed in covered:
            continue

        evidence.set_state("group_schedule_active_seed", seed)
        result = scan_closed_group(
            evidence,
            materialized,
            seed,
            value,
            cancelled=is_cancelled,
        )
        newly_covered = set(result.members) - covered
        covered.update(result.members)
        completed_assets += len(newly_covered)
        comparisons += result.compared_assets
        edges_written += result.edges_written
        if result.group is not None:
            completed_groups += 1
        if progress is not None:
            progress(result, len(seeds))

    evidence.set_state("group_schedule_status", "complete")
    evidence.set_state("group_schedule_active_seed", "")
    return GroupScheduleResult(
        slider=value,
        groups_completed=completed_groups,
        assets_completed=completed_assets,
        comparisons=comparisons,
        edges_written=edges_written,
    )
