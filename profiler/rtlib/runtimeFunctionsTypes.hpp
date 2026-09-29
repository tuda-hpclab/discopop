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

#include "DPTypes.hpp"

#include "functions/FunctionManager.hpp"
#include "loop/LoopManager.hpp"
#include "memory/MemoryManager.hpp"

#if DP_CALLTREE_PROFILING
#include "calltree/CallTreeNode.hpp"
#endif

#include <cstdint>
#include <future>
#include <mutex>
#include <queue>
#include <set>
#include <string>
#include <unordered_map>
#include <vector>

#include "memory/ShadowMemory.hpp"

namespace __dp {
/******* Data structures *******/

typedef enum {
  RAW,
  WAR,
  WAW,
  INIT,
  RAW_II_0,
  RAW_II_1,
  RAW_II_2,
  WAR_II_0,
  WAR_II_1,
  WAR_II_2,
  WAW_II_0,
  WAW_II_1,
  WAW_II_2,
  // .._II_x to represent inter-iteration dependencies by loop level in case of
  // nested loops
} depType;

typedef enum {
  NOM,
  II_0,
  II_1,
  II_2 // NOM -> Normal
} depTypeModifier;

struct AccessInfo {
  AccessInfo(bool isRead, LID lid, char *var, std::int64_t AAvar, ADDR addr, bool skip = false)
      : isRead(isRead), lid(lid), var(var), AAvar(AAvar), addr(addr), skip(skip) {
#if DP_CALLTREE_PROFILING
    call_tree_node_ptr = nullptr;
    calculate_dependency_metadata = true;
#endif
  }

  AccessInfo() : isRead(false), lid(0), var(""), AAvar(0), addr(0), skip(false) {
#if DP_CALLTREE_PROFILING
    call_tree_node_ptr = nullptr;
    calculate_dependency_metadata = true;
#endif
  }

  bool isRead;
  // hybrid analysis
  bool skip;
  // End HA
  LID lid;
  const char *var;
  std::int64_t AAvar; // memory region id; previously: name of allocated variable -> "Anti Aliased Variable"
  ADDR addr;
#if DP_CALLTREE_PROFILING
  shared_ptr<CallTreeNode> call_tree_node_ptr;
  bool calculate_dependency_metadata;
#endif
};

// For runtime dependency merging
struct Dep {
  Dep(depType T, LID dep, const char *var, std::int64_t AAvar) : type(T), depOn(dep), var(var), AAvar(AAvar) {}

  depType type;
  LID depOn;
  const char *var;
  std::int64_t AAvar;
};

struct compDep {
  bool operator()(const Dep &a, const Dep &b) const {
    if (a.type < b.type) {
      return true;
    } else if (a.type == b.type && a.depOn < b.depOn) {
      return true;
    }
    // comparison between string is very time-consuming. So just compare
    // variable names according to address (we only need to distinguish them)
    else if (a.type == b.type && a.depOn == b.depOn && ((size_t)a.var < (size_t)b.var)) {
      return true;
    }

    return false;
  }
};

struct eqDep {
  bool operator()(const Dep &a, const Dep &b) const {
    if (a.type != b.type) {
      return false;
    }
    if (a.depOn != b.depOn) {
      return false;
    }
    // comparison between string is very time-consuming. So just compare
    // variable names according to address (we only need to distinguish them)
    if (a.var != b.var) {
      return false;
    }
    return true;
  }
};

class DepHasher {
public:
  size_t operator()(Dep const &key) const { // the parameter type should be the same as the type of key of unordered_map
    size_t hash = 0;
    hash += std::hash<int64_t>{}(key.depOn);
    hash += std::hash<int>{}((int)key.type);
    return hash;
  }
};

typedef std::unordered_set<Dep, DepHasher, eqDep> depSet;
typedef std::unordered_map<LID, depSet *> depMap;

// Hybrid anaysis
typedef std::unordered_map<std::string, std::unordered_set<std::string>> stringDepMap;
typedef std::unordered_set<std::uint32_t> ReportedBBSet;
// End HA

class FirstAccessQueueChunk {
public:
  FirstAccessQueueChunk(std::size_t chunk_size) : buffer_size(chunk_size) { buffer.resize(chunk_size); }

  inline bool is_full() { return element_count == buffer_size; }

  inline AccessInfo &get_next_AccessInfo_buffer() { return buffer[element_count++]; }

  std::future<std::vector<AccessInfo> *> get_entry_future() { return entry_boundary_first_addr_accesses.get_future(); }

  std::future<AbstractShadow *> get_exit_future() { return exit_boundary_SMem.get_future(); }

  inline std::vector<AccessInfo> *get_buffer() { return &buffer; }

  inline std::size_t get_element_count() { return element_count; }

