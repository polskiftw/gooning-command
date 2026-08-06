from __future__ import annotations

from pathlib import Path

from deduper.database import Database
from deduper.generation_integration import initialize_generation_storage
from deduper.generation_store import GenerationIdentity


def _insert_asset(database: Database, key: str) -> None:
    with database.connection:
        database.connection.execute(
            """
            INSERT INTO assets (key, size, media_type, extension)
            VALUES (?, 100, 'image', '.jpg')
            """,
            (key,),
        )


def test_normal_database_startup_installs_generation_schema(tmp_path: Path) -> None:
    database = Database(tmp_path / "deduper.sqlite3")
    try:
        startup = initialize_generation_storage(database)

        assert startup.active_generation is None
        assert startup.legacy_view_only_generation_id is None
        row = database.connection.execute(
            "SELECT value FROM generation_schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        assert row is not None
        assert row["value"] == "1"
    finally:
        database.close()


def test_startup_marks_mutable_pairs_legacy_without_promoting_them(tmp_path: Path) -> None:
    database = Database(tmp_path / "deduper.sqlite3")
    try:
        _insert_asset(database, "gallery/a.jpg")
        _insert_asset(database, "gallery/b.jpg")
        with database.connection:
            database.connection.execute(
                """
                INSERT INTO pairs (left_key, right_key, similarity, reason, status)
                VALUES ('gallery/a.jpg', 'gallery/b.jpg', 0.99, 'legacy', 'included')
                """
            )
            database.connection.execute(
                """
                INSERT INTO meta (key, value) VALUES ('matching_state', 'complete')
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """
            )

        startup = initialize_generation_storage(database)

        assert startup.active_generation is None
        assert startup.legacy_view_only_generation_id is not None
        legacy = database.connection.execute(
            """
            SELECT state, inventory_fingerprint
            FROM certified_generations
            WHERE generation_id = ?
            """,
            (startup.legacy_view_only_generation_id,),
        ).fetchone()
        assert legacy["state"] == "legacy_view_only"
        assert legacy["inventory_fingerprint"] is None
        assert database.connection.execute("SELECT COUNT(*) FROM pairs").fetchone()[0] == 1
    finally:
        database.close()


def test_startup_is_idempotent_and_recovers_active_generation(tmp_path: Path) -> None:
    path = tmp_path / "deduper.sqlite3"
    database = Database(path)
    try:
        first = initialize_generation_storage(database)
        _insert_asset(database, "gallery/a.jpg")
        _insert_asset(database, "gallery/b.jpg")
        identity = GenerationIdentity(
            inventory_fingerprint="fingerprint",
            inventory_object_count=2,
            slider_value=50,
            matcher_version="matcher-v1",
            hash_version="hash-v1",
            workflow_version="workflow-v1",
        )
        generation_id = first.store.create_staging(identity)
        first.store.replace_staging_pairs(
            generation_id,
            [(0, "group-1", "gallery/a.jpg", "gallery/b.jpg", 0.99, "test")],
        )
        first.store.complete_staging(generation_id)
        first.store.promote(generation_id)
    finally:
        database.close()

    reopened = Database(path)
    try:
        second = initialize_generation_storage(reopened)
        third = initialize_generation_storage(reopened)

        assert second.active_generation is not None
        assert second.active_generation.generation_id == generation_id
        assert third.active_generation is not None
        assert third.active_generation.generation_id == generation_id
        assert reopened.connection.execute(
            "SELECT COUNT(*) FROM active_certified_generation"
        ).fetchone()[0] == 1
    finally:
        reopened.close()
