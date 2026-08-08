#pragma once

#include "reduped/types.hpp"

#include <windows.h>

#include <cstdint>
#include <span>
#include <string_view>
#include <vector>

namespace reduped {

struct PreviewFrames {
    std::vector<HBITMAP> frames;
    std::vector<unsigned> delays_ms;
    PreviewFrames()=default;
    ~PreviewFrames();
    PreviewFrames(PreviewFrames&& other) noexcept;
    PreviewFrames& operator=(PreviewFrames&& other) noexcept;
    PreviewFrames(const PreviewFrames&)=delete;
};

PreviewFrames prepare_preview(std::span<const std::uint8_t> bytes,std::string_view key,
                              MediaKind kind,int width,int height);

} // namespace reduped
