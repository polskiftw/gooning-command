from __future__ import annotations

from collections.abc import Iterable

from .evidence_store import EvidenceEdge, EvidenceStore


QUALIFICATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS edge_qualification (
    left_key TEXT NOT NULL,
    right_key TEXT NOT NULL,
    first_qualified_slider INTEGER NOT NULL,
    PRIMARY KEY (left_key, right_key),
    CHECK (left_key < right_key),
    CHECK (first_qualified_slider BETWEEN 0 AND 99)
);
CREATE INDEX IF NOT EXISTS edge_qualification_slider_idx
    ON edge_qualification(first_qualified_slider DESC);
"""


def ensure_qualification_schema(evidence: EvidenceStore) -> None:
    with evidence._lock, evidence.connection:  # same store-level transaction discipline
        evidence.connection.executescript(QUALIFICATION_SCHEMA)


def mark_edges_qualified(
    evidence: EvidenceStore,
    edges: Iterable[EvidenceEdge],
    strictest_slider: int,
) -> int:
    """Record the strictest certified slider at which each edge qualifies.

    Progressive indexing moves from 99 toward 0. Once an edge is discovered, it
    remains valid at every looser position. Repeated scans therefore retain the
    greatest (strictest) qualification value ever certified for that edge.
    """
    ensure_qualification_schema(evidence)
    slider = max(0, min(99, int(strictest_slider)))
    normalized = [edge.normalized() for edge in edges]
    if not normalized:
        return 0
    rows = {(edge.left_key, edge.right_key, slider) for edge in normalized}
    with evidence._lock, evidence.connection:
        evidence.connection.executemany(
            """
            INSERT INTO edge_qualification
                (left_key, right_key, first_qualified_slider)
            VALUES (?, ?, ?)
            ON CONFLICT(left_key, right_key) DO UPDATE SET
                first_qualified_slider = MAX(
                    edge_qualification.first_qualified_slider,
                    excluded.first_qualified_slider
                )
            """,
            rows,
        )
    return len(rows)


def qualified_edge_rows(evidence: EvidenceStore, slider: int):
    """Return only edges certified for the requested slider position."""
    ensure_qualification_schema(evidence)
    value = max(0, min(99, int(slider)))
    with evidence._lock:
        return evidence.connection.execute(
            """
            SELECT e.*, q.first_qualified_slider
            FROM comparison_edges e
            JOIN edge_qualification q
              ON q.left_key = e.left_key AND q.right_key = e.right_key
            WHERE q.first_qualified_slider >= ?
            ORDER BY e.left_key, e.right_key
            """,
            (value,),
        ).fetchall()
