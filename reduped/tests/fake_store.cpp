#include "fake_store.hpp"

#include "reduped/fingerprint.hpp"

#include <algorithm>

namespace reduped::test {

std::vector<ObjectRecord> FakeStore::list_inventory(std::atomic_bool& cancelled){++list_calls;if(fail_list)throw std::runtime_error("inventory unavailable");return cancelled.load()?std::vector<ObjectRecord>{}:inventory;}
std::vector<std::uint8_t> FakeStore::download(std::string_view key,std::atomic_bool& cancelled){++download_calls;if(cancelled.load())return {};auto found=content.find(std::string(key));if(found==content.end())throw std::runtime_error("missing fake content");return found->second;}
DeleteResult FakeStore::delete_object(std::string_view key){if(fail_delete)throw std::runtime_error("remote deletion failed");auto found=std::find_if(inventory.begin(),inventory.end(),[&](const auto& item){return item.key==key;});if(found==inventory.end())return DeleteResult::not_found;inventory.erase(found);deleted.insert(std::string(key));return DeleteResult::deleted;}
void FakeStore::remove_from_index(std::string_view,std::string_view key){if(fail_index)throw std::runtime_error("index conflict");index_removed.push_back(std::string(key));}

Evidence FakeEvidenceGenerator::generate(const ObjectRecord& object,std::span<const std::uint8_t> bytes,double,int,std::atomic_bool& cancelled){++calls;if(cancelled.load())throw std::runtime_error("cancelled");Evidence value;value.key=object.key;value.sha256=sha256_hex(bytes);std::uint64_t hash=0;for(const auto byte:bytes)hash=hash*131+byte;value.phash=hash;value.pdq=Hash256{hash,hash*3,hash*5,hash*7};value.pdq_quality=80;value.crop_hashes={hash};value.width=100;value.height=100;return value;}

ObjectRecord object(std::string key,std::uint64_t size,std::string etag,MediaKind kind){return {std::move(key),size,std::move(etag),"2026-01-01T00:00:00Z",kind};}
Evidence evidence(const ObjectRecord& object,std::string sha,std::uint64_t phash,int width,int height){Evidence value;value.key=object.key;value.object_version=object_version(object);value.sha256=std::move(sha);value.phash=phash;value.pdq=Hash256{phash,phash,phash,phash};value.pdq_quality=80;value.crop_hashes={phash};value.width=width;value.height=height;value.hash_version="native-evidence-v1";return value;}

} // namespace reduped::test
