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

// Multi-threaded workload for the profiler leak check (scripts/dev/check_profiler_leaks.sh), profiled with a
// runtime library built with DP_PTHREAD_COMPATIBILITY_MODE=1 (the default build does not support targets
// that call the runtime from several threads).
//
// The target starts its own threads: per time step, THREADS std::threads each update a private slice of a
// shared array (no data races in the target), and the main thread joins them. Thread creation and exit, and
// calls into the runtime from several threads, happen once per step, so memory the runtime loses or keeps
// per thread grows with the number of steps.
//
// No loop iterates while the target's threads run: the threads recurse instead of looping, and the main
// thread starts and joins them recursively. __dp_loop_incr is not serialized in DP_PTHREAD_COMPATIBILITY_MODE,
// so concurrent loops crash the runtime (heap-buffer-overflow in LoopCounter::incr_loop_counter).
//
// usage: threads [steps]   (default: 20)

#include <cstdlib>
#include <thread>
#include <vector>

static const int THREADS = 4;
static const int SLICE = 400;

static void work(double *data, int index, int step) {
  if (index >= SLICE) {
    return;
  }
  data[index] = 0.5 * data[index - 1] + data[index] + step;
  work(data, index + 1, step);
}

static void start(std::vector<std::thread> &threads, double *data, int thread, int step) {
  if (thread >= THREADS) {
    return;
  }
  threads.emplace_back(work, data + thread * SLICE, 1, step);
  start(threads, data, thread + 1, step);
}

static void join(std::vector<std::thread> &threads, std::size_t thread) {
  if (thread >= threads.size()) {
    return;
  }
  threads[thread].join();
  join(threads, thread + 1);
}

int main(int argc, char **argv) {
  int steps = 20;
  if (argc > 1) {
    steps = std::atoi(argv[1]);
  }
  std::vector<double> data(THREADS * SLICE, 1.0);
  for (int step = 0; step < steps; ++step) {
    std::vector<std::thread> threads;
    threads.reserve(THREADS);
    start(threads, data.data(), 0, step);
    join(threads, 0);
  }
  return data[SLICE - 1] < 0.0 ? 1 : 0;
}
