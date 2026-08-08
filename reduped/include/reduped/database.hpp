#pragma once

#include "reduped/sqlite_api.hpp"
#include "reduped/types.hpp"

#include <filesystem>
#include <functional>
#include <mutex>
#include <optional>
#include <span>
#include <string>
#include <vector>

namespace reduped {

struct RecertificationJob {
    std::int64_t id{};
    std::string generation_id;
    std::string family_id;
    std::string deleted_key;
    std::string protected_key;
    std::vector<std::string> priority_keys;
    JobState state{JobState::pending};
    int attempts{};
    std::string last_error;
};

struct DeletionIntent {
    std::int64_t action_id{};
    std::optional<std::int64_t> recertification_job_id;
};

struct PreparedAction {
    std::int64_t id{};
    std::string generation_id;
    std::string deleted_key;
    std::string protected_key;
    std::string source;
    std::optional<std::int64_t> recertification_job_id;
};

class Database {
public:
    explicit Database(const std::filesystem::path& path);
    ~Database();
    Database(const Database&) = delete;
    Database& operator=(const Database&) = delete;

    Reconciliation reconcile_inventory(std::span<const ObjectRecord> current);
    std::vector<ObjectRecord> live_assets() const;
    std::optional<Evidence> evidence_for(std::string_view key, std::string_view version,
                                         std::string_view hash_version) const;
    std::vector<Evidence> current_evidence(std::string_view hash_version) const;
    void save_evidence(const Evidence& evidence);
    void save_vpdq_qualities(const Evidence& evidence);
    void hydrate_vpdq_qualities(std::span<Evidence> evidence, std::string_view hash_version) const;

    std::string create_staging(const GenerationIdentity& identity);
    void save_staging_result(std::string_view generation_id,
                             std::span<const Family> families,
                             std::span<const ReviewPair> pairs,
                             std::span<const ExactDeletion> exact);
    void promote(std::string_view generation_id);
    void fail_staging(std::string_view generation_id, std::string_view error);
    std::optional<GenerationSnapshot> active_generation() const;
    bool identity_matches(const GenerationIdentity& identity) const;
    void save_review_position(std::string_view generation_id, std::size_t position);
    bool exclude_pair(const RenderedPairToken& token);
    bool rendered_pair_is_current(const RenderedPairToken& token) const;
    bool family_is_certified(std::string_view generation_id, std::string_view family_id) const;

    DeletionIntent prepare_single_deletion(const RenderedPairToken& token,
                                           std::string_view selected_key,
                                           std::string_view protected_key);
    DeletionIntent prepare_batch_deletion(std::string_view generation_id,
                                          std::string_view selected_key,
                                          std::string_view protected_key,
                                          std::string_view source);
    std::vector<PreparedAction> prepared_actions() const;
    void deletion_remote_failed(std::int64_t action_id, std::string_view error);
    void deletion_remote_succeeded(std::int64_t action_id, std::string_view deleted_key,
                                   std::optional<std::int64_t> recertification_job_id);
    std::vector<RecertificationJob> recoverable_recertification_jobs();
    bool claim_recertification(std::int64_t id);
    void retry_recertification(std::int64_t id, std::string_view error);
    void complete_recertification(std::int64_t id, std::span<const Family> families,
                                  std::span<const ReviewPair> pairs);

    std::vector<std::string> pending_index_cleanup() const;
    void complete_index_cleanup(std::string_view key);
    void fail_index_cleanup(std::string_view key, std::string_view error);

    std::vector<std::string> visual_nuke_plan(std::string_view generation_id) const;
    std::vector<std::string> exact_nuke_plan(std::string_view generation_id) const;
    std::vector<ReviewPair> family_pairs(std::string_view generation_id,
                                         std::string_view family_id) const;

    sqlite3* raw_for_tests() const { return db_; }

private:
    void migrate();
    void execute(std::string_view sql) const;
    void transaction(const std::function<void()>& body) const;
    std::string scalar_text(std::string_view sql) const;
    mutable std::recursive_mutex mutex_;
    sqlite3* db_{};
};

} // namespace reduped
