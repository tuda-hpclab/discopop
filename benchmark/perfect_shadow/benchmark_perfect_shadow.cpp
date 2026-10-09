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

#include <cstdint>
#include <vector>

#include "../../profiler/rtlib/memory/PerfectShadow.hpp"

// General functions

static std::int64_t convert_to_address(const std::int64_t iteration) {
  return ((iteration * 17) + ((iteration + 4) % 5)) % 1024;
}

static bool test_read_address(const std::int64_t address) { return address & 1; }

static bool test_write_address(const std::int64_t address) { return address > 400; }

static bool insert_read_address(const std::int64_t address) { return address < 700; }

static bool insert_write_address(const std::int64_t address) { return address & 539; }

static bool update_read_address(const std::int64_t address) { return (address * 13) & 64; }

static bool update_write_address(const std::int64_t address) { return (address % 19) > 8; }

static bool remove_read_address(const std::int64_t address) { return address % 512 > 400; }

static bool remove_write_address(const std::int64_t address) { return (address & 384) < 49; }

// Benchmarks for old version (i.e., establishing a base line)

static void benchmark_perfect_shadow_test(benchmark::State &state) {
  const auto number_addresses = state.range(0);

  auto addresses = std::vector<std::int64_t>{};
  addresses.resize(number_addresses);

  for (auto i = std::int64_t(0); i < number_addresses; i++) {
    addresses[i] = convert_to_address(i);
  }

  // This exists so that the destructor call does not interfere with the timing
  auto dumping_ground = std::vector<__dp::PerfectShadow>{};

  for (auto _ : state) {
    state.PauseTiming();
    auto shadow = __dp::PerfectShadow{};
    state.ResumeTiming();

    for (auto addr : addresses) {
      std::ignore = shadow.testInRead(addr);
    }

    state.PauseTiming();
    dumping_ground.emplace_back(std::move(shadow));
    state.ResumeTiming();
  }
}

static void benchmark_perfect_shadow_insert(benchmark::State &state) {
  const auto number_addresses = state.range(0);

  auto addresses = std::vector<std::int64_t>{};
  addresses.resize(number_addresses);

  for (auto i = std::int64_t(0); i < number_addresses; i++) {
    addresses[i] = convert_to_address(i);
  }

  // This exists so that the destructor call does not interfere with the timing
  auto dumping_ground = std::vector<__dp::PerfectShadow>{};

  for (auto _ : state) {
    state.PauseTiming();
    auto shadow = __dp::PerfectShadow{};
    state.ResumeTiming();

    for (auto addr : addresses) {
      std::ignore = shadow.insertToRead(addr, 1);
    }

    state.PauseTiming();
    dumping_ground.emplace_back(std::move(shadow));
    state.ResumeTiming();
  }
}

static void benchmark_perfect_shadow_update(benchmark::State &state) {
  const auto number_addresses = state.range(0);

  auto addresses = std::vector<std::int64_t>{};
  addresses.resize(number_addresses);

  for (auto i = std::int64_t(0); i < number_addresses; i++) {
    addresses[i] = convert_to_address(i);
  }

  // This exists so that the destructor call does not interfere with the timing
  auto dumping_ground = std::vector<__dp::PerfectShadow>{};

  for (auto _ : state) {
    state.PauseTiming();
    auto shadow = __dp::PerfectShadow{};
    state.ResumeTiming();

    for (auto addr : addresses) {
      shadow.updateInRead(addr, 1);
    }

    state.PauseTiming();
    dumping_ground.emplace_back(std::move(shadow));
    state.ResumeTiming();
  }
}

static void benchmark_perfect_shadow_remove(benchmark::State &state) {
  const auto number_addresses = state.range(0);

  auto addresses = std::vector<std::int64_t>{};
  addresses.resize(number_addresses);

  for (auto i = std::int64_t(0); i < number_addresses; i++) {
    addresses[i] = convert_to_address(i);
  }

  // This exists so that the destructor call does not interfere with the timing
  auto dumping_ground = std::vector<__dp::PerfectShadow>{};

  for (auto _ : state) {
    state.PauseTiming();
    auto shadow = __dp::PerfectShadow{};
    state.ResumeTiming();

    for (auto addr : addresses) {
      shadow.removeFromRead(addr);
    }

    state.PauseTiming();
    dumping_ground.emplace_back(std::move(shadow));
    state.ResumeTiming();
  }
}

