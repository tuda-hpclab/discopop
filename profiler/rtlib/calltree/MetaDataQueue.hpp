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

#include "DependencyMetadata.hpp"
#include "MetaDataQueueElement.hpp"
#include <iostream>
#include <mutex>
#include <queue>
#include <set>
#include <thread>
#include <unordered_set>
#include <vector>

namespace __dp {
class MetaDataQueue {
public:
  MetaDataQueue(int worker_count); // worker_count: minimum 1
  ~MetaDataQueue();
  void insert(MetaDataQueueElement &&mdqe); // TODO optimization potential, do not use copies here!
  const std::set<DependencyMetadata> &get_metadata();
  int get_size();
  void blocking_finalize_queue();
  bool finalize_queue;
  std::mutex queue_mtx;
  std::queue<MetaDataQueueElement> queue;
  std::mutex results_mtx;
  std::vector<DependencyMetadata> results;
  std::mutex enqueued_mtx;
  std::unordered_set<MetaDataQueueElement> enqueued;

private:
  std::vector<std::thread> threads;
};

static void processQueue(MetaDataQueue *mdq);
static DependencyMetadata processQueueElement(MetaDataQueueElement mdqe);

} // namespace __dp
