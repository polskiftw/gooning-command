#pragma once

#include <filesystem>

namespace reduped {

void reset_session_exclusions(const std::filesystem::path& database_path);

} // namespace reduped
