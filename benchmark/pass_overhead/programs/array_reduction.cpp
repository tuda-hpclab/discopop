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

// BENCHMARK: Repeated reductions over a flat array
// Exercises the reduction recognition of the pass and produces a long stream of
// reads from a single, large memory region.

#include <cstdint>
#include <cstdio>
#include <vector>

static constexpr int kElements = 200000;
static constexpr int kSweeps = 20;

int main() {
  auto values = std::vector<std::int64_t>(kElements);
  for (int i = 0; i < kElements; ++i) {
    values[i] = (i * 17) % 1024;
  }

  std::int64_t sum = 0;
  std::int64_t maximum = 0;
  for (int sweep = 0; sweep < kSweeps; ++sweep) {
    for (int i = 0; i < kElements; ++i) {
      sum += values[i];
      if (values[i] > maximum) {
        maximum = values[i];
      }
    }
  }

  printf("sum: %lld max: %lld\n", static_cast<long long>(sum), static_cast<long long>(maximum));
  return 0;
}
