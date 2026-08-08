#pragma once

#include "reduped/config.hpp"
#include "reduped/object_store.hpp"

#include <memory>

namespace reduped {

class WinHttpObjectStore final : public ObjectStore {
public:
    explicit WinHttpObjectStore(const Config& config);
    ~WinHttpObjectStore() override;
    std::vector<ObjectRecord> list_inventory(std::atomic_bool& cancelled) override;
    std::vector<std::uint8_t> download(std::string_view key, std::atomic_bool& cancelled) override;
    DeleteResult delete_object(std::string_view key) override;
    void remove_from_index(std::string_view index_key, std::string_view deleted_key) override;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace reduped
