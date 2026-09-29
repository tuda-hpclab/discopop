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

#include "DependencyMetadata.hpp"

namespace __dp {
DependencyMetadata::DependencyMetadata(MetaDataQueueElement mdqe, hashset<unsigned int> arg_intra_call_dependencies,
                                       hashset<unsigned int> arg_intra_iteration_dependencies,
                                       hashset<unsigned int> arg_inter_call_dependencies,
                                       hashset<unsigned int> arg_inter_iteration_dependencies,
                                       hashset<unsigned int> arg_sink_ancestors,
                                       hashset<unsigned int> arg_source_ancestors)
    : type(mdqe.type), sink(mdqe.sink), source(mdqe.source), var(mdqe.var), AAvar(mdqe.AAvar),
      intra_call_dependencies(std::move(arg_intra_call_dependencies)),
      intra_iteration_dependencies(std::move(arg_intra_iteration_dependencies)),
      inter_call_dependencies(std::move(arg_inter_call_dependencies)),
      inter_iteration_dependencies(std::move(arg_inter_iteration_dependencies)),
      sink_ancestors(std::move(arg_sink_ancestors)), source_ancestors(std::move(arg_source_ancestors)) {}

bool DependencyMetadata::operator==(const DependencyMetadata &other) const {
  return (type == other.type) && (sink == other.sink) && (source == other.source) && (var == other.var) &&
         (AAvar == other.AAvar) && (intra_call_dependencies == other.intra_call_dependencies) &&
         (intra_iteration_dependencies == other.intra_iteration_dependencies) &&
         (inter_call_dependencies == other.inter_call_dependencies) &&
         (inter_iteration_dependencies == other.inter_iteration_dependencies) &&
         (sink_ancestors == other.sink_ancestors) && (source_ancestors == other.source_ancestors);
}

string DependencyMetadata::toString() {
  string result = "";
  switch (type) {
  case RAW:
    result += "RAW ";
    break;
  case WAR:
    result += "WAR ";
    break;
  case WAW:
    result += "WAW ";
    break;
  case INIT:
    result += "INIT ";
    break;
  default:
    break;
  }
  result += dputil::decodeLID(sink) + " ";
  result += dputil::decodeLID(source) + " ";
  result += var;
  result += " ";
  result += std::to_string(AAvar);
  result += " ";
  result += "IAC[";
  for (auto iac : intra_call_dependencies) {
    result += dputil::decodeLID(iac) + ",";
  }
  result += "] ";
  result += "IAI[";
  for (auto iai : intra_iteration_dependencies) {
    result += dputil::decodeLID(iai) + ",";
  }
  result += "] ";
  result += "IEC[";
  for (auto iec : inter_call_dependencies) {
    result += dputil::decodeLID(iec) + ",";
  }
  result += "] ";
  result += "IEI[";
  for (auto iei : inter_iteration_dependencies) {
    result += dputil::decodeLID(iei) + ",";
  }
  result += "] ";
  result += "SINK_ANC[";
  for (auto sink_anc : sink_ancestors) {
    result += dputil::decodeLID(sink_anc) + ",";
  }
  result += "] ";
  result += "SOURCE_ANC[";
  for (auto source_anc : source_ancestors) {
    result += dputil::decodeLID(source_anc) + ",";
  }
  result += "] ";
  return result;
}

} // namespace __dp
