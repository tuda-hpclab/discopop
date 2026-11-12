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

void DiscoPoP::InitializeInstructionIdCounter() {
    instruction_id_counter = 2;
}

uint32_t DiscoPoP::GetNextInstructionId() {
    constexpr uint32_t kInstructionIdRangeSize = 4000;

    if (instruction_id_counter == 2 || (instruction_id_counter - 2) % kInstructionIdRangeSize == 0) {
        const std::string profiler_directory = dputil::GetEnvOrDefault("DOT_DISCOPOP_PROFILER", ".discopop/profiler");
        const std::string counter_file = profiler_directory + "/DP_InstructionIDCounter.txt";
        const std::string lock_file = dputil::ProfilerLockPath(profiler_directory, "DP_InstructionIDCounter.lock");
        const int lock = open(lock_file.c_str(), O_CREAT | O_RDWR, 0666);

        if (lock == -1) {
            throw std::runtime_error("Could not open instruction-ID lock file: " + lock_file);
        }

        if (flock(lock, LOCK_EX) == -1) {
            close(lock);
            throw std::runtime_error("Could not acquire instruction-ID lock: " + lock_file);
        }

        uint32_t next_id = 2;
        std::ifstream counter_input(counter_file);

        if (counter_input.is_open() && !(counter_input >> next_id)) {
            flock(lock, LOCK_UN);
            close(lock);
            throw std::runtime_error("Could not read instruction-ID counter file: " + counter_file);
        }

        if (next_id > std::numeric_limits<uint32_t>::max() - kInstructionIdRangeSize) {
            flock(lock, LOCK_UN);
            close(lock);
            throw std::overflow_error("Instruction-ID counter exhausted");
        }

        const uint32_t next_range_end = next_id + kInstructionIdRangeSize;
        std::ofstream counter_output(counter_file, std::ios_base::trunc);

        if (!counter_output.is_open()) {
            flock(lock, LOCK_UN);
            close(lock);
            throw std::runtime_error("Could not write instruction-ID counter file: " + counter_file);
        }

        counter_output << next_range_end;
        counter_output.close();

        if (flock(lock, LOCK_UN) == -1) {
            close(lock);
            throw std::runtime_error("Could not release instruction-ID lock: " + lock_file);
        }

        close(lock);
        instruction_id_counter = next_id;
    }

    return instruction_id_counter++;
}
