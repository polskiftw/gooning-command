#pragma once

#include "reduped/types.hpp"

#include <cstdint>
#include <span>
#include <vector>

namespace reduped {

struct NativeStillHashes {
    std::uint64_t phash{};
    Hash256 pdq{};
    int pdq_quality{};
    std::vector<std::uint64_t> crop_hashes;
};

NativeStillHashes compute_native_still_hashes(std::span<const std::uint8_t> gray,
                                              int width, int height);

std::uint64_t imagehash_phash(std::span<const std::uint8_t> gray, int width, int height);
std::vector<std::uint64_t> imagehash_crop_resistant(std::span<const std::uint8_t> gray,
                                                    int width, int height);
std::pair<Hash256,int> meta_pdq(std::span<const std::uint8_t> gray, int width, int height);

} // namespace reduped
