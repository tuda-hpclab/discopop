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
#include <memory>
#include <string>
#include <unordered_set>

#include "static_analysis/StaticCalltree.hpp"

namespace static_callpaths {

// Decides which nodes of the static call tree get call path states of their own, based on the hotspot
// classification of the functions (hotspot_detection/Hotspots.json).
//
// A node is *relevant* if it belongs to a hot function (YES / MAYBE) or can reach one through calls. The path
// below a hot function is kept for `hot_depth_steps` further call tree nodes (a call is two steps: the call
// instruction node and the function node). Everything else is folded into the state of its caller: no state and
// no transition is created, so the runtime keeps the caller's state while the callee runs (see
// EnterFunctionForCallstate in the runtime library).
//
// Configuration (environment, the feature is off unless DP_CALLPATH_HOTSPOTS is set):
//   DP_CALLPATH_HOTSPOTS     path of the Hotspots.json of a hotspot detection run
//   DP_CALLPATH_HOTNESS      comma separated classes that count as hot, default "yes,maybe"
//   DP_CALLPATH_SEEDS        "both" (default): functions that contain a hot loop or are hot themselves (hot
//                            recursion needs no loop); "loops"; "functions". A hot function without calls and
//                            loops is no seed unless DP_CALLPATH_KEEP_HOT_LEAVES is set
//   DP_CALLPATH_HOT_DEPTH    calls kept below a seed function, default 2
//   DP_CALLPATH_UNCLASSIFIED "keep" (default) or "prune": functions that Hotspots.json does not mention
class HotspotRelevance {
 public:
  // returns nullptr if the feature is not enabled or Hotspots.json cannot be used
  static std::unique_ptr<HotspotRelevance> FromEnvironment(const StaticCalltree& calltree);

  // number of path steps to keep below `node` when a path reaches it: hot_depth_steps for a hot function,
  // -1 if the node is not a hot function
  [[nodiscard]] std::int32_t HotBudget(const StaticCalltreeNode* node) const;
  [[nodiscard]] bool IsRelevant(const StaticCalltreeNode* node) const { return relevant_.count(node) != 0; }
  [[nodiscard]] std::int32_t hot_depth_steps() const { return hot_depth_steps_; }

 private:
  HotspotRelevance() = default;

  std::unordered_set<const StaticCalltreeNode*> hot_;
  std::unordered_set<const StaticCalltreeNode*> relevant_;
  std::int32_t hot_depth_steps_ = 4;
};

}  // namespace static_callpaths
