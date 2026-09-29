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
#include "MetaDataQueueElement.hpp"

namespace __dp {

class DependencyMetadata {
public:
  DependencyMetadata(MetaDataQueueElement mdqe, hashset<unsigned int> arg_intra_call_dependencies,
                     hashset<unsigned int> arg_intra_iteration_dependencies,
                     hashset<unsigned int> arg_inter_call_dependencies,
                     hashset<unsigned int> arg_inter_iteration_dependencies, hashset<unsigned int> sink_ancestors,
                     hashset<unsigned int> arg_source_ancestors);
  DependencyMetadata() {}
  bool operator==(const DependencyMetadata &other) const;
  depType type;
  LID sink;
  LID source;
  const char *var;
  std::int64_t AAvar;
  hashset<unsigned int> intra_call_dependencies;
  hashset<unsigned int> intra_iteration_dependencies;
  hashset<unsigned int> inter_call_dependencies;
  hashset<unsigned int> inter_iteration_dependencies;
  hashset<unsigned int> sink_ancestors;
  hashset<unsigned int> source_ancestors;
  string toString();
};

} // namespace __dp

template <> struct std::hash<__dp::DependencyMetadata> {
  std::size_t operator()(const __dp::DependencyMetadata &k) const {
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
    for (auto e : k.intra_call_dependencies)
      hash_combine(seed, hash_value(e));
    for (auto e : k.intra_iteration_dependencies)
      hash_combine(seed, hash_value(e));
    for (auto e : k.inter_call_dependencies)
      hash_combine(seed, hash_value(e));
    for (auto e : k.inter_iteration_dependencies)
      hash_combine(seed, hash_value(e));
    for (auto e : k.sink_ancestors)
      hash_combine(seed, hash_value(e));
    for (auto e : k.source_ancestors)
      hash_combine(seed, hash_value(e));

    // Return the result.
    return seed;
  }
};
