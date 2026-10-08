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

// BENCHMARK: new/delete, malloc/free, calloc and realloc
// Allocation heavy workload that hits every allocation site the pass instruments
// separately, and keeps the memory region bookkeeping churning.

#include <cstdint>
#include <cstdio>
#include <cstdlib>

static constexpr int kRounds = 64000;
static constexpr int kBlockElements = 64;

int main() {
  std::int64_t checksum = 0;

  for (int round = 0; round < kRounds; ++round) {
    int *from_new = new int[kBlockElements];
    for (int i = 0; i < kBlockElements; ++i) {
      from_new[i] = (round + i) % 31;
      checksum += from_new[i];
    }
    delete[] from_new;

    int *from_malloc = static_cast<int *>(malloc(kBlockElements * sizeof(int)));
    for (int i = 0; i < kBlockElements; ++i) {
      from_malloc[i] = (round * i) % 17;
      checksum += from_malloc[i];
    }

    int *from_realloc = static_cast<int *>(realloc(from_malloc, 2 * kBlockElements * sizeof(int)));
    for (int i = kBlockElements; i < 2 * kBlockElements; ++i) {
      from_realloc[i] = i % 7;
      checksum += from_realloc[i];
    }
    free(from_realloc);

    int *from_calloc = static_cast<int *>(calloc(kBlockElements, sizeof(int)));
    for (int i = 0; i < kBlockElements; ++i) {
      checksum += from_calloc[i];
    }
    free(from_calloc);
  }

  printf("checksum: %lld\n", static_cast<long long>(checksum));
  return 0;
}
