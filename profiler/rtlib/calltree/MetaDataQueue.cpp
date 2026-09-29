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

#include "MetaDataQueue.hpp"

#include "../../share/include/timer.hpp"
#include "../runtimeFunctionsGlobals.hpp"

namespace __dp {
// TODO
MetaDataQueue::MetaDataQueue(int worker_count) {
  finalize_queue = false;

  if (worker_count < 1) {
    worker_count = 1;
    // serial execution
  }
  for (size_t i = 0; i < worker_count; ++i) {
    // FIX: unnötiges move
    threads.emplace_back(std::thread(processQueue, this));
  }
}

MetaDataQueue::~MetaDataQueue() {}

void MetaDataQueue::insert(MetaDataQueueElement &&mdqe) {
  const auto calltree_timer = Timer(timers, TimerRegion::ADD_DEP_CALLTREE_REGISTER_METADATAQUEUEELEMENT);
  if (finalize_queue) {
    return;
  }

  // drop the element, if it was already enqueued
  bool mdqe_already_enqueued = false;
  // check if an equal element was already processed
  enqueued_mtx.lock();

  // mdqe_already_enqueued = enqueued.find(mdqe) != enqueued.end();
  auto contained = enqueued.insert(mdqe);
  mdqe_already_enqueued = !contained.second;
  enqueued_mtx.unlock();

  mdqe_already_enqueued = !contained.second;

  if (mdqe_already_enqueued) {
    // element already inserted to queue before
    return;
  }

  // insert mdqe to queue
  std::lock_guard<std::mutex> lock(queue_mtx);
  queue.push(std::move(mdqe));
  // cout << "insert: " << mdqe.toString() << "\n";
}

int MetaDataQueue::get_size() {
  std::lock_guard<std::mutex> lock(queue_mtx);
  return queue.size();
}

void MetaDataQueue::blocking_finalize_queue() {
  finalize_queue = true;
  // join threads
  for (auto &t : threads) {
    t.join();
  }

  // print results
  cout << "RESULTS: \n";
  for (auto dmd : results) {
    cout << dmd.toString() << "\n";
  }

  // output to file
  std::cout << "Outputting dependency metadata... ";
  std::ifstream ifile;
  std::string line;
  std::ofstream ofile;
  std::string tmp(getenv("DOT_DISCOPOP_PROFILER"));
  // output information about the loops
  tmp += "/dependency_metadata.txt";
  ofile.open(tmp.data());
  ofile << "# IAC : intra-call-dependency \n";
  ofile << "# IAI : intra-iteration-dependency \n";
  ofile << "# IEC : inter-call-dependency \n";
  ofile << "# IEI : inter-iteration-dependency \n";
  ofile << "# SINK_ANC : entered functions and loops for sink location \n";
  ofile << "# SOURCE_ANC : entered functions and loops for source location \n";
  ofile << "# Format: <DepType> <sink> <source> <var> <AAvar> <IAC> <IAI> <IEC> <IEI> <SINK_ANC> <SOURCE_ANC>\n";
  for (auto dmd : results) {
    ofile << dmd.toString() << "\n";
  }
  ofile.close();
}

void processQueue(MetaDataQueue *mdq) {
  const auto calltree_timer = Timer(timers, TimerRegion::METADATAQUEUE_PROCESSQUEUE);
  while (!(mdq->finalize_queue && (mdq->get_size() == 0))) {
    mdq->queue_mtx.lock();
    // try fetching an element from the queue
    if (mdq->queue.size() != 0) {
      const auto calltree_timer = Timer(timers, TimerRegion::METADATAQUEUE_PROCESSQUEUE_FETCH);

      // fetch element from the queue
      MetaDataQueueElement mdqe = mdq->queue.front();
      mdq->queue.pop();
      // std::cout << "fetched. Remaining: " << mdq->queue.size() << "\n";
      //  release queue lock
      mdq->queue_mtx.unlock();

      // process element
      // DependencyMetadata metadata = processQueueElement(mdqe);

      // save metadata to results
      mdq->results_mtx.lock();
      mdq->results.push_back(metadata);
      mdq->results_mtx.unlock();
    } else {
      // release lock
      mdq->queue_mtx.unlock();
      // sleep 5 milliseconds
      std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
  }
}

} // namespace __dp
