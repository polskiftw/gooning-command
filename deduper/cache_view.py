from __future__ import annotations

from collections.abc import Iterable

from .evidence_qualification import qualified_edge_rows
from .evidence_store import EvidenceStore
from .group_closure import ready_group_members
from .models import Asset
from .survivor_orientation import orient_duplicate_groups
from .survivor_policy import SurvivorPolicy


def _edge_score_and_reason(row) -> tuple[float, str]:
    scores: list[tuple[float, str]] = []
    if row["phash_distance"] is not None:
        distance = int(row["phash_distance"])
        scores.append((100 * (1 - distance / 64), f"pHash distance {distance}"))
    if row["pdq_distance"] is not None:
        distance = int(row["pdq_distance"])
        scores.append((100 * (1 - distance / 256), f"PDQ distance {distance}"))
    if row["crop_similarity"] is not None:
        score = float(row["crop_similarity"])
        scores.append((score, f"crop overlap {score:.0f}%"))
    if (
        row["vpdq_left_similarity"] is not None
        and row["vpdq_right_similarity"] is not None
    ):
        left = float(row["vpdq_left_similarity"])
        right = float(row["vpdq_right_similarity"])
        score = 100 * min(left, right)
        scores.append((score, f"vPDQ frames {left:.0%} / {right:.0%}"))
    if not scores:
        return 0.0, "certified cached match"
    score, strongest = max(scores, key=lambda item: item[0])
    details = ", ".join(reason for _, reason in scores)
    return round(min(100.0, score), 2), f"certified cache: {details}; strongest {strongest}"


def _pairs_from_qualified_edges(
    evidence: EvidenceStore,
    assets: Iterable[Asset],
    slider: int,
    *,
    allowed_keys: set[str] | None = None,
    survivor_policy: SurvivorPolicy = SurvivorPolicy.BALANCED,
) -> list[tuple[str, str, float, str]]:
    materialized = list(assets)
    live_keys = {asset.key for asset in materialized if not asset.deleted}
    if allowed_keys is not None:
        live_keys &= allowed_keys

    candidates: dict[tuple[str, str], tuple[float, str]] = {}
    for row in qualified_edge_rows(evidence, slider):
        left = str(row["left_key"])
        right = str(row["right_key"])
        if left not in live_keys or right not in live_keys:
            continue
        score, reason = _edge_score_and_reason(row)
        candidates[(left, right)] = (score, reason)

    eligible_assets = [asset for asset in materialized if asset.key in live_keys]
    return orient_duplicate_groups(eligible_assets, candidates, survivor_policy)


def ready_pairs_for_slider(
    evidence: EvidenceStore,
    assets: Iterable[Asset],
    slider: int,
    *,
    survivor_policy: SurvivorPolicy = SurvivorPolicy.BALANCED,
) -> list[tuple[str, str, float, str]]:
    """Build review pairs only from individually certified READY groups.

    Unlike the complete-range view, this is valid while the wider slider band is
    still running. Every included asset belongs to a component whose full live-
    inventory frontier has been exhausted at this slider and current inventory.
    """
    value = max(0, min(99, int(slider)))
    members = ready_group_members(evidence, value)
    if not members:
        return []
    return _pairs_from_qualified_edges(
        evidence,
        assets,
        value,
        allowed_keys=members,
        survivor_policy=survivor_policy,
    )


def cached_pairs_for_slider(
    evidence: EvidenceStore,
    assets: Iterable[Asset],
    slider: int,
    *,
    survivor_policy: SurvivorPolicy = SurvivorPolicy.BALANCED,
) -> list[tuple[str, str, float, str]]:
    """Build stable oriented review pairs from the complete cached range.

    The requested slider must be inside the completely indexed range. Rows from
    the legacy observation writer have no qualification record and are excluded.
    """
    value = max(0, min(99, int(slider)))
    boundary = evidence.loosest_complete_slider()
    if boundary is None:
        raise ValueError("no slider positions are certified yet")
    if value < boundary:
        raise ValueError(
            f"slider {value} is not certified; loosest available position is {boundary}"
        )

    return _pairs_from_qualified_edges(
        evidence,
        assets,
        value,
        survivor_policy=survivor_policy,
    )
