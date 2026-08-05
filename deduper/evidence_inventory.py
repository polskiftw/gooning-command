from __future__ import annotations

from collections.abc import Iterable

from .evidence_store import EvidenceStore, InventoryRecord
from .evidence_sync import ReconcileResult, reconcile_inventory
from .models import Asset


def inventory_records_from_assets(assets: Iterable[Asset]) -> list[InventoryRecord]:
    """Convert one complete storage listing into stable cache identity records."""
    return [
        InventoryRecord(
            key=asset.key,
            size=int(asset.size),
            etag=asset.etag or "",
            last_modified=asset.last_modified or "",
        )
        for asset in assets
    ]


def reconcile_asset_inventory(
    evidence: EvidenceStore,
    assets: Iterable[Asset],
) -> ReconcileResult:
    """Synchronize the evidence cache snapshot with a complete storage listing."""
    return reconcile_inventory(evidence, inventory_records_from_assets(assets))
