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


@dataclass(frozen=True)
class FamilyInvalidation:
    """Family-wide result produced after one certified member is deleted."""

    family: CertifiedFamily
    deleted_key: str
    protected_key: str
    recertify_keys: tuple[str, ...]


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

    def family_for_asset(self, asset_key: str) -> CertifiedFamily | None:
        group_id = self._asset_family.get(asset_key)
        return self._families.get(group_id) if group_id is not None else None

    def family_for_pair(self, left_key: str, right_key: str) -> CertifiedFamily | None:
        left_family = self.family_for_asset(left_key)
        right_family = self.family_for_asset(right_key)
        if left_family is None or right_family is None:
            return None
        if left_family.group_id != right_family.group_id:
            raise ValueError("visible pair members do not belong to the same certified family")
        return left_family

    def invalidate_for_deletion(
        self,
        deleted_key: str,
        protected_key: str,
    ) -> FamilyInvalidation:
        """Remove the whole certified family after one selected member is deleted.

        Every preview row from that family disappears immediately. All still-live
        family members, led by the explicitly protected opposite side, are returned
        in deterministic recertification priority order.
        """
        family = self.family_for_asset(deleted_key)
        if family is None:
            raise KeyError(f"asset {deleted_key} is not in a certified family")
        if protected_key == deleted_key:
            raise ValueError("deleted and protected keys must differ")
        if protected_key not in family.members:
            raise ValueError("protected key must belong to the same certified family")

        self._families.pop(family.group_id, None)
        for member in family.members:
            self._asset_family.pop(member, None)

        surviving = [member for member in family.members if member != deleted_key]
        recertify = tuple(
            [protected_key]
            + sorted(member for member in surviving if member != protected_key)
        )
        return FamilyInvalidation(
            family=family,
            deleted_key=deleted_key,
            protected_key=protected_key,
            recertify_keys=recertify,
        )

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
