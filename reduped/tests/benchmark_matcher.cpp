#include "reduped/matcher.hpp"

#include <chrono>
#include <cstdlib>
#include <iostream>
#include <random>
#include <thread>
#include <vector>

int main(int argc,char** argv){const std::size_t count=argc>1?std::stoull(argv[1]):80000;std::vector<reduped::Evidence> evidence;evidence.reserve(count);std::mt19937_64 random(42);for(std::size_t i=0;i<count;++i){reduped::Evidence item;item.key=std::to_string(i);item.sha256=std::to_string(i);item.phash=random();item.pdq=reduped::Hash256{random(),random(),random(),random()};item.pdq_quality=80;evidence.push_back(std::move(item));}const auto begin=std::chrono::steady_clock::now();const auto edges=reduped::match_all(evidence,50,std::thread::hardware_concurrency());const double seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-begin).count();const double pairs=count>1?static_cast<double>(count)*(count-1)/2:0;std::cout<<"records="<<count<<" seconds="<<seconds<<" million_pairs_per_second="<<(pairs/seconds/1000000.0)<<" edges="<<edges.size()<<'\n';return 0;}
