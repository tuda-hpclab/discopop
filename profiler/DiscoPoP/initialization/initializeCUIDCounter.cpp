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

#include <fcntl.h>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <string>
#include <sys/file.h>
#include <unistd.h>

#include "DiscoPoP.hpp"

void DiscoPoP::InitializeCuIdCounter() {
	cu_id_counter = 0;
}

unsigned int DiscoPoP::GetNextCuId() {
	constexpr unsigned int kCuIdRangeSize = 1000;

	if (cu_id_counter % kCuIdRangeSize == 0) {
		const std::string profiler_directory = dputil::GetEnvOrDefault("DOT_DISCOPOP_PROFILER", ".discopop/profiler");
		const std::string counter_file = profiler_directory + "/DP_CUIDCounter.txt";
		const std::string lock_file = dputil::ProfilerLockPath(profiler_directory, "DP_CUIDCounter.lock");

		const int lock = open(lock_file.c_str(), O_CREAT | O_RDWR, 0666);

		if (lock == -1) {
			throw std::runtime_error("Could not open CU-ID lock file: " + lock_file);
		}

		if (flock(lock, LOCK_EX) == -1) {
			close(lock);
			throw std::runtime_error("Could not acquire CU-ID lock: " + lock_file);
		}

		unsigned int next_id = 0;
		std::ifstream counter_input(counter_file);

		if (counter_input.is_open() && !(counter_input >> next_id)) {
			flock(lock, LOCK_UN);
			close(lock);
			throw std::runtime_error("Could not read CU-ID counter file: " + counter_file);
		}

		counter_input.close();

		if (next_id > std::numeric_limits<unsigned int>::max() - kCuIdRangeSize) {
			flock(lock, LOCK_UN);
			close(lock);
			throw std::overflow_error("CU-ID counter exhausted");
		}

		const unsigned int next_range_start = next_id + kCuIdRangeSize;
		std::ofstream counter_output(counter_file, std::ios_base::trunc);

		if (!counter_output.is_open()) {
			flock(lock, LOCK_UN);
			close(lock);
			throw std::runtime_error("Could not write CU-ID counter file: " + counter_file);
		}

		counter_output << next_range_start;
		counter_output.close();

		if (flock(lock, LOCK_UN) == -1) {
			close(lock);
			throw std::runtime_error("Could not release CU-ID lock: " + lock_file);
		}

		close(lock);
		cu_id_counter = next_id;
	}

	return cu_id_counter++;
}
