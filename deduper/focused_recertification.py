from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .evidence_capture import evidence_for_pairs
from .evidence_qualification import mark_edges_qualified
from .evidence_store import EvidenceStore
from .focused_matcher import acquire_focused_pairs
from .group_closure import certify_closed_groups, ensure_closure_schema, mark_frontier_complete
from .models import Asset
from .progressive_indexer import index_bands


@dataclass(frozen=True)
class FocusedRecertificationResult:
    focus_assets: int
    bands_recertified: int
    edges_written: int
    groups_certified: int


def recertify_added_or_changed_assets(
    evidence: EvidenceStore,
    assets: Iterable[Asset],
    focus_keys: Iterable[str],
    *,
    old_fingerprint: str | None,
    old_boundary: int | None,
    new_fingerprint: str,
    cancelled: Callable[[], bool] | None = None,
) -> FocusedRecertificationResult | None:
    """Extend a completed old inventory proof to added/replaced assets.

    Every focus asset is exhaustively queried against the full current library at
    each previously completed matcher band. Old-old evidence remains valid.
    Unchanged frontier coverage is promoted to the new inventory fingerprint;
    focus assets receive fresh coverage only after their focused pass completes.
    READY groups are then rebuilt from the combined current-inventory proof.
    """
    materialized = [asset for asset in assets if not asset.deleted]
    live_keys = {asset.key for asset in materialized}
    focus = sorted(set(focus_keys) & live_keys)
    if not focus or not old_fingerprint or old_boundary is None:
        return None

    is_cancelled = cancelled or (lambda: False)
    ensure_closure_schema(evidence)

    # Promote only unchanged surviving assets. Changed assets are in focus and
    # must earn fresh frontier coverage from the focused matcher below.
    placeholders = ",".join("?" for _ in focus)
    with evidence._lock, evidence.connection:
        if focus:
            evidence.connection.execute(
                f"""
                UPDATE asset_frontier_coverage
                SET inventory_fingerprint = ?, completed_at = CURRENT_TIMESTAMP
                WHERE inventory_fingerprint = ?
                  AND asset_key NOT IN ({placeholders})
                  AND asset_key IN (SELECT key FROM inventory_snapshot)
                """,
                (new_fingerprint, old_fingerprint, *focus),
            )
        evidence.connection.execute("DELETE FROM ready_groups")

    bands = [band for band in index_bands() if band.loosest_slider >= old_boundary]
    edges_written = 0
    groups_certified = 0
    completed_bands = 0

    for band in bands:
        if is_cancelled():
            return None
        pairs = acquire_focused_pairs(
            materialized,
            focus,
            band.loosest_slider,
            cancelled=is_cancelled,
        )
        edges = evidence_for_pairs(materialized, pairs, band.loosest_slider)
        edges_written += evidence.upsert_edges(edges)
        mark_edges_qualified(evidence, edges, band.strictest_slider)
        mark_frontier_complete(evidence, focus, band.loosest_slider)
        groups_certified += len(certify_closed_groups(evidence, band.loosest_slider))
        completed_bands += 1

    evidence.set_state("loosest_complete_slider", str(old_boundary))
    evidence.set_state("build_status", "complete" if old_boundary == 0 else "building")
    evidence.set_state("incremental_mode", "focused_added_or_changed")
    return FocusedRecertificationResult(
        focus_assets=len(focus),
        bands_recertified=completed_bands,
        edges_written=edges_written,
        groups_certified=groups_certified,
    )
