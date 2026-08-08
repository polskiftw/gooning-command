#include "reduped/fingerprint.hpp"

#include <algorithm>
#include <array>
#include <cstring>
#include <iomanip>
#include <sstream>

namespace reduped {
namespace {

constexpr std::array<std::uint32_t, 64> constants{
    0x428a2f98U,0x71374491U,0xb5c0fbcfU,0xe9b5dba5U,0x3956c25bU,0x59f111f1U,0x923f82a4U,0xab1c5ed5U,
    0xd807aa98U,0x12835b01U,0x243185beU,0x550c7dc3U,0x72be5d74U,0x80deb1feU,0x9bdc06a7U,0xc19bf174U,
    0xe49b69c1U,0xefbe4786U,0x0fc19dc6U,0x240ca1ccU,0x2de92c6fU,0x4a7484aaU,0x5cb0a9dcU,0x76f988daU,
    0x983e5152U,0xa831c66dU,0xb00327c8U,0xbf597fc7U,0xc6e00bf3U,0xd5a79147U,0x06ca6351U,0x14292967U,
    0x27b70a85U,0x2e1b2138U,0x4d2c6dfcU,0x53380d13U,0x650a7354U,0x766a0abbU,0x81c2c92eU,0x92722c85U,
    0xa2bfe8a1U,0xa81a664bU,0xc24b8b70U,0xc76c51a3U,0xd192e819U,0xd6990624U,0xf40e3585U,0x106aa070U,
    0x19a4c116U,0x1e376c08U,0x2748774cU,0x34b0bcb5U,0x391c0cb3U,0x4ed8aa4aU,0x5b9cca4fU,0x682e6ff3U,
    0x748f82eeU,0x78a5636fU,0x84c87814U,0x8cc70208U,0x90befffaU,0xa4506cebU,0xbef9a3f7U,0xc67178f2U};

std::uint32_t rotate(std::uint32_t value, unsigned count) {
    return (value >> count) | (value << (32U - count));
}

std::array<std::uint8_t, 32> digest(std::span<const std::uint8_t> input) {
    std::vector<std::uint8_t> data(input.begin(), input.end());
    const std::uint64_t bit_length = static_cast<std::uint64_t>(data.size()) * 8U;
    data.push_back(0x80U);
    while ((data.size() % 64U) != 56U) data.push_back(0);
    for (int shift = 56; shift >= 0; shift -= 8) data.push_back(static_cast<std::uint8_t>(bit_length >> shift));

    std::array<std::uint32_t, 8> hash{0x6a09e667U,0xbb67ae85U,0x3c6ef372U,0xa54ff53aU,
                                     0x510e527fU,0x9b05688cU,0x1f83d9abU,0x5be0cd19U};
    for (std::size_t offset = 0; offset < data.size(); offset += 64) {
        std::array<std::uint32_t, 64> words{};
        for (std::size_t i = 0; i < 16; ++i) {
            words[i] = (static_cast<std::uint32_t>(data[offset+i*4]) << 24U) |
                       (static_cast<std::uint32_t>(data[offset+i*4+1]) << 16U) |
                       (static_cast<std::uint32_t>(data[offset+i*4+2]) << 8U) |
                       static_cast<std::uint32_t>(data[offset+i*4+3]);
        }
        for (std::size_t i = 16; i < 64; ++i) {
            const auto s0 = rotate(words[i-15],7) ^ rotate(words[i-15],18) ^ (words[i-15] >> 3U);
            const auto s1 = rotate(words[i-2],17) ^ rotate(words[i-2],19) ^ (words[i-2] >> 10U);
            words[i] = words[i-16] + s0 + words[i-7] + s1;
        }
        auto a=hash[0],b=hash[1],c=hash[2],d=hash[3],e=hash[4],f=hash[5],g=hash[6],h=hash[7];
        for (std::size_t i = 0; i < 64; ++i) {
            const auto s1=rotate(e,6)^rotate(e,11)^rotate(e,25);
            const auto ch=(e&f)^((~e)&g);
            const auto t1=h+s1+ch+constants[i]+words[i];
            const auto s0=rotate(a,2)^rotate(a,13)^rotate(a,22);
            const auto maj=(a&b)^(a&c)^(b&c);
            const auto t2=s0+maj;
            h=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2;
        }
        hash[0]+=a; hash[1]+=b; hash[2]+=c; hash[3]+=d;
        hash[4]+=e; hash[5]+=f; hash[6]+=g; hash[7]+=h;
    }
    std::array<std::uint8_t,32> result{};
    for (std::size_t i=0;i<hash.size();++i) for(int shift=24,j=0;shift>=0;shift-=8,++j)
        result[i*4+static_cast<std::size_t>(j)]=static_cast<std::uint8_t>(hash[i]>>shift);
    return result;
}

} // namespace

std::string sha256_hex(std::span<const std::uint8_t> bytes) {
    const auto value = digest(bytes);
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (const auto byte : value) out << std::setw(2) << static_cast<unsigned>(byte);
    return out.str();
}

std::string sha256_hex(std::string_view text) {
    return sha256_hex(std::span(reinterpret_cast<const std::uint8_t*>(text.data()), text.size()));
}

std::string object_version(const ObjectRecord& object) {
    return sha256_hex(object.key + "\n" + std::to_string(object.size) + "\n" + object.etag + "\n" + object.last_modified);
}

std::string inventory_fingerprint(std::vector<ObjectRecord> inventory) {
    std::sort(inventory.begin(), inventory.end(), [](const auto& a, const auto& b) { return a.key < b.key; });
    std::string canonical;
    for (const auto& object : inventory) {
        canonical += std::to_string(object.key.size()) + ":" + object.key + "|" +
                     std::to_string(object.size) + "|" + object.etag + "|" + object.last_modified + "\n";
    }
    return sha256_hex(canonical);
}

std::string stable_id(std::string_view type, std::span<const std::string> parts) {
    std::string canonical(type);
    for (const auto& part : parts) canonical += "\n" + std::to_string(part.size()) + ":" + part;
    return sha256_hex(canonical).substr(0, 32);
}

} // namespace reduped
