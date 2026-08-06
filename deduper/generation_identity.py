from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Protocol

from .generation_store import GenerationIdentity, GenerationRecord


MATCHER_VERSION = "certified-matcher-v1"
HASH_VERSION = "phash-crop-pdq-vpdq-v1"
WORKFLOW_VERSION = "certified-generation-v1"


class InventoryItem(Protocol):
    key: str
    size: int
    etag: str
    last_modified: str


@dataclass(frozen=True)
class InventoryIdentity:
    fingerprint: str
    object_count: int


class ValidationState(str, Enum):
    NO_CERTIFIED_GENERATION = "no_certified_generation"
    VALIDATED = "validated"
    INVENTORY_CHANGED = "inventory_changed"
    SLIDER_CHANGED = "slider_changed"
    MATCHER_CHANGED = "matcher_changed"
    HASH_CHANGED = "hash_changed"
    WORKFLOW_CHANGED = "workflow_changed"
    LEGACY_UNTRUSTED = "legacy_untrusted"


@dataclass(frozen=True)
class GenerationValidation:
    state: ValidationState
    actionable: bool
    reason: str


def inventory_identity(items: Iterable[InventoryItem]) -> InventoryIdentity:
    """Build an order-independent identity from R2 listing metadata.

    Length-prefixing each field prevents ambiguous concatenations, and including
    key, size, ETag, and last-modified detects same-count replacements.
    """
    materialized = sorted(items, key=lambda item: item.key)
    digest = hashlib.sha256()
    for item in materialized:
        for value in (
            item.key,
            str(int(item.size)),
            item.etag or "",
            item.last_modified or "",
        ):
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
    return InventoryIdentity(digest.hexdigest(), len(materialized))


def build_generation_identity(
    items: Iterable[InventoryItem],
    slider_value: int,
    *,
    matcher_version: str = MATCHER_VERSION,
    hash_version: str = HASH_VERSION,
    workflow_version: str = WORKFLOW_VERSION,
) -> GenerationIdentity:
    inventory = inventory_identity(items)
    return GenerationIdentity(
        inventory_fingerprint=inventory.fingerprint,
        inventory_object_count=inventory.object_count,
        slider_value=slider_value,
        matcher_version=matcher_version,
        hash_version=hash_version,
        workflow_version=workflow_version,
    )


def validate_generation(
    generation: GenerationRecord | None,
    current: GenerationIdentity,
) -> GenerationValidation:
    if generation is None:
        return GenerationValidation(
            ValidationState.NO_CERTIFIED_GENERATION,
            False,
            "No certified queue exists for this installation.",
        )
    if generation.state == "legacy_view_only" or generation.identity is None:
        return GenerationValidation(
            ValidationState.LEGACY_UNTRUSTED,
            False,
            "The saved queue lacks trustworthy inventory and version identity.",
        )

    saved = generation.identity
    if (
        saved.inventory_fingerprint != current.inventory_fingerprint
        or saved.inventory_object_count != current.inventory_object_count
    ):
        return GenerationValidation(
            ValidationState.INVENTORY_CHANGED,
            False,
            "The current R2 inventory differs from the certified queue inventory.",
        )
    if saved.slider_value != current.slider_value:
        return GenerationValidation(
            ValidationState.SLIDER_CHANGED,
            False,
            "The selected slider value differs from the certified queue.",
        )
    if saved.matcher_version != current.matcher_version:
        return GenerationValidation(
            ValidationState.MATCHER_CHANGED,
            False,
            "The matcher version differs from the certified queue.",
        )
    if saved.hash_version != current.hash_version:
        return GenerationValidation(
            ValidationState.HASH_CHANGED,
            False,
            "The hash pipeline version differs from the certified queue.",
        )
    if saved.workflow_version != current.workflow_version:
        return GenerationValidation(
            ValidationState.WORKFLOW_CHANGED,
            False,
            "The review workflow version differs from the certified queue.",
        )

    return GenerationValidation(
        ValidationState.VALIDATED,
        True,
        "Certified queue identity matches the current R2 inventory and software versions.",
    )
