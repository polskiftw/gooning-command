#include "reduped/deletion.hpp"

#include <stdexcept>
#include <unordered_map>

namespace reduped {

DeletionService::DeletionService(Database& database,ObjectStore& store,const Config& config):database_(database),store_(store),config_(config){}
void DeletionService::require_enabled()const{if(!config_.allow_delete)throw std::runtime_error("Deletion safety enabled");}

void DeletionService::execute_intent(const DeletionIntent& intent,std::string_view key,bool recovery,const Status& status){
    try{
        const auto result=store_.delete_object(key);
        if(result==DeleteResult::not_found&&!recovery)throw std::runtime_error("Remote object was already missing; deletion was not attributed to this action");
        database_.deletion_remote_succeeded(intent.action_id,key,intent.recertification_job_id);
        status("Deletion complete.");
        try{if(!config_.index_key.empty()){store_.remove_from_index(config_.index_key,key);database_.complete_index_cleanup(key);}}
        catch(const std::exception& e){database_.fail_index_cleanup(key,e.what());status("Media deleted. Gallery index cleanup saved for automatic retry.");}
    }catch(const std::exception& e){database_.deletion_remote_failed(intent.action_id,e.what());throw;}
}

void DeletionService::delete_single(const RenderedPairToken& token,bool delete_left,const Status& status){
    require_enabled();const auto& selected=delete_left?token.left_key:token.right_key;const auto& protected_key=delete_left?token.right_key:token.left_key;
    auto intent=database_.prepare_single_deletion(token,selected,protected_key);status("Deletion in progress.");execute_intent(intent,selected,false,status);
}

void DeletionService::nuke_visual(std::string_view gid,const Status& status){
    require_enabled();const auto targets=database_.visual_nuke_plan(gid);auto active=database_.active_generation();if(!active||active->id!=gid)throw std::runtime_error("Certified generation changed before NUKE");
    std::unordered_map<std::string,std::string> survivors;for(const auto& pair:active->pairs)if(!pair.excluded)survivors[pair.right_key]=pair.left_key;
    for(const auto& key:targets){auto intent=database_.prepare_batch_deletion(gid,key,survivors.at(key),"visual_nuke");execute_intent(intent,key,false,status);}
}

void DeletionService::nuke_exact(std::string_view gid,const Status& status){
    require_enabled();auto active=database_.active_generation();if(!active||active->id!=gid)throw std::runtime_error("Certified generation changed before NUKE SHA ONLY");
    std::unordered_map<std::string,std::string> survivors;for(const auto& item:active->exact_deletions)survivors[item.deletion_key]=item.survivor_key;
    for(const auto& key:database_.exact_nuke_plan(gid)){auto intent=database_.prepare_batch_deletion(gid,key,survivors.at(key),"sha_nuke");execute_intent(intent,key,false,status);}
}

void DeletionService::recover_prepared(const Status& status){
    require_enabled();for(const auto& action:database_.prepared_actions()){status("Recovering interrupted deletion.");execute_intent({action.id,action.recertification_job_id},action.deleted_key,true,status);}
}

void DeletionService::retry_index_cleanup(const Status& status){
    if(config_.index_key.empty())return;
    for(const auto& key:database_.pending_index_cleanup()) {
        try {
            store_.remove_from_index(config_.index_key,key);
            database_.complete_index_cleanup(key);
        } catch(const std::exception& e) {
            database_.fail_index_cleanup(key,e.what());
            status("Gallery index cleanup saved for automatic retry.");
        }
    }
}

} // namespace reduped
