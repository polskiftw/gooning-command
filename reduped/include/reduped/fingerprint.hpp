#pragma once

#include "reduped/types.hpp"

#include <span>
#include <string>
#include <vector>

namespace reduped {

std::string sha256_hex(std::span<const std::uint8_t> bytes);
std::string sha256_hex(std::string_view text);
std::string object_version(const ObjectRecord& object);
std::string inventory_fingerprint(std::vector<ObjectRecord> inventory);
std::string stable_id(std::string_view type, std::span<const std::string> parts);

} // namespace reduped
