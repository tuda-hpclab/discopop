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

#include "MetaDataQueueElement.hpp"

namespace __dp {
MetaDataQueueElement::MetaDataQueueElement(depType arg_type, LID arg_sink, LID arg_source, const char *arg_var,
                                           std::int64_t arg_AAvar, shared_ptr<CallTreeNode> arg_sink_ctn,
                                           shared_ptr<CallTreeNode> arg_source_ctn)
    : type(arg_type), sink(arg_sink), source(arg_source), var(arg_var), AAvar(arg_AAvar),
      sink_ctn(std::move(arg_sink_ctn)), source_ctn(std::move(arg_source_ctn)) {}

bool MetaDataQueueElement::operator==(const MetaDataQueueElement &other) const {
  return (type == other.type) && (sink == other.sink) && (source == other.source) && (var == other.var) &&
         (AAvar == other.AAvar) && (sink_ctn->get_node_type() == other.sink_ctn->get_node_type()) &&
         (sink_ctn->get_loop_or_function_id() == other.sink_ctn->get_loop_or_function_id()) &&
         (sink_ctn->get_iteration_id() == other.sink_ctn->get_iteration_id()) &&
         (source_ctn->get_node_type() == other.source_ctn->get_node_type()) &&
         (source_ctn->get_loop_or_function_id() == other.source_ctn->get_loop_or_function_id()) &&
         (source_ctn->get_iteration_id() == other.source_ctn->get_iteration_id());
}

string MetaDataQueueElement::toString() {
  string result = "MDQE( ";
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
  default:
    break;
  }
  result += dputil::decodeLID(sink) + " - " + dputil::decodeLID(source) + " ";
  result += var;
  result += " ";
  result += AAvar + " ";
  result += "sink_ctn: " + to_string(sink_ctn->get_loop_or_function_id()) + " ";
  result += "it: " + to_string(sink_ctn->get_iteration_id()) + " ";
  result += "source_ctn: " + to_string(source_ctn->get_loop_or_function_id()) + " ";
  result += "it: " + to_string(source_ctn->get_iteration_id()) + " ";
  result += ")";
  return result;
}

} // namespace __dp
