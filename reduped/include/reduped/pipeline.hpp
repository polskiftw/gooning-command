#pragma once

#include "reduped/config.hpp"
#include "reduped/database.hpp"
#include "reduped/object_store.hpp"

#include <atomic>
#include <functional>
#include <string>

namespace reduped {

enum class StartupOutcome { validated_existing, certified_new, validation_failed, cancelled };

struct PipelineVersions {
    std::string hash{"native-phash-pdq-crop-vpdq-v2"};
    std::string matcher{"native-four-stage-v2"};
    std::string workflow{"certified-families-v1"};
};

class CertificationPipeline {
public:
    using Status = std::function<void(std::string_view)>;
    CertificationPipeline(Database& database, ObjectStore& store, EvidenceGenerator& generator,
                          const Config& config, PipelineVersions versions = {});
    StartupOutcome run(std::atomic_bool& cancelled, const Status& status);
    void recertify_pending(std::atomic_bool& cancelled, const Status& status);
private:
    Database& database_;
    ObjectStore& store_;
    EvidenceGenerator& generator_;
    const Config& config_;
    PipelineVersions versions_;
};

} // namespace reduped
