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

#pragma once
#include <cstdint>

extern unsigned int cu_id_counter;
extern unsigned int bb_dep_count;
extern unsigned int instruction_id_counter;
extern unsigned int callpath_state_id_counter;
extern unsigned int static_memory_region_id_counter;
extern bool default_is_global_variable_value;
extern std::int32_t file_id;
