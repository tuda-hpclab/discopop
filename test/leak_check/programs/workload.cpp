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

// Workload for the profiler leak check (scripts/dev/check_profiler_leaks.sh).
//
// It repeats the same accesses on a small, fixed working set for a configurable number of time steps,
// so the profiler processes many access chunks (100000 accesses each) while the set of distinct
// dependencies stays constant. Memory the runtime library loses per chunk, per call, per loop
// iteration or per allocation therefore grows with the number of steps, which is the shape of the
// per-chunk dependency set leak fixed in c8786941. The program itself frees everything it allocates.
//
// usage: workload [steps]   (default: 40)

#include <cstdlib>
#include <vector>

static const int N = 2000;

static double stencil(const double *in, double *out, int n) {
  double sum = 0.0;
  for (int i = 1; i < n - 1; ++i) {
    out[i] = 0.25 * in[i - 1] + 0.5 * in[i] + 0.25 * in[i + 1];
    sum += out[i];
  }
  return sum;
}

static long histogram(const std::vector<int> &keys, std::vector<long> &bins) {
  long total = 0;
  for (std::size_t i = 0; i < keys.size(); ++i) {
    bins[keys[i] % bins.size()] += 1;
    total += keys[i];
  }
  return total;
}

int main(int argc, char **argv) {
  int steps = 40;
  if (argc > 1) {
    steps = std::atoi(argv[1]);
  }

  double *a = new double[N];
  double *b = new double[N];
  for (int i = 0; i < N; ++i) {
    a[i] = i % 7;
    b[i] = 0.0;
  }
  std::vector<int> keys(N);
  for (int i = 0; i < N; ++i) {
    keys[i] = (i * 31) % 97;
  }
  std::vector<long> bins(16, 0);

  double checksum = 0.0;
  for (int step = 0; step < steps; ++step) {
    checksum += stencil(a, b, N);
    checksum += stencil(b, a, N);
    checksum += histogram(keys, bins);

    // short-lived heap memory, freed again in the same step (new[]/delete[] and malloc/free)
    double *scratch = new double[64];
    int *flags = static_cast<int *>(std::malloc(32 * sizeof(int)));
    for (int i = 0; i < 64; ++i) {
      scratch[i] = a[i] + step;
    }
    for (int i = 0; i < 32; ++i) {
      flags[i] = static_cast<int>(scratch[2 * i]) & 1;
      checksum += flags[i];
    }
    std::free(flags);
    delete[] scratch;
  }

  delete[] a;
  delete[] b;
  return checksum < 0.0 ? 1 : 0;
}
