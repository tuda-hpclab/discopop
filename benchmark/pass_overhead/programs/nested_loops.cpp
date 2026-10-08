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

// BENCHMARK: Triple nested loops with data dependent control flow
// The loop entry/exit instrumentation and the call path tracking are the dominant
// cost here, while only a handful of memory regions are touched.

#include <cstdint>
#include <cstdio>

static constexpr int kOuter = 256;
static constexpr int kMiddle = 256;
static constexpr int kInner = 256;

int main() {
  std::int64_t accumulator = 0;
  std::int64_t skipped = 0;

  for (int i = 0; i < kOuter; ++i) {
    for (int j = 0; j < kMiddle; ++j) {
      if (((i + j) % 3) == 0) {
        ++skipped;
        continue;
      }
      for (int k = 0; k < kInner; ++k) {
        accumulator += (i * j + k) % 13;
      }
    }
  }

  printf("accumulator: %lld skipped: %lld\n", static_cast<long long>(accumulator), static_cast<long long>(skipped));
  return 0;
}
