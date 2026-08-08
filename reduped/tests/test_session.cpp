#include "reduped/database.hpp"
#include "reduped/session.hpp"

#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>

using namespace reduped;

namespace {

void require(bool condition, std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}

void exec(sqlite3* db, const char* sql) {
    char* error{};
    if (sqlite3_exec(db, sql, nullptr, nullptr, &error) != SQLITE_OK) {
        const std::string message = error ? error : sqlite3_errmsg(db);
        if (error) sqlite3_free(error);
        throw std::runtime_error(message);
    }
}

} // namespace

int main() {
    const auto path = std::filesystem::temp_directory_path() / "reduped-session-exclusion-test.sqlite3";
    std::error_code ignored;
    std::filesystem::remove(path, ignored);
    std::filesystem::remove(path.string() + "-wal", ignored);
    std::filesystem::remove(path.string() + "-shm", ignored);

    try {
        {
            Database db(path);
            exec(db.raw_for_tests(),
                 "INSERT INTO rd_generations(id,state,inventory_fingerprint,slider,matcher_version,hash_version,workflow_version,complete) "
                 "VALUES('g','certified','inventory',50,'matcher','hash','workflow',1);"
                 "INSERT INTO rd_families(generation_id,id,survivor_key,certified,revision) VALUES('g','f','left',1,1);"
                 "INSERT INTO rd_pairs(generation_id,family_id,left_key,right_key,difference,reason,excluded,revision) "
                 "VALUES('g','f','left','right',1.0,'test',1,2);"
                 "INSERT INTO rd_review_state(generation_id,position) VALUES('g',7);");
            const auto before = db.active_generation();
            require(before && before->pairs.size() == 1 && before->pairs[0].excluded,
                    "fixture did not persist an exclusion");
        }

        reset_session_exclusions(path);

        {
            Database db(path);
            const auto after = db.active_generation();
            require(after && after->pairs.size() == 1, "certified queue was damaged by session reset");
            require(!after->pairs[0].excluded, "excluded pair survived into a new session");
            require(after->review_position == 7, "session reset changed persistent review position");
        }

        std::filesystem::remove(path, ignored);
        std::filesystem::remove(path.string() + "-wal", ignored);
        std::filesystem::remove(path.string() + "-shm", ignored);
        std::cout << "session exclusion reset passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        std::filesystem::remove(path, ignored);
        std::filesystem::remove(path.string() + "-wal", ignored);
        std::filesystem::remove(path.string() + "-shm", ignored);
        return 1;
    }
}