  std::promise<std::vector<AccessInfo> *> entry_boundary_first_addr_accesses;
  std::promise<AbstractShadow *> exit_boundary_SMem;

private:
  std::vector<AccessInfo> buffer;
  std::size_t element_count = 0;
  const std::size_t buffer_size;
};

class SecondAccessQueueElement {
public:
  SecondAccessQueueElement(std::future<std::vector<AccessInfo> *> fut_first_addr_accesses,
                           std::future<AbstractShadow *> fut_exit_smem) {
    entry_boundary_first_addr_accesses = std::move(fut_first_addr_accesses);
    exit_boundary_SMem = std::move(fut_exit_smem);
  }

  std::future<std::vector<AccessInfo> *> entry_boundary_first_addr_accesses;
  std::future<AbstractShadow *> exit_boundary_SMem;
};

class SecondAccessQueue {
public:
  SecondAccessQueue(std::size_t arg_max_size) : max_size(arg_max_size) {}

  void push(SecondAccessQueueElement *elem) {
    // spin-lock to prevent endless queue growth
    while (internal_queue.size() > max_size) {
      // std::cout << "SAQ: push: sleep." << std::endl;
      usleep(1000);
    }
    const std::lock_guard<std::mutex> lock(internal_mtx);
    internal_queue.push(elem);
  }

  SecondAccessQueueElement *get() {
    const std::lock_guard<std::mutex> lock(internal_mtx);
    // return nullptr if empty
    if (internal_queue.size() == 0) {
      return nullptr;
    }
    SecondAccessQueueElement *buffer = internal_queue.front();
    internal_queue.pop();
    return buffer;
  }

  bool empty() {
    const std::lock_guard<std::mutex> lock(internal_mtx);
    return internal_queue.empty();
  }

private:
  std::queue<SecondAccessQueueElement *> internal_queue;
  std::mutex internal_mtx;
  const std::size_t max_size;
};

class FirstAccessQueue {
public:
  FirstAccessQueue(std::size_t arg_max_size) : max_size(arg_max_size) {}

  bool can_accept_entries() { return internal_queue.size() < max_size; }

  void push(FirstAccessQueueChunk *elem) {
    const std::lock_guard<std::mutex> lock(internal_mtx);
    internal_queue.push(elem);
  }

  FirstAccessQueueChunk *get(SecondAccessQueue *secondAccessQueue_ptr) {
    const std::lock_guard<std::mutex> lock(internal_mtx);
    // return nullptr if empty
    if (internal_queue.size() == 0) {
      return nullptr;
    }
    FirstAccessQueueChunk *buffer = internal_queue.front();
    internal_queue.pop();

    // register Futures in SecondAccessQueue
    SecondAccessQueueElement *saqe =
        new SecondAccessQueueElement(std::move(buffer->get_entry_future()), std::move(buffer->get_exit_future()));
    secondAccessQueue_ptr->push(saqe);

    return buffer;
  }

  bool empty() {
    const std::lock_guard<std::mutex> lock(internal_mtx);
    return internal_queue.empty();
  }

private:
  std::queue<FirstAccessQueueChunk *> internal_queue;
  std::mutex internal_mtx;
  const std::size_t max_size;
};

class FirstAccessQueueChunkBuffer {
  // data structure to allow the allocation of chunks by worker threads, so the main thread registering the data
  // accesses does not lose this time
public:
  FirstAccessQueueChunkBuffer(std::size_t arg_size) : size(arg_size) {}

  inline void prepare_chunk_if_required(std::size_t chunk_size) {
    bool chunk_required = false;
    {
      const std::lock_guard<std::mutex> lock(internal_mtx);
      if (internal_queue.size() < size) {
        chunk_required = true;
      }
    }

    if (chunk_required) {
      FirstAccessQueueChunk *new_chunk = new FirstAccessQueueChunk(chunk_size);
      const std::lock_guard<std::mutex> lock(internal_mtx);
      internal_queue.push(new_chunk);
    }
  }

  FirstAccessQueueChunk *get_prepared_chunk(std::size_t chunk_size) {
    FirstAccessQueueChunk *buffer;
    const std::lock_guard<std::mutex> lock(internal_mtx);
    if (internal_queue.size() > 0) {
      // prepared chunk exists
      buffer = internal_queue.front();
      internal_queue.pop();
      return buffer;
    } else {
      // allocate a new chunk
      return new FirstAccessQueueChunk(chunk_size);
    }
  }

  std::size_t get_queue_size() {
    const std::lock_guard<std::mutex> lock(internal_mtx);
    return internal_queue.size();
  }

private:
  std::queue<FirstAccessQueueChunk *> internal_queue;
  std::mutex internal_mtx;
  const std::size_t size;
};

} // namespace __dp
