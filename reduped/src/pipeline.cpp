#include "reduped/pipeline.hpp"

#include "reduped/fingerprint.hpp"
#include "reduped/generation.hpp"
#include "reduped/matcher.hpp"

#include <algorithm>
#include <atomic>
#include <exception>
#include <mutex>
#include <thread>
#include <unordered_map>

namespace reduped {

CertificationPipeline::CertificationPipeline(Database& database,ObjectStore& store,EvidenceGenerator& generator,
                                               const Config& config,PipelineVersions versions)
    :database_(database),store_(store),generator_(generator),config_(config),versions_(std::move(versions)){}

StartupOutcome CertificationPipeline::run(std::atomic_bool& cancelled,const Status& status){
    if(cancelled.load())return StartupOutcome::cancelled;
    status("Validating R2. Saved certified queue is view-only.");
    std::vector<ObjectRecord> inventory;
    try{inventory=store_.list_inventory(cancelled);}catch(const std::exception& e){status(std::string("Validation failed: ")+e.what());return StartupOutcome::validation_failed;}
    if(cancelled.load())return StartupOutcome::cancelled;
    const auto fingerprint=inventory_fingerprint(inventory);
    const GenerationIdentity identity{fingerprint,config_.slider,versions_.matcher,versions_.hash,versions_.workflow};
    if(database_.identity_matches(identity)){status("Saved queue valid. Certified queue ready.");return StartupOutcome::validated_existing;}

    status("R2 changed or matcher version changed. Reconciling inventory.");
    database_.reconcile_inventory(inventory);
    std::vector<ObjectRecord> needs_hash;
    for(const auto& object:inventory)if(!database_.evidence_for(object.key,object_version(object),versions_.hash))needs_hash.push_back(object);
    if(!needs_hash.empty())status("Hashing new/changed objects with pHash, PDQ, crop-resistant hashing, and vPDQ.");
    std::atomic_size_t next{0};std::mutex error_mutex;std::exception_ptr first_error;
    const auto worker_count=std::min<std::size_t>(config_.hash_workers,std::max<std::size_t>(1,needs_hash.size()));
    std::vector<std::thread> workers;
    for(std::size_t w=0;w<worker_count;++w)workers.emplace_back([&]{
        while(!cancelled.load()){
            const auto i=next.fetch_add(1);if(i>=needs_hash.size())break;
            try{
                auto bytes=store_.download(needs_hash[i].key,cancelled);if(cancelled.load())break;
                auto evidence=generator_.generate(needs_hash[i],bytes,config_.video_sample_seconds,config_.max_video_frames,cancelled);
                evidence.object_version=object_version(needs_hash[i]);evidence.hash_version=versions_.hash;
                database_.save_evidence(evidence);database_.save_vpdq_qualities(evidence);
            }
            catch(...){std::lock_guard guard(error_mutex);if(!first_error)first_error=std::current_exception();cancelled.store(true);break;}
        }
    });
    for(auto& worker:workers)worker.join();
    if(first_error){try{std::rethrow_exception(first_error);}catch(const std::exception& e){status(std::string("Hashing failed: ")+e.what());}return StartupOutcome::validation_failed;}
    if(cancelled.load())return StartupOutcome::cancelled;

    status("Building staging certification with all four matching algorithms.");
    const auto generation_id=database_.create_staging(identity);
    try{
        auto current=database_.current_evidence(versions_.hash);database_.hydrate_vpdq_qualities(current,versions_.hash);
        auto edges=match_all(current,config_.slider,config_.compare_workers,&cancelled);
        if(cancelled.load())return StartupOutcome::cancelled;
        auto result=construct_generation(database_.live_assets(),current,edges,config_.survivor_policy,generation_id);
        database_.save_staging_result(generation_id,result.families,result.pairs,result.exact_deletions);
        status("Promoting certified queue.");database_.promote(generation_id);
    }catch(const std::exception& e){database_.fail_staging(generation_id,e.what());status(std::string("Certification failed: ")+e.what());return StartupOutcome::validation_failed;}
    status("Certified queue ready.");return StartupOutcome::certified_new;
}

void CertificationPipeline::recertify_pending(std::atomic_bool& cancelled,const Status& status){
    for(const auto& job:database_.recoverable_recertification_jobs()){
        if(cancelled.load())return;
        if(!database_.claim_recertification(job.id))continue;
        status("Family recertification running. Protected partner remains safe in R2 and hidden from review.");
        try{
            const auto all_objects=database_.live_assets();auto all_evidence=database_.current_evidence(versions_.hash);database_.hydrate_vpdq_qualities(all_evidence,versions_.hash);
            std::unordered_map<std::string,ObjectRecord> objects;for(const auto& object:all_objects)objects[object.key]=object;
            std::unordered_map<std::string,Evidence> evidence;for(const auto& item:all_evidence)evidence[item.key]=item;
            std::vector<ObjectRecord> selected_objects;std::vector<Evidence> selected_evidence;
            for(const auto& key:job.priority_keys)if(objects.contains(key)&&evidence.contains(key)){selected_objects.push_back(objects.at(key));selected_evidence.push_back(evidence.at(key));}
            auto active=database_.active_generation();if(!active)throw std::runtime_error("Active certified generation disappeared");
            auto rebuilt=recertify_family(selected_objects,selected_evidence,active->identity.slider,config_.compare_workers,config_.survivor_policy,active->id);
            database_.complete_recertification(job.id,rebuilt.families,rebuilt.pairs);
        }catch(const std::exception& e){database_.retry_recertification(job.id,e.what());status("Family recertification saved for automatic retry.");}
    }
}

} // namespace reduped
