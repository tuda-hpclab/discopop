/*
 * This file is part of the DiscoPoP software
 * (http://www.discopop.tu-darmstadt.de)
 *
 * Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
 *
 * This software may be modified and distributed under the terms of
 * the 3-Clause BSD License. See the LICENSE file in the package base
 * directory for details.
 *
 */

#include <benchmark/benchmark.h>

#include <algorithm>
#include <cstdint>
#include <random>
#include <vector>

#include "../../profiler/rtlib/memory/MemoryRegionTree.hpp"

// General functions

static std::vector<ADDR> convert_to_address(const std::int64_t number_iterations) {
  auto mt = std::mt19937{0};
  auto uid = std::uniform_int_distribution<ADDR>{0, 0x7FFFFFFFFFFFFFFF};

  auto addresses = std::vector<ADDR>{};
  addresses.resize(number_iterations);

  for (auto i = std::int64_t(0); i < number_iterations; i++) {
    addresses[i] = uid(mt);
  }

  std::sort(addresses.begin(), addresses.end());

  return addresses;
}

// Benchmarks for old version (i.e., establishing a base line)

static void benchmark_mrt_allocate_region(benchmark::State &state) {
  const auto number_iterations = state.range(0);

  const auto addresses = convert_to_address(number_iterations * 2);

  // This exists so that the destructor call does not interfere with the timing
  auto dumping_ground = std::vector<__dp::MemoryRegionTree>{};

  for (auto _ : state) {
    state.PauseTiming();
    auto tree = __dp::MemoryRegionTree{};
    state.ResumeTiming();

    for (auto i = 0; i < number_iterations * 2; i += 2) {
      tree.allocate_region(addresses[i], addresses[i + 1], i + 1);
    }

    state.PauseTiming();
    dumping_ground.emplace_back(std::move(tree));
    state.ResumeTiming();
  }
}

static void benchmark_mrt_get_memory_region_id(benchmark::State &state) {
  const auto number_iterations = state.range(0);

  const auto addresses = convert_to_address(number_iterations * 2);

  auto tree = __dp::MemoryRegionTree{};

  for (auto i = 0; i < number_iterations * 2; i += 2) {
    tree.allocate_region(addresses[i], addresses[i + 1], i + 1);
  }

  for (auto _ : state) {
    for (auto i = 0; i < number_iterations * 2; i++) {
      benchmark::DoNotOptimize(tree.get_memory_region_id(addresses[i]));
    }
  }
}

static void benchmark_mrt_get_memory_region_id_string_found(benchmark::State &state) {
  const auto number_iterations = state.range(0);

  const auto addresses = convert_to_address(number_iterations * 2);

  auto tree = __dp::MemoryRegionTree{};

  for (auto i = 0; i < number_iterations * 2; i += 2) {
    tree.allocate_region(addresses[i], addresses[i + 1], i + 1);
  }

  // This exists so that the destructor call does not interfere with the timing
  auto dumping_ground = std::vector<std::string>{};
  dumping_ground.reserve(number_iterations);

  for (auto _ : state) {
    for (auto i = 0; i < number_iterations * 2; i++) {
      dumping_ground.emplace_back(tree.get_memory_region_id_string(addresses[i], "fallback"));
    }
  }
}

static void benchmark_mrt_get_memory_region_id_string_fallback(benchmark::State &state) {
  const auto number_iterations = state.range(0);

  const auto addresses = convert_to_address(number_iterations * 2);

  auto tree = __dp::MemoryRegionTree{};

  for (auto i = 0; i < number_iterations * 2; i += 2) {
    tree.allocate_region(addresses[i], addresses[i + 1], i + 1);
  }

  // This exists so that the destructor call does not interfere with the timing
  auto dumping_ground = std::vector<std::string>{};
  dumping_ground.reserve(number_iterations);

  for (auto _ : state) {
    for (auto i = 0; i < number_iterations * 2; i++) {
      const auto base_address = addresses[i];
      const auto address = (i % 2 == 0) ? base_address - 1 : base_address + 1;

      dumping_ground.emplace_back(tree.get_memory_region_id_string(address, "fallback"));
    }
  }
}

static void benchmark_mrt_destructor(benchmark::State &state) {
  const auto number_iterations = state.range(0);

  const auto addresses = convert_to_address(number_iterations * 2);

  for (auto _ : state) {
    state.PauseTiming();
    auto tree = __dp::MemoryRegionTree{};
    for (auto i = 0; i < number_iterations * 2; i += 2) {
      tree.allocate_region(addresses[i], addresses[i + 1], i + 1);
    }
    state.ResumeTiming();
  }
}

static void benchmark_mrt_free_region(benchmark::State &state) {
  const auto number_iterations = state.range(0);

  const auto addresses = convert_to_address(number_iterations * 2);

  // This exists so that the destructor call does not interfere with the timing
  auto dumping_ground = std::vector<__dp::MemoryRegionTree>{};

  auto tree = __dp::MemoryRegionTree{};

  for (auto i = 0; i < number_iterations * 2; i += 2) {
    tree.allocate_region(addresses[i], addresses[i + 1], i + 1);
  }

  for (auto _ : state) {
    state.PauseTiming();
    auto tree = __dp::MemoryRegionTree{};
    for (auto i = 0; i < number_iterations * 2; i += 2) {
      tree.allocate_region(addresses[i], addresses[i + 1], i + 1);
    }
    state.ResumeTiming();

    for (auto i = 0; i < number_iterations * 2; i += 2) {
      tree.free_region(addresses[i]);
    }

    state.PauseTiming();
    dumping_ground.emplace_back(std::move(tree));
    state.ResumeTiming();
  }
}

BENCHMARK(benchmark_mrt_allocate_region)->Unit(benchmark::kMillisecond)->Arg(32)->Iterations(100);
BENCHMARK(benchmark_mrt_allocate_region)->Unit(benchmark::kMillisecond)->Arg(1024)->Iterations(100);

BENCHMARK(benchmark_mrt_get_memory_region_id)->Unit(benchmark::kMillisecond)->Arg(32)->Iterations(100);
BENCHMARK(benchmark_mrt_get_memory_region_id)->Unit(benchmark::kMillisecond)->Arg(1024)->Iterations(100);

BENCHMARK(benchmark_mrt_get_memory_region_id_string_found)->Unit(benchmark::kMillisecond)->Arg(32)->Iterations(100);
BENCHMARK(benchmark_mrt_get_memory_region_id_string_found)->Unit(benchmark::kMillisecond)->Arg(1024)->Iterations(100);

BENCHMARK(benchmark_mrt_get_memory_region_id_string_fallback)->Unit(benchmark::kMillisecond)->Arg(32)->Iterations(100);
BENCHMARK(benchmark_mrt_get_memory_region_id_string_fallback)
    ->Unit(benchmark::kMillisecond)
    ->Arg(1024)
    ->Iterations(100);

BENCHMARK(benchmark_mrt_destructor)->Unit(benchmark::kMillisecond)->Arg(32)->Iterations(100);
BENCHMARK(benchmark_mrt_destructor)->Unit(benchmark::kMillisecond)->Arg(1024)->Iterations(100);

BENCHMARK(benchmark_mrt_free_region)->Unit(benchmark::kMillisecond)->Arg(32)->Iterations(100);
BENCHMARK(benchmark_mrt_free_region)->Unit(benchmark::kMillisecond)->Arg(1024)->Iterations(100);
