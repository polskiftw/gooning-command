from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .generation_builder import CertifiedPairRow, GenerationBuildPayload, ShaDeletionRow


@dataclass(frozen=True)
class CertifiedFamily:
    """One fully closed family admitted to preview during an active scan."""

    group_id: str
    members: tuple[str, ...]
    pairs: tuple[CertifiedPairRow, ...]


class CertifiedQueue:
    """Growing preview queue of individually final certified families.

    Admission freezes family membership and pair orientation. Later admissions may
    change only numerical queue positions because the whole visible queue is always
    re-sorted by the existing lowest-to-highest similarity percentage rule.
    """

    def __init__(self) -> None:
        self._families: dict[str, CertifiedFamily] = {}
        self._asset_family: dict[str, str] = {}
        self._sha_deletions: dict[str, ShaDeletionRow] = {}

    def admit_family(self, family: CertifiedFamily) -> bool:
        normalized = self._validate_family(family)
        existing = self._families.get(normalized.group_id)
        if existing is not None:
            if existing != normalized:
                raise ValueError(
                    f"certified family {normalized.group_id} cannot change after admission"
                )
            return False

        for member in normalized.members:
            other_group = self._asset_family.get(member)
            if other_group is not None:
                raise ValueError(
                    f"asset {member} is already certified in family {other_group}"
                )

        self._families[normalized.group_id] = normalized
        for member in normalized.members:
            self._asset_family[member] = normalized.group_id
        return True

    def admit_sha_deletions(self, rows: Iterable[ShaDeletionRow]) -> int:
        added = 0
        for row in rows:
            if row.survivor_key == row.deletion_key:
                raise ValueError("SHA survivor and deletion key must differ")
            existing = self._sha_deletions.get(row.deletion_key)
            if existing is not None:
                if existing != row:
                    raise ValueError(
                        f"SHA deletion {row.deletion_key} cannot change survivor after admission"
                    )
                continue
            self._sha_deletions[row.deletion_key] = row
            added += 1
        return added

    def pairs(self) -> tuple[CertifiedPairRow, ...]:
        rows = [row for family in self._families.values() for row in family.pairs]
        rows.sort(
            key=lambda row: (
                float(row.similarity),
                row.group_id,
                row.survivor_key,
                row.deletion_key,
            )
        )
        return tuple(rows)

    def payload(self) -> GenerationBuildPayload:
        sha_rows = tuple(
            sorted(
                self._sha_deletions.values(),
                key=lambda row: (row.survivor_key, row.deletion_key),
            )
        )
        return GenerationBuildPayload(self.pairs(), sha_rows)

    def family_count(self) -> int:
        return len(self._families)

    @staticmethod
    def _validate_family(family: CertifiedFamily) -> CertifiedFamily:
        members = tuple(sorted(set(family.members)))
        if len(members) < 2:
            raise ValueError("a certified family must contain at least two members")
        if not family.group_id:
            raise ValueError("certified family group_id is required")
        if not family.pairs:
            raise ValueError("a certified family must contain at least one preview pair")

        member_set = set(members)
        deletion_keys: set[str] = set()
        normalized_pairs: list[CertifiedPairRow] = []
        for row in family.pairs:
            if row.group_id != family.group_id:
                raise ValueError("all certified family pairs must use the family group_id")
            if row.survivor_key not in member_set or row.deletion_key not in member_set:
                raise ValueError("certified family pair references an asset outside the family")
            if row.survivor_key == row.deletion_key:
                raise ValueError("certified pair survivor and deletion key must differ")
            if row.deletion_key in deletion_keys:
                raise ValueError("a deletion candidate may appear only once in a certified family")
            deletion_keys.add(row.deletion_key)
            normalized_pairs.append(row)

        normalized_pairs.sort(
            key=lambda row: (
                float(row.similarity),
                row.survivor_key,
                row.deletion_key,
            )
        )
        return CertifiedFamily(family.group_id, members, tuple(normalized_pairs))
