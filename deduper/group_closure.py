from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass

from .evidence_qualification import qualified_edge_rows
from .evidence_store import EvidenceStore


CLOSURE_SCHEMA = """
CREATE TABLE IF NOT EXISTS asset_frontier_coverage (
    asset_key TEXT NOT NULL,
    slider INTEGER NOT NULL,
    inventory_fingerprint TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (asset_key, slider)
);

CREATE TABLE IF NOT EXISTS ready_groups (
    group_id TEXT NOT NULL,
    slider INTEGER NOT NULL,
    inventory_fingerprint TEXT NOT NULL,
    member_count INTEGER NOT NULL,
    certified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (group_id, slider)
);

CREATE TABLE IF NOT EXISTS ready_group_members (
    group_id TEXT NOT NULL,
    slider INTEGER NOT NULL,
    asset_key TEXT NOT NULL,
    PRIMARY KEY (group_id, slider, asset_key),
    FOREIGN KEY (group_id, slider)
        REFERENCES ready_groups(group_id, slider)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS asset_frontier_coverage_slider_idx
    ON asset_frontier_coverage(slider, inventory_fingerprint);
CREATE INDEX IF NOT EXISTS ready_group_members_asset_idx
    ON ready_group_members(asset_key, slider);
"""


@dataclass(frozen=True)
class ClosedGroup:
    group_id: str
    slider: int
    members: tuple[str, ...]


def ensure_closure_schema(evidence: EvidenceStore) -> None:
    with evidence._lock, evidence.connection:
        evidence.connection.executescript(CLOSURE_SCHEMA)


def _inventory_identity(evidence: EvidenceStore) -> str:
    value = evidence.get_state("inventory_fingerprint")
    if not value:
        raise ValueError("inventory snapshot has not been synchronized")
    return value


def _group_id(members: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for key in sorted(set(members)):
        encoded = key.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def mark_frontier_complete(
    evidence: EvidenceStore,
    asset_keys: Iterable[str],
    slider: int,
) -> int:
    """Record that each asset's complete candidate frontier was exhausted."""
    ensure_closure_schema(evidence)
    value = max(0, min(99, int(slider)))
    fingerprint = _inventory_identity(evidence)
    keys = sorted(set(asset_keys))
    if not keys:
        return 0
    with evidence._lock, evidence.connection:
        evidence.connection.executemany(
            """
            INSERT INTO asset_frontier_coverage
                (asset_key, slider, inventory_fingerprint)
            VALUES (?, ?, ?)
            ON CONFLICT(asset_key, slider) DO UPDATE SET
                inventory_fingerprint = excluded.inventory_fingerprint,
                completed_at = CURRENT_TIMESTAMP
            """,
            ((key, value, fingerprint) for key in keys),
        )
    return len(keys)


def invalidate_closure_for_assets(
    evidence: EvidenceStore,
    asset_keys: Iterable[str],
) -> None:
    """Remove coverage and READY groups touched by changed/deleted assets."""
    ensure_closure_schema(evidence)
    keys = sorted(set(asset_keys))
    if not keys:
        return
    placeholders = ",".join("?" for _ in keys)
    with evidence._lock, evidence.connection:
        groups = evidence.connection.execute(
            f"""
            SELECT DISTINCT group_id, slider
            FROM ready_group_members
            WHERE asset_key IN ({placeholders})
            """,
            tuple(keys),
        ).fetchall()
        evidence.connection.execute(
            f"DELETE FROM asset_frontier_coverage WHERE asset_key IN ({placeholders})",
            tuple(keys),
        )
        evidence.connection.executemany(
            "DELETE FROM ready_groups WHERE group_id = ? AND slider = ?",
            ((row["group_id"], int(row["slider"])) for row in groups),
        )


def _components(evidence: EvidenceStore, slider: int) -> list[set[str]]:
    neighbors: dict[str, set[str]] = defaultdict(set)
    for row in qualified_edge_rows(evidence, slider):
        left = str(row["left_key"])
        right = str(row["right_key"])
        neighbors[left].add(right)
        neighbors[right].add(left)

    remaining = set(neighbors)
    components: list[set[str]] = []
    while remaining:
        root = remaining.pop()
        component = {root}
        queue = deque([root])
        while queue:
            current = queue.popleft()
            for other in neighbors[current]:
                if other in component:
                    continue
                component.add(other)
                remaining.discard(other)
                queue.append(other)
        components.append(component)
    return components


def certify_closed_groups(evidence: EvidenceStore, slider: int) -> list[ClosedGroup]:
    """Publish components whose members all have current-inventory frontier proof.

    This intentionally does not require the whole slider band to be complete.
    Per-group closure is the safety proof; the band boundary remains a separate
    whole-library completeness signal.
    """
    ensure_closure_schema(evidence)
    value = max(0, min(99, int(slider)))
    fingerprint = _inventory_identity(evidence)

    with evidence._lock:
        rows = evidence.connection.execute(
            """
            SELECT asset_key
            FROM asset_frontier_coverage
            WHERE slider = ? AND inventory_fingerprint = ?
            """,
            (value, fingerprint),
        ).fetchall()
    covered = {str(row["asset_key"]) for row in rows}

    certified: list[ClosedGroup] = []
    for component in _components(evidence, value):
        if not component.issubset(covered):
            continue
        members = tuple(sorted(component))
        group = ClosedGroup(_group_id(members), value, members)
        with evidence._lock, evidence.connection:
            evidence.connection.execute(
                """
                INSERT INTO ready_groups
                    (group_id, slider, inventory_fingerprint, member_count)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(group_id, slider) DO UPDATE SET
                    inventory_fingerprint = excluded.inventory_fingerprint,
                    member_count = excluded.member_count,
                    certified_at = CURRENT_TIMESTAMP
                """,
                (group.group_id, value, fingerprint, len(members)),
            )
            evidence.connection.execute(
                "DELETE FROM ready_group_members WHERE group_id = ? AND slider = ?",
                (group.group_id, value),
            )
            evidence.connection.executemany(
                """
                INSERT INTO ready_group_members (group_id, slider, asset_key)
                VALUES (?, ?, ?)
                """,
                ((group.group_id, value, key) for key in members),
            )
        certified.append(group)
    return certified


def ready_group_members(evidence: EvidenceStore, slider: int) -> set[str]:
    ensure_closure_schema(evidence)
    fingerprint = _inventory_identity(evidence)
    with evidence._lock:
        rows = evidence.connection.execute(
            """
            SELECT m.asset_key
            FROM ready_group_members m
            JOIN ready_groups g
              ON g.group_id = m.group_id AND g.slider = m.slider
            WHERE m.slider = ? AND g.inventory_fingerprint = ?
            """,
            (max(0, min(99, int(slider))), fingerprint),
        ).fetchall()
    return {str(row["asset_key"]) for row in rows}
