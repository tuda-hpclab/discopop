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

#include <unistd.h>

#include <cstddef>
#include <cstdint>
#include <functional>
#include <iostream>
#include <unordered_set>
#include <vector>

#include "memory/PerfectShadow.hpp"
#include "runtimeFunctions.hpp"
#include "runtimeFunctionsGlobals.hpp"
#include "timer.hpp"

#ifdef __linux__
#include <sched.h>
#endif

namespace dp {

namespace {

// What a deferred access is identified by: the address, the instruction and call path state
// its LID carries, whether it reads or writes, and whether it is one of the markers the
// hybrid analysis inserts. Two accesses that agree on all of it derive the same dependency
// from the state the earlier chunks left behind. Leaving the direction out of this made a
// read swallow the write that followed it on the same address and line.
struct DeferredAccess {
  ADDR addr;
  LID lid;
  bool is_read;
  bool skip;

  bool operator==(const DeferredAccess& other) const noexcept {
    return addr == other.addr && lid == other.lid && is_read == other.is_read && skip == other.skip;
  }
};

struct DeferredAccessHash {
  std::size_t operator()(const DeferredAccess& access) const noexcept {
    const std::size_t flags = (access.is_read ? 1u : 0u) | (access.skip ? 2u : 0u);
    return std::hash<ADDR>()(access.addr) ^ (std::hash<LID>()(access.lid) << 1) ^ (flags << 3);
  }
};

// After this many deferred accesses in one chunk, the deduplication has to have paid for
// itself -- see DEFERRED_DEDUP_MIN_HIT_RATE. Long enough to measure, short enough that a
// chunk of 100000 accesses does not spend much of itself deciding.
constexpr std::size_t kDeferredDedupTrial = 4096;

// The share of deferred accesses that has to be a repeat of one already queued for the table
// to be worth a hash insert per access. Code that walks a new address every time -- a linked
// list, a large array touched once -- finds nothing and drops far below this.
constexpr double kDeferredDedupMinHitRate = 0.25;

}  // namespace

void* ProcessFirstAccessQueue(void* arg) {
#ifdef DP_INTERNAL_TIMER
  const auto timer = Timer(timers, TimerRegion::kAnalyzeDeps);
#endif

  const std::intptr_t id = reinterpret_cast<std::intptr_t>(arg);
  my_map = new DepMap();

  FirstAccessQueueChunk* current = nullptr;

  while (true) {
    // get chunk from queue
    current = first_access_queue.Get(&second_access_queue);

    // check if chunk aquired
    if (current) {
      // process chunk
      AbstractShadow* smem = new PerfectShadow2();
      std::vector<AccessInfo>* entry_condition_accesses = new std::vector<AccessInfo>();
      std::unordered_set<DeferredAccess, DeferredAccessHash> already_deferred;
      // Given up once the chunk turns out not to repeat its accesses.
      bool deduplicate = true;
      std::size_t deferred_seen = 0;
      std::size_t deferred_repeats = 0;

      for (AccessInfo access : *(current->GetBuffer())) {
        if (!(access.addr || access.lid)) {
          continue;
        }

        // An access can be analyzed against the chunk local shadow only once that shadow
        // knows everything about its address, and it does from the first write to it on.
        // Before that, "no earlier write in this chunk" is not "no earlier write", and where
        // the chunk boundary happens to fall decides what is reported. So everything up to
        // and including the first write to an address is analyzed by the second queue, which
        // carries the state the earlier chunks left behind.
        const bool is_entry_condition_access = smem->TestInWrite(access.addr) == 0;
        if (is_entry_condition_access) {
          // Once per address and LID: the second queue would derive the same dependency from
          // the second one, and a read heavy chunk repeats the same pair thousands of times.
          // The shadow below is still updated for every one of them, so the state this chunk
          // hands on is the state of its last access.
          if (deduplicate) {
            ++deferred_seen;
            if (already_deferred.insert(DeferredAccess{access.addr, access.lid, access.is_read, access.skip}).second) {
              entry_condition_accesses->push_back(access);
            } else {
              ++deferred_repeats;
            }
            if (deferred_seen == kDeferredDedupTrial &&
                static_cast<double>(deferred_repeats) / static_cast<double>(deferred_seen) < kDeferredDedupMinHitRate) {
              already_deferred.clear();
              deduplicate = false;
            }
          } else {
            entry_condition_accesses->push_back(access);
          }
          // register the read / write represented by the access to allow the identification of correct dependencies for
          // the rest of the chunk
          if (access.is_read) {
            smem->InsertToRead(access.addr, access.lid);
          } else {
            smem->InsertToWrite(access.addr, access.lid);
          }
        } else {
          // handle access as known from the legacy variant of the profiler
          AnalyzeSingleAccess(smem, access);
        }
      }
      // publish the values of the promises in the current chunk
      current->entry_boundary_first_addr_accesses.set_value(entry_condition_accesses);
      current->exit_boundary_smem.set_value(smem);

      // the thread's dependencies stay in myMap across chunks, deduplicated, and are merged into
      // allDeps once when the thread ends: merging (and freeing) them per chunk allocated and freed
      // a set per dependency sink and chunk again and again
      delete current;

    } else {
      if (finalize_parallelization_called) {
        // no chunks left to process. Let thread finish.
        break;
      }  // let thread sleep and try fetching a chunk again after potentially preparing an new chunk
      first_access_queue_chunk_buffer.PrepareChunkIfRequired(kFirstAccessQueueChunkSize);
      usleep(1000);
    }
  }

  MergeDeps();
  // the dependencies are merged into allDeps; the map itself belongs to this thread
  delete my_map;
  my_map = nullptr;

  if (dp_debug) {
#ifdef __linux__
    std::cout << "thread " << id << " on core " << sched_getcpu() << " exits... \n";
#else
    std::cout << "thread " << id << " exits... \n";
#endif
  }

  pthread_exit(nullptr);
  return nullptr;
}

void* ProcessSecondAccessQueue(void* arg) {
#ifdef DP_INTERNAL_TIMER
  const auto timer = Timer(timers, TimerRegion::kAnalyzeDeps);
#endif

  const std::intptr_t id = reinterpret_cast<std::intptr_t>(arg);
  my_map = new DepMap();

  SecondAccessQueueElement* current = nullptr;
  AbstractShadow* smem = new PerfectShadow2();

  while (true) {
    // get chunk from queue
    current = second_access_queue.Get();

    // check if chunk aquired
    if (current) {
      // check entry boundary conditions for data dependencies
      auto promised_first_accesses_vector_ptr = current->entry_boundary_first_addr_accesses.get();
      for (auto& entry_accesses : *(promised_first_accesses_vector_ptr)) {
        // ignore unused entries of the vector
        if (!(entry_accesses.addr || entry_accesses.lid)) {
          continue;
        }
        AnalyzeSingleAccess(smem, entry_accesses);
      }

      // update persistent SMem with exit boundary conditions (aka merge the local into the persistent shadow memories)
      AbstractShadow* promised_last_smem_ptr = current->exit_boundary_smem.get();

      auto sig_read = static_cast<PerfectShadow2*>(promised_last_smem_ptr)->GetSigRead();
      auto sig_write = static_cast<PerfectShadow2*>(promised_last_smem_ptr)->GetSigWrite();

      // identify required updates to SMem
      // iterate over addresses to be merged
      for (auto it = promised_first_accesses_vector_ptr->begin(); it < promised_first_accesses_vector_ptr->end();
           ++it) {
        smem->UpdateInRead(it->addr, sig_read->at(it->addr));
        smem->UpdateInWrite(it->addr, sig_write->at(it->addr));
      }

      // cleanup promises
      delete promised_first_accesses_vector_ptr;
      delete promised_last_smem_ptr;

      delete current;

    } else {
      if (finalize_parallelization_called) {
        // a first queue worker may have moved a chunk into the second queue since the get() above.
        // FirstAccessQueue::get registers the element in the second queue while holding the first queue's lock, so once
        // the first queue is empty, every element is visible in the second queue: check them in this order
        if (first_access_queue.empty() && second_access_queue.empty()) {
          // no chunks left to process. Let thread finish.
          break;
        }
        usleep(1000);

      } else {
        // let thread sleep and try fetching a chunk again
        usleep(1000);
      }
    }
  }

  delete smem;
  MergeDeps();
  // the dependencies are merged into allDeps; the map itself belongs to this thread
  delete my_map;
  my_map = nullptr;

  if (dp_debug) {
#ifdef __linux__
    std::cout << "thread " << id << " processing secondAccessQueue on core " << sched_getcpu() << " exits... \n";
#else
    std::cout << "thread " << id << " processing secondAccessQueue exits... \n";
#endif
  }

  pthread_exit(nullptr);
  return nullptr;
}

}  // namespace dp
