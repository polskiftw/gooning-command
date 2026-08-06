from __future__ import annotations

from enum import Enum

from .models import Asset


class SurvivorPolicy(str, Enum):
    BALANCED = "1"
    RESOLUTION = "2"
    FILE_SIZE = "3"
    DURATION = "4"
    PDQ_QUALITY = "5"


SURVIVOR_POLICY_LABELS = {
    SurvivorPolicy.BALANCED: "balanced quality (current behavior)",
    SurvivorPolicy.RESOLUTION: "highest resolution",
    SurvivorPolicy.FILE_SIZE: "largest file size",
    SurvivorPolicy.DURATION: "longest duration",
    SurvivorPolicy.PDQ_QUALITY: "highest PDQ quality",
}


def parse_survivor_policy(value: str) -> SurvivorPolicy:
    normalized = value.strip()
    try:
        return SurvivorPolicy(normalized)
    except ValueError as exc:
        choices = ", ".join(
            f"{policy.value}={SURVIVOR_POLICY_LABELS[policy]}"
            for policy in SurvivorPolicy
        )
        raise ValueError(f"SURVIVOR_POLICY must be one of: {choices}") from exc


def survivor_rank(asset: Asset, policy: SurvivorPolicy) -> tuple:
    """Return a deterministic rank; the final key tie-break prevents randomness."""
    pixels = int(asset.width or 0) * int(asset.height or 0)
    duration = float(asset.duration or 0)
    pdq_quality = int(asset.pdq_quality or 0)
    size = int(asset.size)

    if policy == SurvivorPolicy.RESOLUTION:
        return pixels, size, pdq_quality, duration, asset.key
    if policy == SurvivorPolicy.FILE_SIZE:
        return size, pixels, pdq_quality, duration, asset.key
    if policy == SurvivorPolicy.DURATION:
        return duration, pixels, size, pdq_quality, asset.key
    if policy == SurvivorPolicy.PDQ_QUALITY:
        return pdq_quality, pixels, size, duration, asset.key
    return pixels, duration, pdq_quality, size, asset.key


def matcher_identity(policy: SurvivorPolicy) -> str:
    """Changing survivor policy invalidates old actionable certification safely."""
    return f"certified-matcher-v1-survivor-{policy.value}"
