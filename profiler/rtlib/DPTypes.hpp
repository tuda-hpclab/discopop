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

// Number of bits for holding LID
#define LIDSIZE 14

// Number of bits for holding LID Metadata (Column + Loop ID + LoopIteration)
#define LIDMETADATASIZE 32

// Maximum number of lines in a single file. Has to be 2^LIDSIZE.
#define MAXLNO 16384

// #define SKIP_DUP_INSTR 1

typedef std::int64_t LID;
typedef std::int64_t ADDR;
typedef std::int64_t sigElement;

// TODO(Lukas): Is this valid?
#define USE_EMHASH

#ifdef USE_EMHASH
#include "../third_party/emhash/hash_set8.hpp"
#include "../third_party/emhash/hash_table7.hpp"
namespace __dp {
template <typename KeyT, typename ValueT> using hashmap = emhash7::HashMap<KeyT, ValueT>;
template <typename KeyT> using hashset = emhash8::HashSet<KeyT>;
} // namespace __dp
#else
#include <unordered_map>
#include <unordered_set>
namespace __dp {
template <typename KeyT, typename ValueT> using hashmap = std::unordered_map<KeyT, ValueT>;
template <typename KeyT> using hashset = std::unordered_set<KeyT>;
} // namespace __dp
#endif
