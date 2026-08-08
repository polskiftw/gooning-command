#pragma once

#include "reduped/types.hpp"

#include <atomic>
#include <cstdint>
#include <span>
#include <string>
#include <vector>

namespace reduped {

enum class DeleteResult { deleted, not_found };

class ObjectStore {
public:
    virtual ~ObjectStore() = default;
    virtual std::vector<ObjectRecord> list_inventory(std::atomic_bool& cancelled) = 0;
    virtual std::vector<std::uint8_t> download(std::string_view key, std::atomic_bool& cancelled) = 0;
    virtual DeleteResult delete_object(std::string_view key) = 0;
    virtual void remove_from_index(std::string_view index_key, std::string_view deleted_key) = 0;
};

class EvidenceGenerator {
public:
    virtual ~EvidenceGenerator() = default;
    virtual Evidence generate(const ObjectRecord& object, std::span<const std::uint8_t> bytes,
                              double video_sample_seconds, int max_video_frames,
                              std::atomic_bool& cancelled) = 0;
};

} // namespace reduped
