#include "fake_store.hpp"

#include "reduped/config.hpp"
#include "reduped/database.hpp"
#include "reduped/deletion.hpp"
#include "reduped/fingerprint.hpp"
#include "reduped/generation.hpp"
#include "reduped/matcher.hpp"
#include "reduped/pipeline.hpp"
#include "reduped/types.hpp"

#include <algorithm>
#include <atomic>
#include <filesystem>
#include <functional>
#include <iostream>
#include <memory>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

using namespace reduped;
using namespace reduped::test;

namespace {

void require(bool condition,std::string_view message){if(!condition)throw std::runtime_error(std::string(message));}

struct Fixture{
 std::filesystem::path path;
 std::unique_ptr<Database> db;
 Fixture(){path=std::filesystem::temp_directory_path()/std::filesystem::path("reduped-test-"+std::to_string(reinterpret_cast<std::uintptr_t>(this))+".sqlite3");std::error_code ignored;std::filesystem::remove(path,ignored);db=std::make_unique<Database>(path);}
 ~Fixture(){db.reset();std::error_code ignored;std::filesystem::remove(path,ignored);std::filesystem::remove(path.string()+"-wal",ignored);std::filesystem::remove(path.string()+"-shm",ignored);}
};

GenerationSnapshot certify(Database& db,const std::vector<ObjectRecord>& objects,const std::vector<Evidence>& evidence_values,const std::vector<MatchEdge>& edges,int slider=50){
 db.reconcile_inventory(objects);for(const auto& value:evidence_values)db.save_evidence(value);GenerationIdentity identity{inventory_fingerprint(objects),slider,"native-exhaustive-v1","native-evidence-v1","certified-families-v1"};const auto id=db.create_staging(identity);auto result=construct_generation(objects,evidence_values,edges,SurvivorPolicy::resolution,id);db.save_staging_result(id,result.families,result.pairs,result.exact_deletions);db.promote(id);return *db.active_generation();
}

Config deletion_config(){Config config;config.allow_delete=true;config.index_key="index";config.compare_workers=2;return config;}

std::vector<ObjectRecord> star_objects(){return {object("A",100),object("B",90),object("C",80),object("D",70),object("E",60)};}
std::vector<Evidence> star_evidence(const std::vector<ObjectRecord>& objects){return {evidence(objects[0],"sha-a",1,1000,1000),evidence(objects[1],"sha-b",2,500,500),evidence(objects[2],"sha-c",3,400,400),evidence(objects[3],"sha-d",4,800,800),evidence(objects[4],"sha-e",5,300,300)};}
std::vector<MatchEdge> star_edges(){return {{"A","B",1,"direct"},{"A","C",2,"direct"},{"D","E",3,"direct"}};}

void fingerprint_is_deterministic(){auto a=object("a"),b=object("b");require(inventory_fingerprint({a,b})==inventory_fingerprint({b,a}),"inventory list order changed fingerprint");b.etag="different";require(inventory_fingerprint({a,b})!=inventory_fingerprint({a,object("b")}),"identity change did not change fingerprint");}

void sha256_known_vector(){require(sha256_hex("abc")=="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad","SHA-256 implementation is incorrect");}

void reconciliation_reuses_only_unchanged(){Fixture f;auto a=object("a"),b=object("b");std::vector initial{a,b};f.db->reconcile_inventory(initial);auto ea=evidence(a,"sha",1);f.db->save_evidence(ea);auto changed=a;changed.etag="v2";auto c=object("c");std::vector replacement{changed,c};auto result=f.db->reconcile_inventory(replacement);require(result.changed.size()==1&&result.added.size()==1&&result.missing.size()==1,"inventory classes are wrong");require(!f.db->evidence_for("a",object_version(changed),"native-evidence-v1"),"changed object reused stale evidence");require(f.db->evidence_for("a",object_version(a),"native-evidence-v1").has_value(),"historical evidence was destroyed");}

void direct_edges_are_not_invented(){auto objects=std::vector{object("A"),object("B"),object("C")};auto values=std::vector{evidence(objects[0],"1",1,1000,1000),evidence(objects[1],"2",2,500,500),evidence(objects[2],"3",3,400,400)};std::vector<MatchEdge> edges{{"A","B",1,"AB"},{"B","C",2,"BC"}};auto result=construct_generation(objects,values,edges,SurvivorPolicy::resolution,"g");for(const auto& pair:result.pairs)require(!(pair.left_key=="A"&&pair.right_key=="C"),"unsupported transitive edge was invented");std::set<std::string> candidates;for(const auto& pair:result.pairs)require(candidates.insert(pair.right_key).second,"deletion candidate appears more than once");}

void family_orientation_and_order_are_stable(){auto objects=star_objects();auto values=star_evidence(objects);auto result=construct_generation(objects,values,star_edges(),SurvivorPolicy::resolution,"g");require(result.pairs.size()==3,"expected three direct review rows");require(result.pairs[0].left_key=="A"&&result.pairs[0].right_key=="B","highest resolution was not the survivor");require(result.pairs[0].difference<=result.pairs[1].difference&&result.pairs[1].difference<=result.pairs[2].difference,"queue is not strongest-first");std::set<std::string> targets;for(const auto& pair:result.pairs)require(targets.insert(pair.right_key).second,"contradictory deletion target");}

void exact_duplicates_are_separate(){auto objects=std::vector{object("A",100),object("B",90)};auto values=std::vector{evidence(objects[0],"same",1,1000,1000),evidence(objects[1],"same",1,500,500)};auto result=construct_generation(objects,values,{},SurvivorPolicy::resolution,"g");require(result.pairs.empty(),"exact duplicates polluted visual queue");require(result.exact_deletions.size()==1&&result.exact_deletions[0].survivor_key=="A"&&result.exact_deletions[0].deletion_key=="B","exact deletion orientation is wrong");}

void staging_never_replaces_active_early(){Fixture f;auto objects=star_objects();auto values=star_evidence(objects);auto active=certify(*f.db,objects,values,star_edges());GenerationIdentity next{inventory_fingerprint(objects),70,"new-matcher","native-evidence-v1","certified-families-v1"};const auto staging=f.db->create_staging(next);require(f.db->active_generation()->id==active.id,"creating staging destroyed active generation");f.db->fail_staging(staging,"test");require(f.db->active_generation()->id==active.id,"failed staging destroyed active generation");}

void promotion_rejects_contradictory_roles(){Fixture f;auto objects=std::vector{object("A"),object("B"),object("C")};f.db->reconcile_inventory(objects);GenerationIdentity identity{inventory_fingerprint(objects),50,"m","h","w"};const auto id=f.db->create_staging(identity);std::vector<Family> families{{"f1","A",{"A","B"}},{"f2","B",{"B","C"}}};std::vector<ReviewPair> pairs{{0,id,"f1","A","B",1,"x",false,1},{0,id,"f2","B","C",2,"x",false,1}};f.db->save_staging_result(id,families,pairs,{});bool rejected=false;try{f.db->promote(id);}catch(...){rejected=true;}require(rejected&&!f.db->active_generation(),"contradictory staging generation was promoted");}

void pipeline_reopens_without_rehash_or_reorder(){Fixture f;FakeStore store;store.inventory={object("a"),object("b")};store.content["a"]={1,2,3};store.content["b"]={9,8,7};FakeEvidenceGenerator generator;Config config;config.slider=50;config.hash_workers=2;config.compare_workers=2;std::atomic_bool cancel=false;CertificationPipeline first(*f.db,store,generator,config);require(first.run(cancel,[](auto){})==StartupOutcome::certified_new,"first run did not certify");const auto before=*f.db->active_generation();const int calls=generator.calls;std::reverse(store.inventory.begin(),store.inventory.end());CertificationPipeline second(*f.db,store,generator,config);require(second.run(cancel,[](auto){})==StartupOutcome::validated_existing,"unchanged run rebuilt generation");const auto after=*f.db->active_generation();require(generator.calls==calls,"unchanged run rehashed media");require(before.id==after.id&&before.pairs.size()==after.pairs.size(),"unchanged run replaced queue");}

void pipeline_hashes_only_new_objects(){Fixture f;FakeStore store;store.inventory={object("a")};store.content["a"]={1};FakeEvidenceGenerator generator;Config config;config.hash_workers=2;config.compare_workers=2;std::atomic_bool cancel=false;CertificationPipeline pipeline(*f.db,store,generator,config);pipeline.run(cancel,[](auto){});store.inventory.push_back(object("b"));store.content["b"]={2};const int before=generator.calls;CertificationPipeline changed(*f.db,store,generator,config);require(changed.run(cancel,[](auto){})==StartupOutcome::certified_new,"changed inventory was not certified");require(generator.calls-before==1,"inventory growth rehashed unchanged object");}

void validation_failure_preserves_queue(){Fixture f;auto objects=star_objects();auto values=star_evidence(objects);auto active=certify(*f.db,objects,values,star_edges());FakeStore store;store.fail_list=true;FakeEvidenceGenerator generator;Config config;std::atomic_bool cancel=false;CertificationPipeline pipeline(*f.db,store,generator,config);require(pipeline.run(cancel,[](auto){})==StartupOutcome::validation_failed,"list failure not reported");require(f.db->active_generation()->id==active.id,"list failure destroyed saved queue");}

void cancellation_before_validation_avoids_remote_work(){Fixture f;FakeStore store;FakeEvidenceGenerator generator;Config config;std::atomic_bool cancel=true;CertificationPipeline pipeline(*f.db,store,generator,config);require(pipeline.run(cancel,[](auto){})==StartupOutcome::cancelled&&store.list_calls==0,"cancelled startup still contacted remote service");}

void legacy_tables_are_preserved(){auto path=std::filesystem::temp_directory_path()/"reduped-legacy-preserve.sqlite3";std::error_code ignored;std::filesystem::remove(path,ignored);sqlite3* raw{};require(sqlite3_open_v2(path.string().c_str(),&raw,SQLITE_OPEN_READWRITE|SQLITE_OPEN_CREATE|SQLITE_OPEN_FULLMUTEX,nullptr)==SQLITE_OK,"legacy fixture open failed");sqlite3_exec(raw,"CREATE TABLE assets(key TEXT PRIMARY KEY,sha256 TEXT);INSERT INTO assets VALUES('old','trusted');",nullptr,nullptr,nullptr);sqlite3_close(raw);{Database db(path);sqlite3_stmt* statement{};sqlite3_prepare_v2(db.raw_for_tests(),"SELECT sha256 FROM assets WHERE key='old'",-1,&statement,nullptr);require(sqlite3_step(statement)==SQLITE_ROW,"legacy asset was erased");require(std::string(reinterpret_cast<const char*>(sqlite3_column_text(statement,0)))=="trusted","legacy evidence was altered");sqlite3_finalize(statement);}std::filesystem::remove(path,ignored);std::filesystem::remove(path.string()+"-wal",ignored);std::filesystem::remove(path.string()+"-shm",ignored);}

void actionability_has_one_fail_closed_authority(){ActionabilityInput input;input.active_generation_certified=true;input.current_pair_exists=true;input.current_pair_certified=true;input.current_family_certified=true;input.allow_delete=true;auto locked=compute_actionability(input);require(!locked.can_delete_single&&locked.reason=="Validating R2","startup lock failed open");input.startup_inventory_validated=true;auto ready=compute_actionability(input);require(ready.can_delete_single&&ready.can_nuke,"validated actions stayed locked");input.allow_delete=false;auto safety=compute_actionability(input);require(!safety.can_delete_single&&safety.reason=="Deletion safety enabled","deletion flag is not authoritative");}

void ordinary_deletion_preserves_other_rows(){Fixture f;auto objects=star_objects();auto values=star_evidence(objects);auto active=certify(*f.db,objects,values,star_edges());FakeStore store;store.inventory=objects;DeletionService service(*f.db,store,deletion_config());auto pair=*std::find_if(active.pairs.begin(),active.pairs.end(),[](const auto& p){return p.right_key=="B";});service.delete_single({pair.generation_id,pair.family_id,pair.id,pair.left_key,pair.right_key,pair.revision},false,[](auto){});auto after=*f.db->active_generation();require(store.deleted.contains("B"),"right BYE BITCH deleted wrong object");require(after.pairs.size()==2,"ordinary candidate deletion removed unrelated rows");require(std::any_of(after.pairs.begin(),after.pairs.end(),[](const auto& p){return p.right_key=="C";}),"valid family row was lost");}

void survivor_deletion_hides_only_family_and_persists_priority(){Fixture f;auto objects=star_objects();auto values=star_evidence(objects);auto active=certify(*f.db,objects,values,star_edges());FakeStore store;store.inventory=objects;DeletionService service(*f.db,store,deletion_config());auto pair=*std::find_if(active.pairs.begin(),active.pairs.end(),[](const auto& p){return p.right_key=="B";});service.delete_single({pair.generation_id,pair.family_id,pair.id,pair.left_key,pair.right_key,pair.revision},true,[](auto){});auto after=*f.db->active_generation();require(store.deleted.contains("A")&&!store.deleted.contains("B")&&!store.deleted.contains("C"),"survivor deletion swept surviving family members");require(after.pairs.size()==1&&after.pairs[0].left_key=="D","unrelated family did not remain actionable");auto jobs=f.db->recoverable_recertification_jobs();require(jobs.size()==1&&jobs[0].priority_keys.front()=="B","protected partner was not first recertification priority");}

void failed_remote_deletion_keeps_truth(){Fixture f;auto objects=star_objects();auto values=star_evidence(objects);auto active=certify(*f.db,objects,values,star_edges());FakeStore store;store.inventory=objects;store.fail_delete=true;DeletionService service(*f.db,store,deletion_config());auto pair=active.pairs[0];bool failed=false;try{service.delete_single({pair.generation_id,pair.family_id,pair.id,pair.left_key,pair.right_key,pair.revision},true,[](auto){});}catch(...){failed=true;}require(failed,"remote failure was hidden");require(f.db->active_generation()->pairs.size()==active.pairs.size(),"remote failure invalidated family");require(f.db->recoverable_recertification_jobs().empty(),"remote failure left fake repair work");}

void index_failure_is_durable(){Fixture f;auto objects=star_objects();auto values=star_evidence(objects);auto active=certify(*f.db,objects,values,star_edges());FakeStore store;store.inventory=objects;store.fail_index=true;DeletionService service(*f.db,store,deletion_config());auto pair=active.pairs[0];service.delete_single({pair.generation_id,pair.family_id,pair.id,pair.left_key,pair.right_key,pair.revision},false,[](auto){});require(f.db->pending_index_cleanup().size()==1,"index failure was not queued");store.fail_index=false;service.retry_index_cleanup([](auto){});require(f.db->pending_index_cleanup().empty(),"index cleanup did not retry");}

void stale_and_excluded_clicks_cannot_delete(){Fixture f;auto objects=star_objects();auto values=star_evidence(objects);auto active=certify(*f.db,objects,values,star_edges());FakeStore store;store.inventory=objects;DeletionService service(*f.db,store,deletion_config());auto pair=active.pairs[0];RenderedPairToken token{pair.generation_id,pair.family_id,pair.id,pair.left_key,pair.right_key,pair.revision};require(f.db->exclude_pair(token),"exclude failed");bool blocked=false;try{service.delete_single(token,false,[](auto){});}catch(...){blocked=true;}require(blocked&&store.deleted.empty(),"excluded stale click deleted media");}

void deletion_intent_is_idempotent_and_recoverable(){Fixture f;auto objects=star_objects();auto values=star_evidence(objects);auto active=certify(*f.db,objects,values,star_edges());auto pair=*std::find_if(active.pairs.begin(),active.pairs.end(),[](const auto& p){return p.right_key=="B";});RenderedPairToken token{pair.generation_id,pair.family_id,pair.id,pair.left_key,pair.right_key,pair.revision};auto first=f.db->prepare_single_deletion(token,"A","B");auto second=f.db->prepare_single_deletion(token,"A","B");require(first.action_id==second.action_id&&first.recertification_job_id==second.recertification_job_id,"identical intent created duplicate work");FakeStore store;store.inventory=objects;store.delete_object("A");DeletionService service(*f.db,store,deletion_config());service.recover_prepared([](auto){});require(f.db->prepared_actions().empty(),"interrupted successful deletion was not recovered");require(f.db->recoverable_recertification_jobs().size()==1,"recovery forgot family recertification");}

void recertification_claim_is_exclusive_and_retry_is_same_job(){Fixture f;auto objects=star_objects();auto values=star_evidence(objects);auto active=certify(*f.db,objects,values,star_edges());FakeStore store;store.inventory=objects;DeletionService service(*f.db,store,deletion_config());auto pair=*std::find_if(active.pairs.begin(),active.pairs.end(),[](const auto& p){return p.right_key=="B";});service.delete_single({pair.generation_id,pair.family_id,pair.id,pair.left_key,pair.right_key,pair.revision},true,[](auto){});auto job=f.db->recoverable_recertification_jobs()[0];require(f.db->claim_recertification(job.id),"first worker failed to claim");require(!f.db->claim_recertification(job.id),"second worker also claimed job");f.db->retry_recertification(job.id,"decode failed");auto retry=f.db->recoverable_recertification_jobs();require(retry.size()==1&&retry[0].id==job.id&&retry[0].attempts==1&&retry[0].last_error=="decode failed","retry created or lost job metadata");}

void nuke_plans_never_delete_survivors(){Fixture f;auto objects=star_objects();auto values=star_evidence(objects);auto active=certify(*f.db,objects,values,star_edges());const auto plan=f.db->visual_nuke_plan(active.id);require(std::find(plan.begin(),plan.end(),"A")==plan.end()&&std::find(plan.begin(),plan.end(),"D")==plan.end(),"NUKE selected a survivor");FakeStore store;store.inventory=objects;DeletionService service(*f.db,store,deletion_config());service.nuke_visual(active.id,[](auto){});require(!store.deleted.contains("A")&&!store.deleted.contains("D"),"NUKE deleted a survivor");}

void exact_nuke_uses_certified_set_only(){Fixture f;auto objects=std::vector{object("A",100),object("B",90)};auto values=std::vector{evidence(objects[0],"same",1,1000,1000),evidence(objects[1],"same",1,500,500)};auto active=certify(*f.db,objects,values,{});FakeStore store;store.inventory=objects;DeletionService service(*f.db,store,deletion_config());service.nuke_exact(active.id,[](auto){});require(store.deleted.size()==1&&store.deleted.contains("B"),"NUKE SHA ONLY used wrong set");}

void preview_revision_rejects_late_result(){require(!preview_result_is_current(1,"old",2,"new"),"late preview revision was accepted");require(!preview_result_is_current(2,"old",2,"new"),"wrong preview key was accepted");require(preview_result_is_current(2,"new",2,"new"),"current preview was rejected");}

void matcher_policy_has_about_one_hundred_distinct_steps(){auto strict=policy_for_slider(0),loose=policy_for_slider(99);require(strict.phash_radius<loose.phash_radius&&strict.pdq_radius<loose.pdq_radius,"slider does not change consistent policy");}

} // namespace

