#include "reduped/algorithms.hpp"
#include "reduped/matcher.hpp"

#include <algorithm>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace reduped;

namespace {

void require(bool condition, std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}

Evidence video(std::string key, Hash256 hash, int quality) {
    Evidence e;
    e.key = std::move(key);
    e.sha256 = e.key;
    e.video_hashes = {hash};
    e.video_qualities = {quality};
    return e;
}

} // namespace

int main() {
    try {
        const auto loose = policy_for_slider(0);
        const auto strict = policy_for_slider(99);
        require(loose.phash_radius == 18 && strict.phash_radius == 6, "pHash slider endpoints changed");
        require(loose.pdq_radius == 48 && strict.pdq_radius == 23, "PDQ slider endpoints changed");
        require(loose.video_radius == 45 && strict.video_radius == 25, "vPDQ slider endpoints changed");
        require(loose.required_crop_fraction < strict.required_crop_fraction, "crop slider direction is backwards");
        require(loose.required_video_fraction < strict.required_video_fraction, "vPDQ slider direction is backwards");
        require(loose.minimum_similarity < strict.minimum_similarity, "minimum similarity slider direction is backwards");

        std::vector<std::uint8_t> gradient(96 * 96);
        for (int y = 0; y < 96; ++y) for (int x = 0; x < 96; ++x)
            gradient[static_cast<std::size_t>(y) * 96 + x] = static_cast<std::uint8_t>((x * 3 + y * 5) & 255);
        const auto hashes = compute_native_still_hashes(gradient, 96, 96);
        require(hashes.pdq_quality >= 0 && hashes.pdq_quality <= 100, "PDQ quality is out of range");
        require(!hashes.crop_hashes.empty(), "crop-resistant hashing produced no segments");
        require(imagehash_phash(gradient, 96, 96) == hashes.phash, "pHash wrapper is inconsistent");
        require(meta_pdq(gradient, 96, 96).first == hashes.pdq, "PDQ wrapper is inconsistent");

        const Hash256 same{1,2,3,4};
        auto good_a = video("a", same, 80);
        auto good_b = video("b", same, 80);
        auto edges = match_all(std::vector<Evidence>{good_a, good_b}, 50, 1);
        require(edges.size() == 1 && edges[0].reason == "vPDQ", "vPDQ did not match equal good-quality frame hashes");

        auto low_a = video("c", same, 20);
        auto low_b = video("d", same, 20);
        edges = match_all(std::vector<Evidence>{low_a, low_b}, 0, 1);
        require(edges.empty(), "vPDQ used frames below the quality floor");

        std::cout << "algorithm semantics passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
