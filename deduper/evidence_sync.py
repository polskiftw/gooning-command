from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .evidence_store import EvidenceStore, InventoryRecord


@dataclass(frozen=True)
class InventoryDelta:
    added: frozenset[str]
    changed: frozenset[str]
    removed: frozenset[str]
    unchanged: frozenset[str]

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.changed or self.removed)


@dataclass(frozen=True)
class ReconcileResult:
    delta: InventoryDelta
    fingerprint: str
    cache_was_current: bool


def _identity(record: InventoryRecord) -> tuple[int, str, str]:
    return (int(record.size), record.etag or "", record.last_modified or "")


def inventory_delta(
    previous: Iterable[InventoryRecord],
    current: Iterable[InventoryRecord],
) -> InventoryDelta:
    old = {record.key: record for record in previous}
    new = {record.key: record for record in current}

    old_keys = set(old)
    new_keys = set(new)
    common = old_keys & new_keys
    changed = {key for key in common if _identity(old[key]) != _identity(new[key])}
    unchanged = common - changed
    return InventoryDelta(
        added=frozenset(new_keys - old_keys),
        changed=frozenset(changed),
        removed=frozenset(old_keys - new_keys),
        unchanged=frozenset(unchanged),
    )


def _stored_inventory(evidence: EvidenceStore) -> list[InventoryRecord]:
    with evidence._lock:
        rows = evidence.connection.execute(
            "SELECT key, size, etag, last_modified FROM inventory_snapshot ORDER BY key"
        ).fetchall()
    return [
        InventoryRecord(
            key=str(row["key"]),
            size=int(row["size"]),
            etag=str(row["etag"]),
            last_modified=str(row["last_modified"]),
        )
        for row in rows
    ]


def reconcile_inventory(
    evidence: EvidenceStore,
    current: Iterable[InventoryRecord],
) -> ReconcileResult:
    """Reconcile a complete storage listing with the durable evidence cache.

    Existing evidence for unchanged assets remains valid. Edges touching changed
    or removed assets are invalidated, while newly added assets begin with no
    edges. The inventory snapshot is replaced after invalidation.
    """
    materialized = list(current)
    previous = _stored_inventory(evidence)
    delta = inventory_delta(previous, materialized)
    cache_was_current = not delta.has_changes and evidence.inventory_matches(materialized)

    if delta.has_changes:
        for key in sorted(delta.changed | delta.removed):
            evidence.remove_asset(key)
        evidence.set_state("build_status", "dirty")
        evidence.set_state("loosest_complete_slider", "100")

    fingerprint = evidence.replace_inventory_snapshot(materialized)
    return ReconcileResult(
        delta=delta,
        fingerprint=fingerprint,
        cache_was_current=cache_was_current,
    )
