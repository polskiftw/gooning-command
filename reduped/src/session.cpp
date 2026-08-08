#include "reduped/session.hpp"

#include "reduped/sqlite_api.hpp"

#include <stdexcept>
#include <string>

namespace reduped {

void reset_session_exclusions(const std::filesystem::path& database_path) {
    if (!std::filesystem::exists(database_path)) return;

    sqlite3* db{};
    const auto utf8 = database_path.u8string();
    const int opened = sqlite3_open_v2(reinterpret_cast<const char*>(utf8.c_str()), &db,
                                       SQLITE_OPEN_READWRITE | SQLITE_OPEN_FULLMUTEX, nullptr);
    if (opened != SQLITE_OK) {
        const std::string error = db ? sqlite3_errmsg(db) : "Unable to open Reduped database";
        if (db) sqlite3_close(db);
        throw std::runtime_error("Unable to reset session exclusions: " + error);
    }

    char* error{};
    const int result = sqlite3_exec(db, "UPDATE rd_pairs SET excluded=0 WHERE excluded<>0", nullptr, nullptr, &error);
    if (result != SQLITE_OK) {
        const std::string message = error ? error : sqlite3_errmsg(db);
        if (error) sqlite3_free(error);
        sqlite3_close(db);
        if (message.find("no such table: rd_pairs") != std::string::npos) return;
        throw std::runtime_error("Unable to reset session exclusions: " + message);
    }

    sqlite3_close(db);
}

} // namespace reduped
