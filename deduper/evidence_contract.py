from __future__ import annotations

from .evidence_store import EvidenceStore


EVIDENCE_CONTRACT_VERSION = 2


def enforce_evidence_contract(evidence: EvidenceStore) -> bool:
    """Discard certification produced by an incompatible qualification contract.

    Version 2 removes the historical crop-overlap bypass. Raw and certified edge
    rows are cleared together so no old 60%-overlap relationship can survive as
    a READY component. The inventory snapshot remains, allowing the next scan to
    rebuild safely without redownloading already stored hashes.
    """
    current = evidence.get_state("evidence_contract_version")
    if current == str(EVIDENCE_CONTRACT_VERSION):
        return False

    with evidence._lock, evidence.connection:
        for table in (
            "ready_group_members",
            "ready_groups",
            "asset_frontier_coverage",
            "edge_qualification",
            "comparison_edges",
        ):
            evidence.connection.execute(f"DELETE FROM {table}")
        evidence.connection.execute(
            """
            INSERT INTO cache_state (key, value) VALUES
                ('evidence_contract_version', ?),
                ('loosest_complete_slider', '100'),
                ('build_status', 'empty')
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(EVIDENCE_CONTRACT_VERSION),),
        )
    return True
