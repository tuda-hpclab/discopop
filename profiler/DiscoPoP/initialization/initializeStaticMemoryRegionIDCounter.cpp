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

void DiscoPoP::InitializeStaticMemoryRegionIDCounter() {
    static_memory_region_id_counter = 0;
}

uint32_t DiscoPoP::GetNextStaticMemoryRegionId() {
    constexpr uint32_t kStaticMemoryRegionIdRangeSize = 4000;

    if (static_memory_region_id_counter % kStaticMemoryRegionIdRangeSize == 0) {
        const std::string profiler_directory = dputil::GetEnvOrDefault("DOT_DISCOPOP_PROFILER", ".discopop/profiler");
        const std::string counter_file = profiler_directory + "/DP_StaticMemoryRegionIDCounter.txt";
        const std::string lock_file = dputil::ProfilerLockPath(profiler_directory, "DP_StaticMemoryRegionIDCounter.lock");
        const int lock = open(lock_file.c_str(), O_CREAT | O_RDWR, 0666);

        if (lock == -1) {
            throw std::runtime_error("Could not open static memory-region lock file: " + lock_file);
        }

        if (flock(lock, LOCK_EX) == -1) {
            close(lock);
            throw std::runtime_error("Could not acquire static memory-region lock: " + lock_file);
        }

        uint32_t next_id = 0;
        std::ifstream counter_input(counter_file);

        if (counter_input.is_open() && !(counter_input >> next_id)) {
            flock(lock, LOCK_UN);
            close(lock);
            throw std::runtime_error("Could not read static memory-region counter file: " + counter_file);
        }

        counter_input.close();

        if (next_id > std::numeric_limits<uint32_t>::max() - kStaticMemoryRegionIdRangeSize) {
            flock(lock, LOCK_UN);
            close(lock);
            throw std::overflow_error("Static memory-region counter exhausted");
        }

        const uint32_t next_range_start = next_id + kStaticMemoryRegionIdRangeSize;
        std::ofstream counter_output(counter_file, std::ios_base::trunc);

        if (!counter_output.is_open()) {
            flock(lock, LOCK_UN);
            close(lock);
            throw std::runtime_error("Could not write static memory-region counter file: " + counter_file);
        }

        counter_output << next_range_start;
        counter_output.close();

        if (flock(lock, LOCK_UN) == -1) {
            close(lock);
            throw std::runtime_error("Could not release static memory-region lock: " + lock_file);
        }

        close(lock);
        static_memory_region_id_counter = next_id;
    }

    return static_memory_region_id_counter++;
}
