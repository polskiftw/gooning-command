#pragma once

#include "reduped/types.hpp"

#include <span>
#include <vector>

namespace reduped {

struct GenerationResult {
    std::vector<Family> families;
    std::vector<ReviewPair> pairs;
    std::vector<ExactDeletion> exact_deletions;
};

GenerationResult construct_generation(std::span<const ObjectRecord> objects,
                                      std::span<const Evidence> evidence,
                                      std::span<const MatchEdge> edges,
                                      SurvivorPolicy survivor_policy,
                                      std::string_view generation_id);

GenerationResult recertify_family(std::span<const ObjectRecord> objects,
                                  std::span<const Evidence> evidence,
                                  int slider,
                                  unsigned workers,
                                  SurvivorPolicy survivor_policy,
                                  std::string_view generation_id);

} // namespace reduped
