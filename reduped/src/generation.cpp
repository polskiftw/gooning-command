#include "reduped/generation.hpp"

#include "reduped/fingerprint.hpp"
#include "reduped/matcher.hpp"

#include <algorithm>
#include <map>
#include <numeric>
#include <set>
#include <tuple>
#include <unordered_map>
#include <unordered_set>

namespace reduped {
namespace {

struct UnionFind {
    std::vector<std::size_t> parent;
    explicit UnionFind(std::size_t n):parent(n){std::iota(parent.begin(),parent.end(),0);}
    std::size_t find(std::size_t i){while(parent[i]!=i){parent[i]=parent[parent[i]];i=parent[i];}return i;}
    void join(std::size_t a,std::size_t b){a=find(a);b=find(b);if(a!=b)parent[b]=a;}
};

const ObjectRecord& object_for(const std::unordered_map<std::string,const ObjectRecord*>& objects,const std::string& key){return *objects.at(key);}
const Evidence& evidence_for(const std::unordered_map<std::string,const Evidence*>& evidence,const std::string& key){return *evidence.at(key);}

auto survivor_rank(const ObjectRecord& object,const Evidence& evidence,SurvivorPolicy policy){
    const std::int64_t pixels=static_cast<std::int64_t>(evidence.width)*evidence.height;
    switch(policy){
      case SurvivorPolicy::file_size:return std::tuple{static_cast<std::int64_t>(object.size),pixels,evidence.pdq_quality,object.last_modified,object.key};
      case SurvivorPolicy::oldest:return std::tuple{pixels,static_cast<std::int64_t>(object.size),evidence.pdq_quality,std::string(32,'z')+object.last_modified,object.key};
      case SurvivorPolicy::newest:return std::tuple{pixels,static_cast<std::int64_t>(object.size),evidence.pdq_quality,object.last_modified,object.key};
      default:return std::tuple{pixels,static_cast<std::int64_t>(object.size),evidence.pdq_quality,object.last_modified,object.key};
    }
}

std::string choose_survivor(const std::vector<std::string>& keys,const auto& objects,const auto& evidence,SurvivorPolicy policy){
    return *std::max_element(keys.begin(),keys.end(),[&](const auto& a,const auto& b){
        if(policy==SurvivorPolicy::oldest){const auto& oa=object_for(objects,a);const auto& ob=object_for(objects,b);if(oa.last_modified!=ob.last_modified)return oa.last_modified>ob.last_modified;}
        return survivor_rank(object_for(objects,a),evidence_for(evidence,a),policy)<survivor_rank(object_for(objects,b),evidence_for(evidence,b),policy);
    });
}

} // namespace

GenerationResult construct_generation(std::span<const ObjectRecord> objects,std::span<const Evidence> evidence,
                                      std::span<const MatchEdge> edges,SurvivorPolicy policy,std::string_view generation_id){
    GenerationResult result;
    std::unordered_map<std::string,const ObjectRecord*> object_map;for(const auto& o:objects)object_map[o.key]=&o;
    std::unordered_map<std::string,const Evidence*> evidence_map;for(const auto& e:evidence)if(object_map.contains(e.key))evidence_map[e.key]=&e;

    std::unordered_set<std::string> exact_removed;
    std::map<std::string,std::vector<std::string>> exact_groups;
    for(const auto& e:evidence)if(!e.sha256.empty()&&object_map.contains(e.key))exact_groups[e.sha256].push_back(e.key);
    for(auto& [sha,keys]:exact_groups)if(keys.size()>1){std::sort(keys.begin(),keys.end());const auto survivor=choose_survivor(keys,object_map,evidence_map,policy);for(const auto& key:keys)if(key!=survivor){result.exact_deletions.push_back({survivor,key});exact_removed.insert(key);}}

    std::unordered_map<std::string,std::size_t> index;std::vector<std::string> keys;
    for(const auto& edge:edges)for(const auto* key:{&edge.left,&edge.right})if(!exact_removed.contains(*key)&&evidence_map.contains(*key)&&!index.contains(*key)){index[*key]=keys.size();keys.push_back(*key);}
    UnionFind uf(keys.size());for(const auto& edge:edges)if(index.contains(edge.left)&&index.contains(edge.right))uf.join(index[edge.left],index[edge.right]);
    std::map<std::size_t,std::vector<std::string>> components;for(std::size_t i=0;i<keys.size();++i)components[uf.find(i)].push_back(keys[i]);
    std::map<std::pair<std::string,std::string>,const MatchEdge*> edge_map;for(const auto& edge:edges){auto a=edge.left,b=edge.right;if(b<a)std::swap(a,b);edge_map[{a,b}]=&edge;}

    for(auto& [root,component]:components){
        std::set<std::string> remaining(component.begin(),component.end());
        while(remaining.size()>1){
            std::string hub;std::vector<std::string> hub_neighbors;
            for(const auto& candidate:remaining){std::vector<std::string> neighbors;for(const auto& other:remaining)if(candidate!=other){auto a=candidate,b=other;if(b<a)std::swap(a,b);if(edge_map.contains({a,b}))neighbors.push_back(other);}
                if(neighbors.size()>hub_neighbors.size()||(neighbors.size()==hub_neighbors.size()&&!neighbors.empty()&&(hub.empty()||survivor_rank(object_for(object_map,candidate),evidence_for(evidence_map,candidate),policy)>survivor_rank(object_for(object_map,hub),evidence_for(evidence_map,hub),policy)))){hub=candidate;hub_neighbors=std::move(neighbors);}}
            if(hub_neighbors.empty())break;
            std::vector<std::string> star{hub};star.insert(star.end(),hub_neighbors.begin(),hub_neighbors.end());
            const auto survivor=choose_survivor(star,object_map,evidence_map,policy);
            std::vector<std::string> direct;for(const auto& member:star)if(member!=survivor){auto a=member,b=survivor;if(b<a)std::swap(a,b);if(edge_map.contains({a,b}))direct.push_back(member);}
            if(direct.empty()){remaining.erase(hub);continue;}
            std::vector<std::string> family_members{survivor};std::sort(direct.begin(),direct.end());family_members.insert(family_members.end(),direct.begin(),direct.end());
            auto id_parts=family_members;id_parts.push_back(std::string(generation_id));const auto family_id=stable_id("family",id_parts);
            result.families.push_back({family_id,survivor,family_members});
            for(const auto& candidate:direct){auto a=survivor,b=candidate;if(b<a)std::swap(a,b);const auto* edge=edge_map.at({a,b});result.pairs.push_back({0,std::string(generation_id),family_id,survivor,candidate,edge->difference,edge->reason,false,1});}
            remaining.erase(survivor);for(const auto& candidate:direct)remaining.erase(candidate);
        }
    }
    std::sort(result.pairs.begin(),result.pairs.end(),[](const auto& a,const auto& b){return std::tie(a.difference,a.family_id,a.right_key)<std::tie(b.difference,b.family_id,b.right_key);});
    std::sort(result.exact_deletions.begin(),result.exact_deletions.end(),[](const auto& a,const auto& b){return a.deletion_key<b.deletion_key;});
    return result;
}

GenerationResult recertify_family(std::span<const ObjectRecord> objects,std::span<const Evidence> evidence,int slider,unsigned workers,SurvivorPolicy policy,std::string_view generation_id){
    auto edges=match_all(evidence,slider,workers);return construct_generation(objects,evidence,edges,policy,generation_id);
}

} // namespace reduped