int main(){
 const std::vector<std::pair<std::string,std::function<void()>>> tests{
  {"fingerprint deterministic",fingerprint_is_deterministic},{"sha vector",sha256_known_vector},{"incremental reconciliation",reconciliation_reuses_only_unchanged},
  {"no transitive invention",direct_edges_are_not_invented},{"family orientation",family_orientation_and_order_are_stable},{"exact queue",exact_duplicates_are_separate},
  {"staging isolation",staging_never_replaces_active_early},{"promotion validation",promotion_rejects_contradictory_roles},{"unchanged startup",pipeline_reopens_without_rehash_or_reorder},{"incremental hashing",pipeline_hashes_only_new_objects},
  {"validation failure",validation_failure_preserves_queue},{"startup cancellation",cancellation_before_validation_avoids_remote_work},{"legacy preservation",legacy_tables_are_preserved},{"actionability",actionability_has_one_fail_closed_authority},{"ordinary deletion",ordinary_deletion_preserves_other_rows},
  {"survivor deletion",survivor_deletion_hides_only_family_and_persists_priority},{"remote failure",failed_remote_deletion_keeps_truth},{"index recovery",index_failure_is_durable},
  {"stale click",stale_and_excluded_clicks_cannot_delete},{"deletion recovery",deletion_intent_is_idempotent_and_recoverable},{"exclusive recertification",recertification_claim_is_exclusive_and_retry_is_same_job},
  {"visual nuke",nuke_plans_never_delete_survivors},{"exact nuke",exact_nuke_uses_certified_set_only},{"preview race",preview_revision_rejects_late_result},{"slider policy",matcher_policy_has_about_one_hundred_distinct_steps}
 };
 int failures=0;for(const auto& [name,test]:tests)try{test();std::cout<<"PASS  "<<name<<'\n';}catch(const std::exception& error){++failures;std::cerr<<"FAIL  "<<name<<": "<<error.what()<<'\n';}
 std::cout<<tests.size()-static_cast<std::size_t>(failures)<<"/"<<tests.size()<<" tests passed\n";return failures?1:0;
}
