from __future__ import annotations

from collections import defaultdict

from .models import Asset
from .survivor_policy import SurvivorPolicy, survivor_rank


PairResult = tuple[str, str, float, str]


def partition_exact_duplicates(
    assets: list[Asset],
    policy: SurvivorPolicy,
) -> tuple[list[Asset], list[tuple[str, str]]]:
    """Remove exact-SHA groups and choose their survivor under one policy."""
    groups: dict[str, list[Asset]] = defaultdict(list)
    for asset in assets:
        if asset.sha256:
            groups[asset.sha256].append(asset)

    withheld: set[str] = set()
    deletions: list[tuple[str, str]] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        survivor = max(group, key=lambda asset: survivor_rank(asset, policy))
        withheld.update(asset.key for asset in group)
        deletions.extend(
            (survivor.key, asset.key)
            for asset in group
            if asset.key != survivor.key
        )

    visual_assets = [asset for asset in assets if asset.key not in withheld]
    deletions.sort()
    return visual_assets, deletions


def orient_duplicate_groups(
    assets: list[Asset],
    candidates: dict[tuple[str, str], tuple[float, str]],
    policy: SurvivorPolicy,
) -> list[PairResult]:
    """Orient a complete candidate graph using the configured survivor policy."""
    if not candidates:
        return []

    asset_by_key = {asset.key: asset for asset in assets}
    parent: dict[str, str] = {}
    neighbors: dict[str, set[str]] = defaultdict(set)

    def find(key: str) -> str:
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left, right in candidates:
        union(left, right)
        neighbors[left].add(right)
        neighbors[right].add(left)

    groups: dict[str, set[str]] = defaultdict(set)
    for key in parent:
        groups[find(key)].add(key)

    oriented: list[PairResult] = []
    for members in groups.values():
        unassigned = set(members)
        while unassigned:
            survivor = max(
                unassigned,
                key=lambda key: survivor_rank(asset_by_key[key], policy),
            )
            deletion_candidates = neighbors[survivor] & unassigned
            for deletion_candidate in deletion_candidates:
                score, reason = candidates[tuple(sorted((survivor, deletion_candidate)))]
                oriented.append(
                    (
                        survivor,
                        deletion_candidate,
                        score,
                        f"automatic survivor policy {policy.value}; {reason}",
                    )
                )
            unassigned.difference_update(deletion_candidates)
            unassigned.remove(survivor)

    # Existing preview behavior: lowest similarity percentage first.
    oriented.sort(key=lambda pair: (pair[2], pair[0], pair[1]))
    return oriented
