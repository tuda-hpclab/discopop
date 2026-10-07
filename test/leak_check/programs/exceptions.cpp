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

// Exception workload for the profiler leak check (scripts/dev/check_profiler_leaks.sh).
//
// Per time step, exceptions are thrown out of nested calls and loops and caught again, so the runtime
// library's landing pad handling (__dp_landing_pad) and its unwinding of function and loop stacks run once
// per throw. Memory the runtime loses or keeps per exception grows with the number of steps.
//
// usage: exceptions [steps]   (default: 200)

#include <cstdlib>
#include <stdexcept>
#include <vector>

static int depth_sum = 0;

static void level2(std::vector<int> &values, int step) {
  for (std::size_t i = 0; i < values.size(); ++i) {
    values[i] += step;
    if (i == values.size() / 2 && step % 2 == 0) {
      throw std::runtime_error("even step");
    }
  }
}

static void level1(std::vector<int> &values, int step) {
  std::vector<int> local(8, step);
  for (int repeat = 0; repeat < 2; ++repeat) {
    level2(values, step + local[repeat]);
  }
  depth_sum += local[0];
}

int main(int argc, char **argv) {
  int steps = 200;
  if (argc > 1) {
    steps = std::atoi(argv[1]);
  }
  std::vector<int> values(64, 0);
  int caught = 0;
  for (int step = 0; step < steps; ++step) {
    try {
      level1(values, step);
    } catch (const std::runtime_error &) {
      ++caught;
    }
    try {
      for (int i = 0; i < 4; ++i) {
        if (values[i] > step + 1000000) {
          break;
        }
        if (i == 3) {
          throw 42;
        }
      }
    } catch (int) {
      ++caught;
    }
  }
  return caught > 0 && depth_sum >= 0 ? 0 : 1;
}
