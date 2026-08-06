from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .generation_identity import MATCHER_VERSION, build_generation_identity
from .generation_store import GenerationRecord, GenerationStore
from .models import Asset


@dataclass(frozen=True)
class CertifiedPairRow:
    group_id: str
    survivor_key: str
    deletion_key: str
    similarity: float
    reason: str


@dataclass(frozen=True)
class ShaDeletionRow:
    survivor_key: str
    deletion_key: str


@dataclass(frozen=True)
class GenerationBuildPayload:
    pairs: tuple[CertifiedPairRow, ...]
    sha_deletions: tuple[ShaDeletionRow, ...]


@dataclass(frozen=True)
class GenerationBuildResult:
    generation: GenerationRecord
    pair_count: int
    sha_deletion_count: int


class GenerationBuildCancelled(RuntimeError):
    pass


PayloadBuilder = Callable[
    [tuple[Asset, ...], int, Callable[[], bool]],
    GenerationBuildPayload,
]


class CertifiedGenerationBuilder:
    """Build and atomically promote one immutable certified generation.

    The supplied inventory must be the materialized startup snapshot. This class
    never lists R2 and never mutates the currently active generation or visible
    review projection while staging is incomplete.
    """

    def __init__(
        self,
        generations: GenerationStore,
        inventory: Iterable[Asset],
        slider_value: int,
        payload_builder: PayloadBuilder,
        *,
        matcher_version: str = MATCHER_VERSION,
    ) -> None:
        self.generations = generations
        self.inventory = tuple(inventory)
        self.slider_value = int(slider_value)
        self.payload_builder = payload_builder
        self.matcher_version = matcher_version
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def build(self) -> GenerationBuildResult:
        if self._cancelled.is_set():
            raise GenerationBuildCancelled("generation build cancelled before staging")

        identity = build_generation_identity(
            self.inventory,
            self.slider_value,
            matcher_version=self.matcher_version,
        )
        staging_id = self.generations.create_staging(identity)
        try:
            payload = self.payload_builder(
                self.inventory,
                self.slider_value,
                self._cancelled.is_set,
            )
            if self._cancelled.is_set():
                raise GenerationBuildCancelled("generation build cancelled before commit")

            pair_rows = tuple(self._number_pairs(payload.pairs))
            sha_rows = tuple(self._number_sha_deletions(payload.sha_deletions))
            pair_count = self.generations.replace_staging_pairs(staging_id, pair_rows)
            sha_count = self.generations.replace_staging_sha_deletions(staging_id, sha_rows)

            if self._cancelled.is_set():
                raise GenerationBuildCancelled("generation build cancelled before promotion")

            self.generations.complete_staging(staging_id)
            self.generations.promote(staging_id)
            generation = self.generations.active()
            if generation is None or generation.generation_id != staging_id:
                raise RuntimeError("atomic generation promotion did not install staging generation")
            return GenerationBuildResult(generation, pair_count, sha_count)
        except Exception as exc:
            try:
                self.generations.fail_staging(staging_id, f"{type(exc).__name__}: {exc}")
            except ValueError:
                # Promotion may have completed before a later verification error.
                # Never rewrite a certified generation as failed.
                pass
            raise

    @staticmethod
    def _number_pairs(
        pairs: Iterable[CertifiedPairRow],
    ) -> Iterable[tuple[int, str, str, str, float, str]]:
        for position, row in enumerate(pairs):
            yield (
                position,
                row.group_id,
                row.survivor_key,
                row.deletion_key,
                float(row.similarity),
                row.reason,
            )

    @staticmethod
    def _number_sha_deletions(
        rows: Iterable[ShaDeletionRow],
    ) -> Iterable[tuple[int, str, str]]:
        for position, row in enumerate(rows):
            yield position, row.survivor_key, row.deletion_key
