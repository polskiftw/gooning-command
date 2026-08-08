#pragma once

#include "reduped/fingerprint.hpp"
#include "reduped/types.hpp"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <optional>
#include <string>
#include <system_error>
#include <utility>
#include <vector>

namespace reduped {

// Disposable on-disk cache for original media bytes used only by the preview UI.
// A zero-byte limit disables the cache completely: no cache directory is created,
// no cached file is read, and every request calls the supplied loader.
class PreviewCache {
public:
    PreviewCache(std::filesystem::path directory, int limit_mb)
        : directory_(std::move(directory)),
          limit_bytes_(limit_mb <= 0 ? 0ULL : static_cast<std::uint64_t>(limit_mb) * 1024ULL * 1024ULL) {
        if (limit_bytes_ != 0) std::filesystem::create_directories(directory_);
    }

    bool enabled() const noexcept { return limit_bytes_ != 0; }

    template<class Loader>
    std::vector<std::uint8_t> load(const ObjectRecord& object, Loader&& loader) {
        // PREVIEW_CACHE_MB=0 deliberately means "fresh from R2 every time".
        if (!enabled()) return std::forward<Loader>(loader)();

        const auto path = cache_path(object);
        {
            std::lock_guard lock(mutex_);
            if (auto cached = read_valid_locked(path, object.size)) {
                touch_locked(path);
                return std::move(*cached);
            }
        }

        // Do not hold the cache lock during network I/O. The two preview workers
        // must remain able to download the left and right sides concurrently.
        auto bytes = std::forward<Loader>(loader)();
        if (bytes.size() != object.size || bytes.size() > limit_bytes_) return bytes;

        {
            std::lock_guard lock(mutex_);
            // Another worker may have filled the same entry while this one was
            // downloading. In that case its copy is already valid; just touch it.
            std::error_code error;
            if (std::filesystem::is_regular_file(path, error) &&
                !error && std::filesystem::file_size(path, error) == object.size && !error) {
                touch_locked(path);
                return bytes;
            }

            make_room_locked(static_cast<std::uint64_t>(bytes.size()));
            write_atomic_locked(path, bytes);
        }
        return bytes;
    }

private:
    struct Entry {
        std::filesystem::path path;
        std::uint64_t size{};
        std::filesystem::file_time_type used{};
    };

    std::filesystem::path cache_path(const ObjectRecord& object) const {
        // object_version already includes key, size, ETag, and Last-Modified.
        // Including it in the cache identity prevents stale data after an R2
        // object is replaced without changing its key.
        const auto identity = object.key + "\n" + object_version(object);
        return directory_ / (sha256_hex(identity) + ".bin");
    }

    std::optional<std::vector<std::uint8_t>> read_valid_locked(const std::filesystem::path& path,
                                                                std::uint64_t expected_size) {
        std::error_code error;
        if (!std::filesystem::is_regular_file(path, error) || error) return std::nullopt;
        const auto size = std::filesystem::file_size(path, error);
        if (error || size != expected_size) {
            std::filesystem::remove(path, error);
            return std::nullopt;
        }

        std::ifstream input(path, std::ios::binary);
        if (!input) {
            std::filesystem::remove(path, error);
            return std::nullopt;
        }
        std::vector<std::uint8_t> bytes(static_cast<std::size_t>(size));
        if (size != 0) input.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(size));
        if (!input) {
            std::filesystem::remove(path, error);
            return std::nullopt;
        }
        return bytes;
    }

    void touch_locked(const std::filesystem::path& path) {
        std::error_code ignored;
        std::filesystem::last_write_time(path, std::filesystem::file_time_type::clock::now(), ignored);
    }

    void make_room_locked(std::uint64_t incoming) {
        std::vector<Entry> entries;
        std::uint64_t total = 0;
        std::error_code error;
        for (std::filesystem::directory_iterator it(directory_, error), end; !error && it != end; it.increment(error)) {
            std::error_code item_error;
            if (!it->is_regular_file(item_error) || item_error) continue;
            if (it->path().extension() != ".bin") continue;
            const auto size = it->file_size(item_error);
            if (item_error) continue;
            const auto used = it->last_write_time(item_error);
            if (item_error) continue;
            total += static_cast<std::uint64_t>(size);
            entries.push_back({it->path(), static_cast<std::uint64_t>(size), used});
        }

        if (total + incoming <= limit_bytes_) return;
        std::sort(entries.begin(), entries.end(), [](const Entry& a, const Entry& b) { return a.used < b.used; });
        for (const auto& entry : entries) {
            std::error_code remove_error;
            if (std::filesystem::remove(entry.path, remove_error) && !remove_error) {
                total = entry.size > total ? 0 : total - entry.size;
                if (total + incoming <= limit_bytes_) break;
            }
        }
    }

    void write_atomic_locked(const std::filesystem::path& path,
                             const std::vector<std::uint8_t>& bytes) {
        const auto nonce = std::chrono::steady_clock::now().time_since_epoch().count();
        auto temporary = path;
        temporary += ".tmp-" + std::to_string(nonce);
        {
            std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
            if (!output) return; // Cache failure must never make previewing fail.
            if (!bytes.empty()) output.write(reinterpret_cast<const char*>(bytes.data()),
                                             static_cast<std::streamsize>(bytes.size()));
            if (!output) {
                output.close();
                std::error_code ignored;
                std::filesystem::remove(temporary, ignored);
                return;
            }
        }

        std::error_code error;
        std::filesystem::rename(temporary, path, error);
        if (error) std::filesystem::remove(temporary, error);
    }

    std::filesystem::path directory_;
    std::uint64_t limit_bytes_{};
    std::mutex mutex_;
};

} // namespace reduped
