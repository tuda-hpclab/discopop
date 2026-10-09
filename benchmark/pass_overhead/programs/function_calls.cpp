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

// BENCHMARK: Many small calls plus recursion
// Every iteration crosses several function boundaries, so the function entry
// instrumentation and the static call path tracking dominate.

#include <cstdint>
#include <cstdio>

static constexpr int kIterations = 3000000;

static std::int64_t leaf(std::int64_t value) { return (value * 3) % 101; }

static std::int64_t middle(std::int64_t value) { return leaf(value) + leaf(value + 1); }

static std::int64_t outer(std::int64_t value) { return middle(value) + middle(value + 2); }

static std::int64_t recursive_sum(int depth) {
  if (depth <= 0) {
    return 0;
  }
  return depth + recursive_sum(depth - 1);
}

int main() {
  std::int64_t accumulator = 0;

  for (int i = 0; i < kIterations; ++i) {
    accumulator += outer(i);
  }

  for (int i = 0; i < 30000; ++i) {
    accumulator += recursive_sum(20);
  }

  printf("accumulator: %lld\n", static_cast<long long>(accumulator));
  return 0;
}
