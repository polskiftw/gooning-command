#pragma once

#include "reduped/config.hpp"
#include "reduped/database.hpp"
#include "reduped/object_store.hpp"

#include <functional>
#include <string>

namespace reduped {

class DeletionService {
public:
    using Status = std::function<void(std::string_view)>;
    DeletionService(Database& database,ObjectStore& store,const Config& config);
    void delete_single(const RenderedPairToken& token,bool delete_left,const Status& status);
    void nuke_visual(std::string_view generation_id,const Status& status);
    void nuke_exact(std::string_view generation_id,const Status& status);
    void recover_prepared(const Status& status);
    void retry_index_cleanup(const Status& status);
private:
    void require_enabled() const;
    void execute_intent(const DeletionIntent& intent,std::string_view key,bool recovery,const Status& status);
    Database& database_;
    ObjectStore& store_;
    const Config& config_;
};

} // namespace reduped
