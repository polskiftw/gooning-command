#pragma once

#include "reduped/object_store.hpp"

#include <memory>

namespace reduped {

class WindowsEvidenceGenerator final : public EvidenceGenerator {
public:
    WindowsEvidenceGenerator();
    ~WindowsEvidenceGenerator() override;
    Evidence generate(const ObjectRecord& object, std::span<const std::uint8_t> bytes,
                      double video_sample_seconds, int max_video_frames,
                      std::atomic_bool& cancelled) override;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace reduped
