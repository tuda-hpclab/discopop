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

#include "static_analysis/hotspot_relevance.hpp"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <unordered_map>
#include <utility>
#include <vector>

#include "llvm/Support/JSON.h"
#include "llvm/Support/MemoryBuffer.h"

namespace static_callpaths {

namespace {

std::string Lowercase(std::string s) {
  std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return std::tolower(c); });
  return s;
}

std::unordered_set<std::string> ParseHotnessClasses(const char* value) {
  std::unordered_set<std::string> classes;
  std::stringstream stream(value);
  std::string item;
  while (std::getline(stream, item, ',')) {
    if (!item.empty()) {
      classes.insert(Lowercase(item));
    }
  }
  return classes;
}

// name of the function a call tree function node belongs to: loop iteration states are named
// "<function>_loopstate<digits>"
std::string FunctionNameOfNode(StaticCalltreeNode* node) {
  const std::string& label = node->GetLabel();
  if (node->is_loopstate) {
    const std::size_t position = label.rfind("_loopstate");
    if (position != std::string::npos) {
      return label.substr(0, position);
    }
  }
  return label;
}

}  // namespace

std::unique_ptr<HotspotRelevance> HotspotRelevance::FromEnvironment(const StaticCalltree& calltree) {
  const char* hotspots_path = std::getenv("DP_CALLPATH_HOTSPOTS");
  if (hotspots_path == nullptr || *hotspots_path == '\0') {
    return nullptr;
  }
  auto buffer = llvm::MemoryBuffer::getFile(hotspots_path);
  if (!buffer) {
    std::cerr << "DiscoPoP: cannot read " << hotspots_path << ", call path states are not pruned\n";
    return nullptr;
  }
  auto parsed = llvm::json::parse((*buffer)->getBuffer());
  if (!parsed) {
    llvm::consumeError(parsed.takeError());
    std::cerr << "DiscoPoP: cannot parse " << hotspots_path << ", call path states are not pruned\n";
    return nullptr;
  }
  const llvm::json::Object* root = parsed->getAsObject();
  const llvm::json::Array* regions = root != nullptr ? root->getArray("code_regions") : nullptr;
  if (regions == nullptr) {
    std::cerr << "DiscoPoP: " << hotspots_path << " has no code_regions, call path states are not pruned\n";
    return nullptr;
  }

  const char* classes_value = std::getenv("DP_CALLPATH_HOTNESS");
  const std::unordered_set<std::string> hot_classes = ParseHotnessClasses(classes_value ? classes_value : "yes,maybe");
  const char* unclassified_value = std::getenv("DP_CALLPATH_UNCLASSIFIED");
  const bool keep_unclassified = unclassified_value == nullptr || Lowercase(unclassified_value) != "prune";

  // classification of the functions; a function that has several regions is as hot as its hottest one
  std::unordered_set<std::string> hot_functions;
  std::unordered_set<std::string> classified_functions;
  std::unordered_set<std::string> hot_loops;  // "<file id>:<line>"
  for (const llvm::json::Value& value : *regions) {
    const llvm::json::Object* region = value.getAsObject();
    if (region == nullptr) {
      continue;
    }
    auto type = region->getString("typ");
    auto name = region->getString("name");
    auto hotness = region->getString("hotness");
    if (!type || !hotness) {
      continue;
    }
    if (*type == "LOOP") {
      auto file_id = region->getInteger("fid");
      auto line = region->getInteger("lineNum");
      if (file_id && line && hot_classes.count(Lowercase(hotness->str())) != 0) {
        hot_loops.insert(std::to_string(*file_id) + ":" + std::to_string(*line));
      }
      continue;
    }
    if (!name || *type != "FUNCTION") {
      continue;
    }
    classified_functions.insert(name->str());
    if (hot_classes.count(Lowercase(hotness->str())) != 0) {
      hot_functions.insert(name->str());
    }
  }

  // a function is a seed if it contains a hot loop and/or is hot itself, depending on DP_CALLPATH_SEEDS
  const char* seeds_value = std::getenv("DP_CALLPATH_SEEDS");
  const std::string seeds = seeds_value != nullptr ? Lowercase(seeds_value) : "both";
  const bool seed_by_loops = seeds == "loops" || seeds == "both";
  const bool seed_by_functions = seeds == "functions" || seeds == "both";
  std::unordered_set<std::string> functions_with_hot_loops;
  for (const auto& entry : calltree.loop_locations_by_function) {
    for (const std::string& location : entry.second) {
      if (hot_loops.count(location) != 0) {
        functions_with_hot_loops.insert(entry.first);
        break;
      }
    }
  }

  // functions with calls or loops of their own. A hot function without either has no structure of its own to
  // parallelize (hot recursion, a loop, or calls are what make a function a target), but all paths to it would
  // stay, so it is no seed unless DP_CALLPATH_KEEP_HOT_LEAVES is set.
  std::unordered_set<std::string> functions_with_structure;
  for (const auto& pair : calltree.function_map) {
    if (!pair.second->successors.empty()) {
      functions_with_structure.insert(FunctionNameOfNode(pair.second));
    }
  }
  const bool keep_hot_leaves = std::getenv("DP_CALLPATH_KEEP_HOT_LEAVES") != nullptr;

  std::unique_ptr<HotspotRelevance> result(new HotspotRelevance());
  const char* depth_value = std::getenv("DP_CALLPATH_HOT_DEPTH");
  if (depth_value != nullptr) {
    result->hot_depth_steps_ = std::max(0, std::atoi(depth_value)) * 2;
  } else {
    result->hot_depth_steps_ = 4;
  }

  // hot call tree nodes: function nodes (and their loop iteration states) of hot functions
  std::vector<StaticCalltreeNode*> work;
  for (const auto& pair : calltree.function_map) {
    StaticCalltreeNode* node = pair.second;
    const std::string name = FunctionNameOfNode(node);
    const bool classified = classified_functions.count(name) != 0;
    const bool seed = (seed_by_loops && functions_with_hot_loops.count(name) != 0) ||
                      (seed_by_functions && hot_functions.count(name) != 0 &&
                       (keep_hot_leaves || functions_with_structure.count(name) != 0)) ||
                      (!classified && functions_with_hot_loops.count(name) == 0 && keep_unclassified);
    if (seed) {
      result->hot_.insert(node);
      if (result->relevant_.insert(node).second) {
        work.push_back(node);
      }
    }
  }
  // everything that can reach a hot node is relevant: walk the calls backwards. The "main" function is kept
  // by the enumeration itself.
  while (!work.empty()) {
    StaticCalltreeNode* node = work.back();
    work.pop_back();
    for (StaticCalltreeNode* predecessor : node->predecessors) {
      if (result->relevant_.insert(predecessor).second) {
        work.push_back(predecessor);
      }
    }
  }
  std::cout << "Hotspot relevance: " << result->hot_.size() << " hot and " << result->relevant_.size()
            << " relevant of " << (calltree.function_map.size() + calltree.instruction_map.size())
            << " call tree nodes, " << (result->hot_depth_steps_ / 2) << " calls kept below hot functions\n";
  return result;
}

std::int32_t HotspotRelevance::HotBudget(const StaticCalltreeNode* node) const {
  return hot_.count(node) != 0 ? hot_depth_steps_ : -1;
}

}  // namespace static_callpaths
