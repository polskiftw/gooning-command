#pragma once

#include <array>
#include <chrono>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace reduped {

using Hash256 = std::array<std::uint64_t, 4>;

enum class MediaKind { image, animated_image, video, unknown };
enum class SurvivorPolicy { resolution, file_size, oldest, newest };
enum class GenerationState { staging, certified, inactive, failed };
enum class JobState { awaiting_remote, pending, running, retry, complete, cancelled };

struct ObjectRecord {
    std::string key;
    std::uint64_t size{};
    std::string etag;
    std::string last_modified;
    MediaKind media_kind{MediaKind::unknown};
};

struct Evidence {
    std::string key;
    std::string object_version;
    std::string sha256;
    std::optional<std::uint64_t> phash;
    std::optional<Hash256> pdq;
    int pdq_quality{};
    std::vector<std::uint64_t> crop_hashes;
    std::vector<Hash256> video_hashes;
    int width{};
    int height{};
    double duration_seconds{};
    std::string error;
    std::string hash_version;
};

struct MatchEdge {
    std::string left;
    std::string right;
    double difference{};
    std::string reason;
};

struct Family {
    std::string id;
    std::string survivor;
    std::vector<std::string> members;
};

struct ReviewPair {
    std::int64_t id{};
    std::string generation_id;
    std::string family_id;
    std::string left_key;
    std::string right_key;
    double difference{};
    std::string reason;
    bool excluded{};
    std::uint64_t revision{};
};

struct ExactDeletion {
    std::string survivor_key;
    std::string deletion_key;
};

struct GenerationIdentity {
    std::string inventory_fingerprint;
    int slider{};
    std::string matcher_version;
    std::string hash_version;
    std::string workflow_version;
};

struct GenerationSnapshot {
    std::string id;
    GenerationState state{GenerationState::staging};
    GenerationIdentity identity;
    std::vector<ReviewPair> pairs;
    std::vector<ExactDeletion> exact_deletions;
    std::size_t review_position{};
};

struct Reconciliation {
    std::vector<ObjectRecord> unchanged;
    std::vector<ObjectRecord> changed;
    std::vector<ObjectRecord> added;
    std::vector<ObjectRecord> missing;
};

struct RenderedPairToken {
    std::string generation_id;
    std::string family_id;
    std::int64_t pair_id{};
    std::string left_key;
    std::string right_key;
    std::uint64_t revision{};
};

inline bool preview_result_is_current(std::uint64_t result_revision,std::string_view result_key,
                                      std::uint64_t current_revision,std::string_view expected_key) {
    return result_revision == current_revision && result_key == expected_key;
}

struct ActionabilityInput {
    bool active_generation_certified{};
    bool startup_inventory_validated{};
    bool current_pair_exists{};
    bool current_pair_certified{};
    bool current_family_certified{};
    bool allow_delete{};
    bool destructive_operation_running{};
    bool relevant_family_invalidated{};
    bool validation_failed{};
    bool recertification_running{};
};

struct Actionability {
    bool can_review_mutate{};
    bool can_delete_single{};
    bool can_nuke{};
    bool can_nuke_sha{};
    std::string reason;
};

inline Actionability compute_actionability(const ActionabilityInput& in) {
    Actionability out;
    out.can_review_mutate = in.active_generation_certified && in.startup_inventory_validated &&
                            !in.destructive_operation_running && !in.relevant_family_invalidated;
    out.can_delete_single = out.can_review_mutate && in.current_pair_exists &&
                            in.current_pair_certified && in.current_family_certified && in.allow_delete;
    out.can_nuke = out.can_review_mutate && in.allow_delete;
    out.can_nuke_sha = out.can_review_mutate && in.allow_delete;
    if (in.validation_failed) out.reason = "R2 validation failed";
    else if (!in.startup_inventory_validated) out.reason = "Validating R2";
    else if (!in.allow_delete) out.reason = "Deletion safety enabled";
    else if (in.recertification_running) out.reason = "Family recertification running";
    else if (in.relevant_family_invalidated) out.reason = "Family is awaiting recertification";
    else if (in.destructive_operation_running) out.reason = "Deletion in progress";
    else if (!in.current_pair_exists) out.reason = "No certified pair selected";
    else out.reason = "Certified queue ready";
    return out;
}

} // namespace reduped
