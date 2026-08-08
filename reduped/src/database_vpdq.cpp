#include "reduped/database.hpp"

#include <stdexcept>
#include <string>
#include <unordered_map>

namespace reduped {
namespace {

void check_sql(sqlite3* db, int result) {
    if (result != SQLITE_OK && result != SQLITE_DONE && result != SQLITE_ROW)
        throw std::runtime_error(sqlite3_errmsg(db));
}

void ensure_table(sqlite3* db) {
    char* error{};
    const int result = sqlite3_exec(db, R"SQL(
CREATE TABLE IF NOT EXISTS rd_vpdq_quality(
 key TEXT NOT NULL,
 object_version TEXT NOT NULL,
 hash_version TEXT NOT NULL,
 frame_index INTEGER NOT NULL,
 quality INTEGER NOT NULL,
 PRIMARY KEY(key, object_version, hash_version, frame_index)
);
)SQL", nullptr, nullptr, &error);
    if (result != SQLITE_OK) {
        const std::string message = error ? error : sqlite3_errmsg(db);
        if (error) sqlite3_free(error);
        throw std::runtime_error(message);
    }
}

} // namespace

void Database::save_vpdq_qualities(const Evidence& evidence) {
    std::lock_guard lock(mutex_);
    ensure_table(db_);
    if (evidence.video_hashes.size() != evidence.video_qualities.size())
        throw std::runtime_error("vPDQ frame hashes and quality values are misaligned");

    check_sql(db_, sqlite3_exec(db_, "BEGIN IMMEDIATE", nullptr, nullptr, nullptr));
    try {
        sqlite3_stmt* remove{};
        check_sql(db_, sqlite3_prepare_v2(db_,
            "DELETE FROM rd_vpdq_quality WHERE key=? AND object_version=? AND hash_version=?", -1, &remove, nullptr));
        sqlite3_bind_text(remove, 1, evidence.key.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(remove, 2, evidence.object_version.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(remove, 3, evidence.hash_version.c_str(), -1, SQLITE_TRANSIENT);
        check_sql(db_, sqlite3_step(remove));
        sqlite3_finalize(remove);

        sqlite3_stmt* insert{};
        check_sql(db_, sqlite3_prepare_v2(db_,
            "INSERT INTO rd_vpdq_quality(key,object_version,hash_version,frame_index,quality) VALUES(?,?,?,?,?)", -1, &insert, nullptr));
        for (std::size_t i = 0; i < evidence.video_qualities.size(); ++i) {
            sqlite3_bind_text(insert, 1, evidence.key.c_str(), -1, SQLITE_TRANSIENT);
            sqlite3_bind_text(insert, 2, evidence.object_version.c_str(), -1, SQLITE_TRANSIENT);
            sqlite3_bind_text(insert, 3, evidence.hash_version.c_str(), -1, SQLITE_TRANSIENT);
            sqlite3_bind_int64(insert, 4, static_cast<sqlite3_int64>(i));
            sqlite3_bind_int(insert, 5, evidence.video_qualities[i]);
            check_sql(db_, sqlite3_step(insert));
            sqlite3_reset(insert);
            sqlite3_clear_bindings(insert);
        }
        sqlite3_finalize(insert);
        check_sql(db_, sqlite3_exec(db_, "COMMIT", nullptr, nullptr, nullptr));
    } catch (...) {
        sqlite3_exec(db_, "ROLLBACK", nullptr, nullptr, nullptr);
        throw;
    }
}

void Database::hydrate_vpdq_qualities(std::span<Evidence> evidence, std::string_view hash_version) const {
    std::lock_guard lock(mutex_);
    ensure_table(db_);
    sqlite3_stmt* query{};
    check_sql(db_, sqlite3_prepare_v2(db_,
        "SELECT quality FROM rd_vpdq_quality WHERE key=? AND object_version=? AND hash_version=? ORDER BY frame_index", -1, &query, nullptr));
    for (auto& item : evidence) {
        item.video_qualities.clear();
        sqlite3_bind_text(query, 1, item.key.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(query, 2, item.object_version.c_str(), -1, SQLITE_TRANSIENT);
        const std::string version(hash_version);
        sqlite3_bind_text(query, 3, version.c_str(), -1, SQLITE_TRANSIENT);
        while (sqlite3_step(query) == SQLITE_ROW) item.video_qualities.push_back(sqlite3_column_int(query, 0));
        sqlite3_reset(query);
        sqlite3_clear_bindings(query);
        if (!item.video_hashes.empty() && item.video_hashes.size() != item.video_qualities.size())
            throw std::runtime_error("Persisted vPDQ quality data is incomplete for " + item.key);
    }
    sqlite3_finalize(query);
}

} // namespace reduped
