#pragma once

#include "reduped/types.hpp"

#include <filesystem>
#include <string>

namespace reduped {

struct Config {
    std::string endpoint;
    std::string region{"auto"};
    std::string bucket;
    std::string prefix;
    std::string index_key;
    std::string access_key_id;
    std::string secret_access_key;
    std::string public_media_base;
    bool allow_delete{false};
    int slider{50};
    SurvivorPolicy survivor_policy{SurvivorPolicy::resolution};
    double video_sample_seconds{1.0};
    int max_video_frames{300};
    int preview_cache_mb{5000};
    unsigned hash_workers{8};
    unsigned compare_workers{0};

    static Config load(const std::filesystem::path& path);
    void validate() const;
};

} // namespace reduped
