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

#include "../DPUtils.hpp"
#include "../runtimeFunctionsTypes.hpp"
#include "CallTreeNode.hpp"
#include <boost/functional/hash.hpp>
#include <memory>

namespace __dp {

class MetaDataQueueElement {
public:
  MetaDataQueueElement(depType arg_type, LID arg_sink, LID arg_source, const char *arg_var, std::int64_t arg_AAvar,
                       shared_ptr<CallTreeNode> arg_sink_ctn, shared_ptr<CallTreeNode> arg_source_ctn);
  bool operator==(const MetaDataQueueElement &other) const;
  string toString();
  depType type;
  LID sink;
  LID source;
  const char *var;
  std::int64_t AAvar;
  shared_ptr<CallTreeNode> sink_ctn;
  shared_ptr<CallTreeNode> source_ctn;
};
} // namespace __dp

template <> struct std::hash<__dp::MetaDataQueueElement> {
  std::size_t operator()(const __dp::MetaDataQueueElement &k) const {
    using boost::hash_combine;
    using boost::hash_value;

    // Start with a hash value of 0    .
    std::size_t seed = 0;

    // Modify 'seed' by XORing and bit-shifting in
    // one member of 'Key' after the other:
    hash_combine(seed, hash_value(k.type));
    hash_combine(seed, hash_value(k.sink));
    hash_combine(seed, hash_value(k.source));
    hash_combine(seed, hash_value(k.var));
    hash_combine(seed, hash_value(k.AAvar));
    hash_combine(seed, hash_value(k.sink_ctn->get_node_type()));
    hash_combine(seed, hash_value(k.sink_ctn->get_loop_or_function_id()));
    hash_combine(seed, hash_value(k.sink_ctn->get_iteration_id()));
    hash_combine(seed, hash_value(k.source_ctn->get_node_type()));
    hash_combine(seed, hash_value(k.source_ctn->get_loop_or_function_id()));
    hash_combine(seed, hash_value(k.source_ctn->get_iteration_id()));

    // Return the result.
    return seed;
  }
};
