#include "reduped/matcher.hpp"

#include <algorithm>
#include <atomic>
#include <bit>
#include <cmath>
#include <limits>
#include <mutex>
#include <thread>

namespace reduped {
namespace {

struct Score {
    bool matched{};
    double difference{100.0};
    std::string reason;
};

Score score_pair(const Evidence& a, const Evidence& b, const MatchPolicy& policy) {
    Score best;
    auto consider = [&](bool match, double difference, std::string reason) {
        if (match && (!best.matched || difference < best.difference)) {
            best = {true, difference, std::move(reason)};
        }
    };
    if (a.phash && b.phash) {
        const auto distance = hamming(*a.phash, *b.phash);
        consider(distance <= policy.phash_radius, static_cast<double>(distance) * 100.0 / 64.0, "pHash");
    }
    if (a.pdq && b.pdq && a.pdq_quality >= policy.minimum_pdq_quality && b.pdq_quality >= policy.minimum_pdq_quality) {
        const auto distance = hamming(*a.pdq, *b.pdq);
        consider(distance <= policy.pdq_radius, static_cast<double>(distance) * 100.0 / 256.0, "PDQ");
    }
    if (!a.crop_hashes.empty() && !b.crop_hashes.empty()) {
        unsigned closest = 65;
        for (const auto left : a.crop_hashes) for (const auto right : b.crop_hashes)
            closest = std::min(closest, hamming(left, right));
        consider(closest <= policy.crop_radius, static_cast<double>(closest) * 100.0 / 64.0, "crop-resistant");
    }
    if (!a.video_hashes.empty() && !b.video_hashes.empty()) {
        auto matched_fraction = [&](const auto& left, const auto& right) {
            std::size_t matched = 0;
            double total_best = 0;
            for (const auto& frame : left) {
                unsigned closest = 257;
                for (const auto& other : right) closest = std::min(closest, hamming(frame, other));
                if (closest <= policy.video_radius) ++matched;
                total_best += closest;
            }
            return std::pair{static_cast<double>(matched) / static_cast<double>(left.size()),
                             total_best / static_cast<double>(left.size())};
        };
        const auto forward = matched_fraction(a.video_hashes, b.video_hashes);
        const auto reverse = matched_fraction(b.video_hashes, a.video_hashes);
        const double fraction = std::min(forward.first, reverse.first);
        const double distance = std::max(forward.second, reverse.second);
        consider(fraction >= policy.required_video_fraction && distance <= policy.video_radius,
                 distance * 100.0 / 256.0, "video frames");
    }
    return best;
}

} // namespace

MatchPolicy policy_for_slider(int slider) {
    slider = std::clamp(slider, 0, 99);
    const auto interpolate = [slider](unsigned strict, unsigned loose) {
        return strict + static_cast<unsigned>((loose - strict) * slider / 99);
    };
    return {interpolate(2, 20), interpolate(8, 64), interpolate(3, 18),
            interpolate(10, 64), 0.72 - (0.42 * static_cast<double>(slider) / 99.0), 20};
}

unsigned hamming(std::uint64_t left, std::uint64_t right) { return std::popcount(left ^ right); }
unsigned hamming(const Hash256& left, const Hash256& right) {
    return hamming(left[0],right[0])+hamming(left[1],right[1])+hamming(left[2],right[2])+hamming(left[3],right[3]);
}

std::vector<MatchEdge> match_all(std::span<const Evidence> evidence, int slider,
                                 unsigned workers, std::atomic_bool* cancelled) {
    const auto policy = policy_for_slider(slider);
    workers = std::max(1u, workers);
    std::atomic_size_t next{0};
    constexpr std::size_t chunk = 16;
    std::vector<std::vector<MatchEdge>> local(workers);
    std::vector<std::thread> threads;
    threads.reserve(workers);
    for (unsigned worker=0;worker<workers;++worker) threads.emplace_back([&,worker]{
        auto& edges=local[worker];
        while(!cancelled || !cancelled->load(std::memory_order_relaxed)){
            const auto begin=next.fetch_add(chunk,std::memory_order_relaxed);
            if(begin>=evidence.size())break;
            const auto end=std::min(evidence.size(),begin+chunk);
            for(std::size_t i=begin;i<end;++i)for(std::size_t j=i+1;j<evidence.size();++j){
                if(!evidence[i].sha256.empty()&&evidence[i].sha256==evidence[j].sha256)continue;
                const auto score=score_pair(evidence[i],evidence[j],policy);
                if(score.matched){auto left=evidence[i].key,right=evidence[j].key;if(right<left)std::swap(left,right);edges.push_back({std::move(left),std::move(right),score.difference,score.reason});}
            }
        }
    });
    for(auto& thread:threads)thread.join();
    if(cancelled&&cancelled->load())return {};
    std::vector<MatchEdge> result;
    std::size_t count=0;for(const auto& edges:local)count+=edges.size();result.reserve(count);
    for(auto& edges:local)result.insert(result.end(),std::make_move_iterator(edges.begin()),std::make_move_iterator(edges.end()));
    std::sort(result.begin(),result.end(),[](const auto& a,const auto& b){return std::tie(a.left,a.right,a.difference,a.reason)<std::tie(b.left,b.right,b.difference,b.reason);});
    result.erase(std::unique(result.begin(),result.end(),[](const auto& a,const auto& b){return a.left==b.left&&a.right==b.right;}),result.end());
    return result;
}

} // namespace reduped