static void benchmark_perfect_shadow(benchmark::State &state) {
  const auto number_addresses = state.range(0);

  auto addresses = std::vector<std::int64_t>{};
  addresses.resize(number_addresses);

  for (auto i = std::int64_t(0); i < number_addresses; i++) {
    addresses[i] = convert_to_address(i);
  }

  // This exists so that the destructor call does not interfere with the timing
  auto dumping_ground = std::vector<__dp::PerfectShadow>{};

  for (auto _ : state) {
    state.PauseTiming();
    auto shadow = __dp::PerfectShadow{};
    state.ResumeTiming();

    for (auto addr : addresses) {
      if (test_read_address(addr)) {
        std::ignore = shadow.testInRead(addr);
      }

      if (test_write_address(addr)) {
        std::ignore = shadow.testInWrite(addr);
      }

      if (insert_read_address(addr)) {
        std::ignore = shadow.insertToRead(addr, 1);
      }

      if (insert_write_address(addr)) {
        std::ignore = shadow.insertToWrite(addr, 2);
      }

      if (update_read_address(addr)) {
        shadow.updateInRead(addr, 3);
      }

      if (update_write_address(addr)) {
        shadow.updateInWrite(addr, 4);
      }

      if (remove_read_address(addr)) {
        shadow.removeFromRead(addr);
      }

      if (remove_write_address(addr)) {
        shadow.removeFromWrite(addr);
      }
    }

    state.PauseTiming();
    dumping_ground.emplace_back(std::move(shadow));
    state.ResumeTiming();
  }
}

// Benchmarks for new version (i.e., hopefully beating the base line)

static void benchmark_perfect_shadow_2_test(benchmark::State &state) {
  const auto number_addresses = state.range(0);

  auto addresses = std::vector<std::int64_t>{};
  addresses.resize(number_addresses);

  for (auto i = std::int64_t(0); i < number_addresses; i++) {
    addresses[i] = convert_to_address(i);
  }

  // This exists so that the destructor call does not interfere with the timing
  auto dumping_ground = std::vector<__dp::PerfectShadow2>{};

  for (auto _ : state) {
    state.PauseTiming();
    auto shadow = __dp::PerfectShadow2{};
    state.ResumeTiming();

    for (auto addr : addresses) {
      std::ignore = shadow.testInRead(addr);
    }

    state.PauseTiming();
    dumping_ground.emplace_back(std::move(shadow));
    state.ResumeTiming();
  }
}

static void benchmark_perfect_shadow_2_insert(benchmark::State &state) {
  const auto number_addresses = state.range(0);

  auto addresses = std::vector<std::int64_t>{};
  addresses.resize(number_addresses);

  for (auto i = std::int64_t(0); i < number_addresses; i++) {
    addresses[i] = convert_to_address(i);
  }

  // This exists so that the destructor call does not interfere with the timing
  auto dumping_ground = std::vector<__dp::PerfectShadow2>{};

  for (auto _ : state) {
    state.PauseTiming();
    auto shadow = __dp::PerfectShadow2{};
    state.ResumeTiming();

    for (auto addr : addresses) {
      std::ignore = shadow.insertToRead(addr, 1);
    }

    state.PauseTiming();
    dumping_ground.emplace_back(std::move(shadow));
    state.ResumeTiming();
  }
}

static void benchmark_perfect_shadow_2_update(benchmark::State &state) {
  const auto number_addresses = state.range(0);

  auto addresses = std::vector<std::int64_t>{};
  addresses.resize(number_addresses);

  for (auto i = std::int64_t(0); i < number_addresses; i++) {
    addresses[i] = convert_to_address(i);
  }

  // This exists so that the destructor call does not interfere with the timing
  auto dumping_ground = std::vector<__dp::PerfectShadow2>{};

  for (auto _ : state) {
    state.PauseTiming();
    auto shadow = __dp::PerfectShadow2{};
    state.ResumeTiming();

    for (auto addr : addresses) {
      shadow.updateInRead(addr, 1);
    }

    state.PauseTiming();
    dumping_ground.emplace_back(std::move(shadow));
    state.ResumeTiming();
  }
}

static void benchmark_perfect_shadow_2_remove(benchmark::State &state) {
  const auto number_addresses = state.range(0);

  auto addresses = std::vector<std::int64_t>{};
  addresses.resize(number_addresses);

  for (auto i = std::int64_t(0); i < number_addresses; i++) {
    addresses[i] = convert_to_address(i);
  }

  // This exists so that the destructor call does not interfere with the timing
  auto dumping_ground = std::vector<__dp::PerfectShadow2>{};

  for (auto _ : state) {
    state.PauseTiming();
    auto shadow = __dp::PerfectShadow2{};
    state.ResumeTiming();

    for (auto addr : addresses) {
      shadow.removeFromRead(addr);
    }

    state.PauseTiming();
    dumping_ground.emplace_back(std::move(shadow));
    state.ResumeTiming();
  }
}

