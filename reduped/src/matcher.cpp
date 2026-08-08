#include "reduped/matcher.hpp"

#include <algorithm>
#include <atomic>
#include <bit>
#include <cmath>
#include <set>
#include <thread>
#include <tuple>
#include <unordered_set>

namespace reduped {
namespace {

struct Score {
    bool matched{};
    double similarity{};
    std::string reason;
};

double crop_similarity(const Evidence& a,const Evidence& b,double radius){
    if(a.crop_hashes.empty()||b.crop_hashes.empty())return 0.0;
    const auto fraction=[&](const auto& left,const auto& right){
        std::size_t matched=0;
        for(const auto value:left){unsigned closest=65;for(const auto other:right)closest=std::min(closest,hamming(value,other));if(static_cast<double>(closest)<=radius)++matched;}
        return static_cast<double>(matched)/static_cast<double>(left.size());
    };
    return 100.0*std::min(fraction(a.crop_hashes,b.crop_hashes),fraction(b.crop_hashes,a.crop_hashes));
}

std::vector<std::pair<Hash256,int>> quality_frames(const Evidence& evidence){
    std::vector<std::pair<Hash256,int>> out;
    std::set<Hash256> seen;
    for(std::size_t i=0;i<evidence.video_hashes.size();++i){const int quality=i<evidence.video_qualities.size()?evidence.video_qualities[i]:100;if(quality<35)continue;if(seen.insert(evidence.video_hashes[i]).second)out.push_back({evidence.video_hashes[i],quality});}
    return out;
}

std::pair<double,double> vpdq_similarity(const Evidence& a,const Evidence& b,unsigned radius){
    const auto left=quality_frames(a),right=quality_frames(b);if(left.empty()||right.empty())return {0.0,0.0};
    const auto fraction=[&](const auto& source,const auto& target){std::size_t matched=0;for(const auto& feature:source){if(std::any_of(target.begin(),target.end(),[&](const auto& other){return hamming(feature.first,other.first)<=radius;}))++matched;}return static_cast<double>(matched)/source.size();};
    return {fraction(left,right),fraction(right,left)};
}

Score score_pair(const Evidence& a,const Evidence& b,const MatchPolicy& policy){
    double best=0.0;std::string reason;bool crop_qualified=false;
    const bool animated_or_video=!a.video_hashes.empty()||!b.video_hashes.empty();
    if(!animated_or_video&&a.phash&&b.phash){const auto distance=hamming(*a.phash,*b.phash);if(distance<=policy.phash_radius){const double score=100.0*(1.0-static_cast<double>(distance)/64.0);if(score>best){best=score;reason="pHash";}}}
    if(!animated_or_video&&a.pdq&&b.pdq){const auto distance=hamming(*a.pdq,*b.pdq);if(distance<=policy.pdq_radius){const double score=100.0*(1.0-static_cast<double>(distance)/256.0);if(score>best){best=score;reason="Meta PDQ";}}}
    if(!animated_or_video){const double score=crop_similarity(a,b,policy.crop_radius);crop_qualified=score/100.0>=policy.required_crop_fraction;if(crop_qualified&&score>best){best=score;reason="crop-resistant";}}
    if(!a.video_hashes.empty()&&!b.video_hashes.empty()){
        const auto [left,right]=vpdq_similarity(a,b,policy.video_radius);const double fraction=std::min(left,right);if(fraction>=policy.required_video_fraction){const double score=100.0*fraction;if(score>best){best=score;reason="vPDQ";}}
    }
    const bool matched=crop_qualified||best>=policy.minimum_similarity;
    return {matched,best,reason};
}

} // namespace

MatchPolicy policy_for_slider(int slider){
    slider=std::clamp(slider,0,99);const double strictness=static_cast<double>(slider)/99.0;
    return {
        static_cast<unsigned>(std::lround(18.0-strictness*12.0)),
        static_cast<unsigned>(std::lround(48.0-strictness*25.0)),
        18.0-strictness*10.0,
        0.25+strictness*0.35,
        static_cast<unsigned>(std::lround(45.0-strictness*20.0)),
        0.45+strictness*0.40,
        58.0+strictness*29.0
    };
}

unsigned hamming(std::uint64_t left,std::uint64_t right){return std::popcount(left^right);}
unsigned hamming(const Hash256& left,const Hash256& right){return hamming(left[0],right[0])+hamming(left[1],right[1])+hamming(left[2],right[2])+hamming(left[3],right[3]);}

std::vector<MatchEdge> match_all(std::span<const Evidence> evidence,int slider,unsigned workers,std::atomic_bool* cancelled){
    const auto policy=policy_for_slider(slider);workers=std::max(1u,workers);std::atomic_size_t next{0};constexpr std::size_t chunk=16;std::vector<std::vector<MatchEdge>> local(workers);std::vector<std::thread> threads;threads.reserve(workers);
    for(unsigned worker=0;worker<workers;++worker)threads.emplace_back([&,worker]{auto& edges=local[worker];while(!cancelled||!cancelled->load(std::memory_order_relaxed)){const auto begin=next.fetch_add(chunk,std::memory_order_relaxed);if(begin>=evidence.size())break;const auto end=std::min(evidence.size(),begin+chunk);for(std::size_t i=begin;i<end;++i)for(std::size_t j=i+1;j<evidence.size();++j){if(!evidence[i].sha256.empty()&&evidence[i].sha256==evidence[j].sha256)continue;const auto score=score_pair(evidence[i],evidence[j],policy);if(score.matched){auto left=evidence[i].key,right=evidence[j].key;if(right<left)std::swap(left,right);edges.push_back({std::move(left),std::move(right),100.0-score.similarity,score.reason});}}}});
    for(auto& thread:threads)thread.join();if(cancelled&&cancelled->load())return {};std::vector<MatchEdge> result;std::size_t count=0;for(const auto& edges:local)count+=edges.size();result.reserve(count);for(auto& edges:local)result.insert(result.end(),std::make_move_iterator(edges.begin()),std::make_move_iterator(edges.end()));std::sort(result.begin(),result.end(),[](const auto& a,const auto& b){return std::tie(a.left,a.right,a.difference,a.reason)<std::tie(b.left,b.right,b.difference,b.reason);});result.erase(std::unique(result.begin(),result.end(),[](const auto& a,const auto& b){return a.left==b.left&&a.right==b.right;}),result.end());return result;
}

} // namespace reduped
