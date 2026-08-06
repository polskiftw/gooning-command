from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .cache_view import ready_pairs_for_slider
from .certified_queue import CertifiedFamily, CertifiedQueue
from .frontier_worker import FrontierResult
from .generation_builder import CertifiedPairRow
from .evidence_store import EvidenceStore
from .models import Asset


@dataclass(frozen=True)
class AdmissionResult:
    admitted: bool
    family_count: int
    pair_count: int


def admit_closed_frontier_group(
    queue: CertifiedQueue,
    evidence: EvidenceStore,
    assets: Iterable[Asset],
    result: FrontierResult,
) -> AdmissionResult:
    """Admit one completely closed family and never an unfinished frontier.

    `FrontierResult.group` is the closure proof. A result without that proof is
    intentionally ignored, even when it already contains discovered members or
    qualifying edges. Queue position may later change through percentage sorting;
    family membership and pair orientation may not.
    """
    if result.group is None:
        return AdmissionResult(False, queue.family_count(), len(queue.pairs()))

    group = result.group
    member_keys = set(group.members)
    ready_pairs = ready_pairs_for_slider(evidence, assets, group.slider)
    family_rows = tuple(
        CertifiedPairRow(
            group_id=group.group_id,
            survivor_key=survivor,
            deletion_key=deletion,
            similarity=float(similarity),
            reason=reason,
        )
        for survivor, deletion, similarity, reason in ready_pairs
        if survivor in member_keys and deletion in member_keys
    )
    if not family_rows:
        raise ValueError(
            f"closed family {group.group_id} produced no actionable preview pairs"
        )

    admitted = queue.admit_family(
        CertifiedFamily(
            group_id=group.group_id,
            members=tuple(group.members),
            pairs=family_rows,
        )
    )
    return AdmissionResult(admitted, queue.family_count(), len(queue.pairs()))


def preview_projection(
    queue: CertifiedQueue,
) -> list[tuple[str, str, float, str]]:
    """Return the existing UI projection in lowest-to-highest percentage order."""
    return [
        (row.survivor_key, row.deletion_key, row.similarity, row.reason)
        for row in queue.pairs()
    ]
