#pragma once

#include "reduped/types.hpp"

#include <atomic>
#include <span>
#include <vector>

namespace reduped {

struct MatchPolicy {
    unsigned phash_radius{};
    unsigned pdq_radius{};
    unsigned crop_radius{};
    unsigned video_radius{};
    double required_video_fraction{};
    int minimum_pdq_quality{};
};

MatchPolicy policy_for_slider(int slider);
unsigned hamming(std::uint64_t left, std::uint64_t right);
unsigned hamming(const Hash256& left, const Hash256& right);
std::vector<MatchEdge> match_all(std::span<const Evidence> evidence, int slider,
                                 unsigned workers, std::atomic_bool* cancelled = nullptr);

} // namespace reduped
