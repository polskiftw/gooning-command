#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#if defined(_MSC_VER)
#include <intrin.h>
#endif

struct Record {
    std::uint64_t phash;
    std::uint64_t pdq[4];
    std::uint8_t flags;
    std::uint8_t padding[7];
};

static_assert(sizeof(Record) == 48, "Unexpected record layout");

static inline unsigned popcount64(std::uint64_t value) noexcept {
#if defined(_MSC_VER)
    return static_cast<unsigned>(__popcnt64(value));
#else
    return static_cast<unsigned>(__builtin_popcountll(value));
#endif
}

struct Totals {
    std::uint64_t phash_pairs = 0;
    std::uint64_t pdq_pairs = 0;
    std::uint64_t either_pairs = 0;
    std::uint64_t comparisons = 0;
    std::uint64_t checksum = 0;
};

static std::vector<Record> load_records(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        throw std::runtime_error("Could not open benchmark input: " + path);
    }

    char magic[8]{};
    std::uint64_t count = 0;
    input.read(magic, sizeof(magic));
    input.read(reinterpret_cast<char*>(&count), sizeof(count));
    if (!input || std::memcmp(magic, "GPHBEN01", 8) != 0) {
        throw std::runtime_error("Invalid benchmark input header");
    }

    std::vector<Record> records(static_cast<std::size_t>(count));
    if (count > 0) {
        input.read(reinterpret_cast<char*>(records.data()), static_cast<std::streamsize>(count * sizeof(Record)));
    }
    if (!input) {
        throw std::runtime_error("Benchmark input is truncated");
    }
    return records;
}

int main(int argc, char** argv) {
    try {
        if (argc < 2) {
            std::cerr << "Usage: hamming_benchmark.exe INPUT [PHASH_RADIUS] [PDQ_RADIUS] [THREADS]\n";
            return 2;
        }

        const std::string input_path = argv[1];
        const unsigned phash_radius = argc >= 3 ? static_cast<unsigned>(std::stoul(argv[2])) : 18U;
        const unsigned pdq_radius = argc >= 4 ? static_cast<unsigned>(std::stoul(argv[3])) : 48U;
        unsigned thread_count = argc >= 5 ? static_cast<unsigned>(std::stoul(argv[4])) : std::thread::hardware_concurrency();
        if (thread_count == 0) thread_count = 1;

        const auto records = load_records(input_path);
        const std::uint64_t n = static_cast<std::uint64_t>(records.size());
        const std::uint64_t theoretical_pairs = n > 1 ? (n * (n - 1)) / 2 : 0;

        std::cout << "\nNative exhaustive Hamming benchmark\n";
        std::cout << "Records       : " << n << "\n";
        std::cout << "Pair slots    : " << theoretical_pairs << "\n";
        std::cout << "pHash radius  : " << phash_radius << "\n";
        std::cout << "PDQ radius    : " << pdq_radius << "\n";
        std::cout << "Threads       : " << thread_count << "\n\n";

        constexpr std::uint64_t row_chunk = 32;
        std::atomic<std::uint64_t> next_row{0};
        std::atomic<std::uint64_t> rows_done{0};
        std::atomic<bool> finished{false};
        std::vector<Totals> local(thread_count);

        const auto started = std::chrono::steady_clock::now();
        std::thread reporter([&]() {
            unsigned last_percent = 0;
            while (!finished.load(std::memory_order_relaxed)) {
                std::this_thread::sleep_for(std::chrono::seconds(1));
                const auto done = rows_done.load(std::memory_order_relaxed);
                const unsigned percent = n == 0 ? 100U : static_cast<unsigned>((done * 100) / n);
                if (percent >= last_percent + 5 || percent == 100) {
                    const auto elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
                    std::cout << "Progress      : " << std::setw(3) << percent << "%  (" << std::fixed << std::setprecision(1) << elapsed << " s)\n";
                    last_percent = percent;
                }
            }
        });

        std::vector<std::thread> workers;
        workers.reserve(thread_count);
        for (unsigned worker_id = 0; worker_id < thread_count; ++worker_id) {
            workers.emplace_back([&, worker_id]() {
                Totals& totals = local[worker_id];
                while (true) {
                    const std::uint64_t begin = next_row.fetch_add(row_chunk, std::memory_order_relaxed);
                    if (begin >= n) break;
                    const std::uint64_t end = std::min(n, begin + row_chunk);

                    for (std::uint64_t i = begin; i < end; ++i) {
                        const Record& left = records[static_cast<std::size_t>(i)];
                        for (std::uint64_t j = i + 1; j < n; ++j) {
                            const Record& right = records[static_cast<std::size_t>(j)];
                            bool phash_match = false;
                            bool pdq_match = false;

                            if ((left.flags & 1U) && (right.flags & 1U)) {
                                const unsigned distance = popcount64(left.phash ^ right.phash);
                                phash_match = distance <= phash_radius;
                                totals.checksum += distance;
                            }

                            if ((left.flags & 2U) && (right.flags & 2U)) {
                                const unsigned distance =
                                    popcount64(left.pdq[0] ^ right.pdq[0]) +
                                    popcount64(left.pdq[1] ^ right.pdq[1]) +
                                    popcount64(left.pdq[2] ^ right.pdq[2]) +
                                    popcount64(left.pdq[3] ^ right.pdq[3]);
                                pdq_match = distance <= pdq_radius;
                                totals.checksum += distance;
                            }

                            totals.phash_pairs += static_cast<std::uint64_t>(phash_match);
                            totals.pdq_pairs += static_cast<std::uint64_t>(pdq_match);
                            totals.either_pairs += static_cast<std::uint64_t>(phash_match || pdq_match);
                            ++totals.comparisons;
                        }
                    }
                    rows_done.fetch_add(end - begin, std::memory_order_relaxed);
                }
            });
        }

        for (auto& worker : workers) worker.join();
        finished.store(true, std::memory_order_relaxed);
        reporter.join();

        Totals totals;
        for (const Totals& item : local) {
            totals.phash_pairs += item.phash_pairs;
            totals.pdq_pairs += item.pdq_pairs;
            totals.either_pairs += item.either_pairs;
            totals.comparisons += item.comparisons;
            totals.checksum += item.checksum;
        }

        const double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
        const double rate = seconds > 0.0 ? static_cast<double>(totals.comparisons) / seconds : 0.0;

        std::cout << "\nResults\n";
        std::cout << "Elapsed       : " << std::fixed << std::setprecision(3) << seconds << " seconds\n";
        std::cout << "Comparisons   : " << totals.comparisons << "\n";
        std::cout << "Rate          : " << std::fixed << std::setprecision(2) << (rate / 1'000'000.0) << " million pairs/sec\n";
        std::cout << "pHash matches : " << totals.phash_pairs << "\n";
        std::cout << "PDQ matches   : " << totals.pdq_pairs << "\n";
        std::cout << "Either matches: " << totals.either_pairs << "\n";
        std::cout << "Checksum      : " << totals.checksum << "\n";
        return 0;
    } catch (const std::exception& exc) {
        std::cerr << "ERROR: " << exc.what() << "\n";
        return 1;
    }
}
