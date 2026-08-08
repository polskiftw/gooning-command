#include "reduped/config.hpp"

#include <algorithm>
#include <cctype>
#include <fstream>
#include <stdexcept>
#include <thread>
#include <unordered_map>

namespace reduped {
namespace {

std::string trim(std::string value) {
    auto not_space = [](unsigned char c) { return !std::isspace(c); };
    value.erase(value.begin(), std::find_if(value.begin(), value.end(), not_space));
    value.erase(std::find_if(value.rbegin(), value.rend(), not_space).base(), value.end());
    return value;
}

std::string lower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return value;
}

int integer(const std::unordered_map<std::string, std::string>& values,
            const std::string& key, int fallback) {
    const auto it = values.find(key);
    return it == values.end() || it->second.empty() ? fallback : std::stoi(it->second);
}

} // namespace

Config Config::load(const std::filesystem::path& path) {
    std::ifstream input(path);
    if (!input) throw std::runtime_error("Missing config.txt. Copy config.example.txt and fill in local values.");
    std::unordered_map<std::string, std::string> values;
    std::string line;
    std::size_t line_number = 0;
    while (std::getline(input, line)) {
        ++line_number;
        line = trim(line);
        if (line.empty() || line.front() == '#') continue;
        const auto split = line.find('=');
        if (split == std::string::npos) {
            throw std::runtime_error("Config line " + std::to_string(line_number) + " must use NAME=value");
        }
        values[trim(line.substr(0, split))] = trim(line.substr(split + 1));
    }

    Config config;
    config.endpoint = values["ENDPOINT"];
    if (!values["REGION"].empty()) config.region = values["REGION"];
    config.bucket = values["BUCKET"];
    config.prefix = values["PREFIX"];
    config.index_key = values["INDEX_KEY"];
    config.access_key_id = values["ACCESS_KEY_ID"];
    config.secret_access_key = values["SECRET_ACCESS_KEY"];
    config.public_media_base = values["PUBLIC_MEDIA_BASE"];
    config.allow_delete = lower(values["ALLOW_DELETE"]) == "yes";
    config.slider = integer(values, "SLIDER", 50);
    config.video_sample_seconds = values["VIDEO_SAMPLE_SECONDS"].empty()
        ? 1.0 : std::stod(values["VIDEO_SAMPLE_SECONDS"]);
    config.max_video_frames = integer(values, "MAX_VIDEO_FRAMES", 300);
    config.preview_cache_mb = integer(values, "PREVIEW_CACHE_MB", 5000);
    config.hash_workers = static_cast<unsigned>(integer(values, "HASH_WORKERS", 8));
    config.compare_workers = static_cast<unsigned>(integer(values, "COMPARE_WORKERS", 0));
    const auto policy = lower(values["SURVIVOR_POLICY"]);
    if (policy.empty() || policy == "resolution") config.survivor_policy = SurvivorPolicy::resolution;
    else if (policy == "file_size") config.survivor_policy = SurvivorPolicy::file_size;
    else if (policy == "oldest") config.survivor_policy = SurvivorPolicy::oldest;
    else if (policy == "newest") config.survivor_policy = SurvivorPolicy::newest;
    else throw std::runtime_error("SURVIVOR_POLICY must be resolution, file_size, oldest, or newest");
    if (config.compare_workers == 0) {
        config.compare_workers = std::max(1u, std::thread::hardware_concurrency());
    }
    config.validate();
    return config;
}

void Config::validate() const {
    if (endpoint.empty() || bucket.empty() || access_key_id.empty() || secret_access_key.empty()) {
        throw std::runtime_error("ENDPOINT, BUCKET, ACCESS_KEY_ID, and SECRET_ACCESS_KEY are required");
    }
    if (slider < 0 || slider > 99) throw std::runtime_error("SLIDER must be between 0 and 99");
    if (video_sample_seconds <= 0 || max_video_frames < 1) {
        throw std::runtime_error("Video sampling values must be positive");
    }
    if (preview_cache_mb < 64 || hash_workers < 1 || compare_workers < 1) {
        throw std::runtime_error("Cache and worker values must be positive");
    }
}

} // namespace reduped
