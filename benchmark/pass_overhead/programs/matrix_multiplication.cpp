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

// BENCHMARK: Dense matrix multiplication, load/store bound
// Dominated by array loads and stores inside a perfectly nested loop, i.e. by the
// load/store instrumentation.

#include <cstdio>
#include <vector>

static constexpr int kSize = 160;

int main() {
  auto a = std::vector<double>(kSize * kSize);
  auto b = std::vector<double>(kSize * kSize);
  auto c = std::vector<double>(kSize * kSize, 0.0);

  for (int i = 0; i < kSize; ++i) {
    for (int j = 0; j < kSize; ++j) {
      a[i * kSize + j] = static_cast<double>((i + 1) % 7);
      b[i * kSize + j] = static_cast<double>((j + 2) % 5);
    }
  }

  for (int i = 0; i < kSize; ++i) {
    for (int j = 0; j < kSize; ++j) {
      double sum = 0.0;
      for (int k = 0; k < kSize; ++k) {
        sum += a[i * kSize + k] * b[k * kSize + j];
      }
      c[i * kSize + j] = sum;
    }
  }

  double checksum = 0.0;
  for (int i = 0; i < kSize * kSize; ++i) {
    checksum += c[i];
  }

  printf("checksum: %.1f\n", checksum);
  return 0;
}
