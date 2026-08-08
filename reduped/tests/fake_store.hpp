#pragma once

#include "reduped/object_store.hpp"

#include <map>
#include <set>
#include <stdexcept>

namespace reduped::test {

class FakeStore final : public ObjectStore {
public:
    std::vector<ObjectRecord> inventory;
    std::map<std::string,std::vector<std::uint8_t>> content;
    std::set<std::string> deleted;
    std::vector<std::string> index_removed;
    bool fail_list{};
    bool fail_delete{};
    bool fail_index{};
    int list_calls{};
    int download_calls{};

    std::vector<ObjectRecord> list_inventory(std::atomic_bool& cancelled) override;
    std::vector<std::uint8_t> download(std::string_view key,std::atomic_bool& cancelled) override;
    DeleteResult delete_object(std::string_view key) override;
    void remove_from_index(std::string_view index_key,std::string_view deleted_key) override;
};

class FakeEvidenceGenerator final : public EvidenceGenerator {
public:
    int calls{};
    Evidence generate(const ObjectRecord& object,std::span<const std::uint8_t> bytes,
                      double,int,std::atomic_bool& cancelled) override;
};

ObjectRecord object(std::string key,std::uint64_t size=100,std::string etag="v1",
                    MediaKind kind=MediaKind::image);
Evidence evidence(const ObjectRecord& object,std::string sha,std::uint64_t phash,
                  int width=100,int height=100);

} // namespace reduped::test
