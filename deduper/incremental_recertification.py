from __future__ import annotations

from collections.abc import Iterable

from .evidence_store import EvidenceStore
from .group_closure import certify_closed_groups, ensure_closure_schema, invalidate_closure_for_assets


def carry_forward_after_removals(
    evidence: EvidenceStore,
    removed_keys: Iterable[str],
    *,
    old_fingerprint: str | None,
    old_boundary: int | None,
    new_fingerprint: str,
) -> int:
    """Carry unaffected closure proof to a removal-only inventory snapshot.

    Removing assets cannot introduce a new comparison edge. READY groups touched
    by a removed member are invalidated, while surviving frontier coverage can be
    promoted to the new inventory fingerprint. Components affected by removals are
    then recertified from their surviving qualified edges.

    Additions and replacements must never use this shortcut because they can add
    new edges to any existing group.
    """
    keys = sorted(set(removed_keys))
    if not keys or not old_fingerprint:
        return 0

    ensure_closure_schema(evidence)
    invalidate_closure_for_assets(evidence, keys)

    with evidence._lock, evidence.connection:
        coverage_rows = evidence.connection.execute(
            """
            SELECT DISTINCT slider
            FROM asset_frontier_coverage
            WHERE inventory_fingerprint = ?
            ORDER BY slider DESC
            """,
            (old_fingerprint,),
        ).fetchall()
        sliders = [int(row["slider"]) for row in coverage_rows]

        evidence.connection.execute(
            """
            UPDATE asset_frontier_coverage
            SET inventory_fingerprint = ?, completed_at = CURRENT_TIMESTAMP
            WHERE inventory_fingerprint = ?
              AND asset_key NOT IN (
                  SELECT key FROM inventory_snapshot WHERE key NOT IN (
                      SELECT key FROM inventory_snapshot
                  )
              )
            """,
            (new_fingerprint, old_fingerprint),
        )
        # The subquery above intentionally reduces to the rows that survived the
        # snapshot replacement. Clean up any stale coverage defensively.
        evidence.connection.execute(
            """
            DELETE FROM asset_frontier_coverage
            WHERE asset_key NOT IN (SELECT key FROM inventory_snapshot)
            """
        )
        evidence.connection.execute(
            """
            UPDATE ready_groups
            SET inventory_fingerprint = ?, certified_at = CURRENT_TIMESTAMP
            WHERE inventory_fingerprint = ?
            """,
            (new_fingerprint, old_fingerprint),
        )

    rebuilt = 0
    for slider in sliders:
        rebuilt += len(certify_closed_groups(evidence, slider))

    if old_boundary is not None:
        evidence.set_state("loosest_complete_slider", str(old_boundary))
        evidence.set_state("build_status", "complete" if old_boundary == 0 else "building")
    return rebuilt