static void benchmark_perfect_shadow_2(benchmark::State &state) {
  const auto number_addresses = state.range(0);

  auto addresses = std::vector<std::int64_t>{};
  addresses.resize(number_addresses);

  for (auto i = std::int64_t(0); i < number_addresses; i++) {
    addresses[i] = convert_to_address(i);
  }

  // This exists so that the destructor call does not interfere with the timing
  auto dumping_ground = std::vector<__dp::PerfectShadow2>{};

  for (auto _ : state) {
    state.PauseTiming();
    auto shadow = __dp::PerfectShadow2{};
    state.ResumeTiming();

    for (auto addr : addresses) {
      if (test_read_address(addr)) {
        std::ignore = shadow.testInRead(addr);
      }

      if (test_write_address(addr)) {
        std::ignore = shadow.testInWrite(addr);
      }

      if (insert_read_address(addr)) {
        std::ignore = shadow.insertToRead(addr, 1);
      }

      if (insert_write_address(addr)) {
        std::ignore = shadow.insertToWrite(addr, 2);
      }

      if (update_read_address(addr)) {
        shadow.updateInRead(addr, 3);
      }

      if (update_write_address(addr)) {
        shadow.updateInWrite(addr, 4);
      }

      if (remove_read_address(addr)) {
        shadow.removeFromRead(addr);
      }

      if (remove_write_address(addr)) {
        shadow.removeFromWrite(addr);
      }
    }

    state.PauseTiming();
    dumping_ground.emplace_back(std::move(shadow));
    state.ResumeTiming();
  }
}

// The sorting determines the output order --> put pairs together so a
// comparison is easier

BENCHMARK(benchmark_perfect_shadow_test)->Unit(benchmark::kMillisecond)->Arg(1024)->Iterations(100);
BENCHMARK(benchmark_perfect_shadow_2_test)->Unit(benchmark::kMillisecond)->Arg(1024)->Iterations(100);
BENCHMARK(benchmark_perfect_shadow_test)->Unit(benchmark::kMillisecond)->Arg(1024 * 64)->Iterations(100);
BENCHMARK(benchmark_perfect_shadow_2_test)->Unit(benchmark::kMillisecond)->Arg(1024 * 64)->Iterations(100);

BENCHMARK(benchmark_perfect_shadow_insert)->Unit(benchmark::kMillisecond)->Arg(1024)->Iterations(100);
BENCHMARK(benchmark_perfect_shadow_2_insert)->Unit(benchmark::kMillisecond)->Arg(1024)->Iterations(100);
BENCHMARK(benchmark_perfect_shadow_insert)->Unit(benchmark::kMillisecond)->Arg(1024 * 64)->Iterations(100);
BENCHMARK(benchmark_perfect_shadow_2_insert)->Unit(benchmark::kMillisecond)->Arg(1024 * 64)->Iterations(100);

BENCHMARK(benchmark_perfect_shadow_update)->Unit(benchmark::kMillisecond)->Arg(1024)->Iterations(100);
BENCHMARK(benchmark_perfect_shadow_2_update)->Unit(benchmark::kMillisecond)->Arg(1024)->Iterations(100);
BENCHMARK(benchmark_perfect_shadow_update)->Unit(benchmark::kMillisecond)->Arg(1024 * 64)->Iterations(100);
BENCHMARK(benchmark_perfect_shadow_2_update)->Unit(benchmark::kMillisecond)->Arg(1024 * 64)->Iterations(100);

BENCHMARK(benchmark_perfect_shadow_remove)->Unit(benchmark::kMillisecond)->Arg(1024)->Iterations(100);
BENCHMARK(benchmark_perfect_shadow_2_remove)->Unit(benchmark::kMillisecond)->Arg(1024)->Iterations(100);
BENCHMARK(benchmark_perfect_shadow_remove)->Unit(benchmark::kMillisecond)->Arg(1024 * 64)->Iterations(100);
BENCHMARK(benchmark_perfect_shadow_2_remove)->Unit(benchmark::kMillisecond)->Arg(1024 * 64)->Iterations(100);

BENCHMARK(benchmark_perfect_shadow)->Unit(benchmark::kMillisecond)->Arg(1024)->Iterations(100);
BENCHMARK(benchmark_perfect_shadow_2)->Unit(benchmark::kMillisecond)->Arg(1024)->Iterations(100);
BENCHMARK(benchmark_perfect_shadow)->Unit(benchmark::kMillisecond)->Arg(1024 * 64)->Iterations(100);
BENCHMARK(benchmark_perfect_shadow_2)->Unit(benchmark::kMillisecond)->Arg(1024 * 64)->Iterations(100);
