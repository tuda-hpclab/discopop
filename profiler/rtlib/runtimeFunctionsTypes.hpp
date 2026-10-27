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

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <future>
#include <mutex>
#include <queue>
#include <set>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "DPTypes.hpp"
#include "functions/FunctionManager.hpp"
#include "loop/LoopManager.hpp"
#include "memory/ShadowMemory.hpp"

namespace dp {
/******* Data structures *******/

enum DepType {
  kRaw,
  kWar,
  kWaw,
  kInit,
  kRawIi0,
  kRawIi1,
  kRawIi2,
  kWarIi0,
  kWarIi1,
  kWarIi2,
  kWawIi0,
  kWawIi1,
  kWawIi2,
  // .._II_x to represent inter-iteration dependencies by loop level in case of
  // nested loops
};

enum DepTypeModifier {
  kNom,
  kIi0,
  kIi1,
  kIi2  // NOM -> Normal
};

struct AccessInfo {
  AccessInfo(bool is_read, LID lid, const char* var, std::int64_t aa_var, ADDR addr, bool skip = false)
      : is_read(is_read), skip(skip), lid(lid), var(var), aa_var(aa_var), addr(addr) {}

  AccessInfo() : is_read(false), skip(false), lid(0), var(""), aa_var(0), addr(0) {}

  bool is_read;
  // hybrid analysis
  bool skip;
  // End HA
  LID lid;
  const char* var;
  std::int64_t aa_var;  // memory region id; previously: name of allocated variable -> "Anti Aliased Variable"
  ADDR addr;
};

// For runtime dependency merging
struct Dep {
  Dep(DepType t, LID dep, const char* var, std::int64_t aa_var) : type(t), dep_on(dep), var(var), aa_var(aa_var) {}

  DepType type;
  LID dep_on;
  const char* var;
  std::int64_t aa_var;
};

struct EqDep {
  bool operator()(const Dep& a, const Dep& b) const {
    if (a.type != b.type) {
      return false;
    }
    if (a.dep_on != b.dep_on) {
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
  size_t operator()(
      const Dep& key) const {  // the parameter type should be the same as the type of key of unordered_map
    size_t hash = 0;
    hash += std::hash<int64_t>{}(key.dep_on);
    hash += std::hash<int>{}(static_cast<int>(key.type));
    return hash;
  }
};

using DepSet = std::unordered_set<Dep, DepHasher, EqDep>;
// The sets are held by value. As owning raw pointers they outlived every map they were stored
// in: the per-thread map is cleared once per processed chunk, which dropped the pointers and
// leaked one set per dependency source line and chunk for the whole run.
using DepMap = std::unordered_map<LID, DepSet>;

// Hybrid anaysis
using StringDepMap = std::unordered_map<std::string, std::unordered_set<std::string>>;
// One observed execution of a reporting basic block of the hybrid analysis (see
// __dp_report_bb / __dp_report_bb_pair): which entry of the handed over
// dependency strings it reports, the callpath state of the most recent execution
// of the basic block holding the dependencies' sources, and the callpath state
// of the reporting (sink) basic block's execution.
struct ReportedBB {
  std::uint32_t bb_index;
  std::uint32_t source_state;
  std::uint32_t sink_state;

  bool operator==(const ReportedBB& other) const {
    return bb_index == other.bb_index && source_state == other.source_state && sink_state == other.sink_state;
  }
};

struct ReportedBBHasher {
  size_t operator()(const ReportedBB& key) const {
    std::uint64_t states = (static_cast<std::uint64_t>(key.source_state) << 32) | key.sink_state;
    return std::hash<std::uint64_t>{}(states) ^ (std::hash<std::uint32_t>{}(key.bb_index) * 0x9E3779B97F4A7C15ULL);
  }
};

using ReportedBBSet = std::unordered_set<ReportedBB, ReportedBBHasher>;

// Collects the reported executions. A reporting basic block executes very
// often, but mostly in pairs of states it was already reported with, so the
// common case is a lookup of an existing entry. The executions are kept in an
// open-addressing hash table of plain entries (linear probing, power-of-two
// capacity, at most half full), which makes that lookup much cheaper than one
// in a std::unordered_set. The entries are only needed as a set at
// termination, see get_executions.
class ReportedBBRecorder {
 public:
  ReportedBBRecorder() : slots_(kInitialCapacity) {}

  inline void Record(std::uint32_t bb_index, std::uint32_t source_state, std::uint32_t sink_state) {
    const std::uint64_t states = (static_cast<std::uint64_t>(source_state) << 32) | sink_state;
    const std::size_t mask = slots_.size() - 1;
    for (std::size_t pos = SlotOf(bb_index, states) & mask;; pos = (pos + 1) & mask) {
      Slot& slot = slots_[pos];
      if (!slot.used) {
        slot.used = true;
        slot.bb_index = bb_index;
        slot.states = states;
        if (2 * (++count_) > slots_.size()) {
          Grow();
        }
        return;
      }
      if (slot.states == states && slot.bb_index == bb_index) {
        return;
      }
    }
  }

  std::size_t size() const { return count_; }

  ReportedBBSet GetExecutions() const {
    ReportedBBSet executions;
    executions.reserve(count_);
    for (const Slot& slot : slots_) {
      if (slot.used) {
        executions.insert(ReportedBB{slot.bb_index, static_cast<std::uint32_t>(slot.states >> 32),
                                     static_cast<std::uint32_t>(slot.states & 0xFFFFFFFF)});
      }
    }
    return executions;
  }

 private:
  static constexpr std::size_t kInitialCapacity = 1024;
  struct Slot {
    std::uint64_t states = 0;
    std::uint32_t bb_index = 0;
    bool used = false;
  };

  static inline std::size_t SlotOf(std::uint32_t bb_index, std::uint64_t states) {
    std::uint64_t h = states * 0x9E3779B97F4A7C15ULL ^ (static_cast<std::uint64_t>(bb_index) * 0xC2B2AE3D27D4EB4FULL);
    h ^= h >> 29;
    h *= 0xBF58476D1CE4E5B9ULL;
    h ^= h >> 32;
    return static_cast<std::size_t>(h);
  }

  void Grow() {
    std::vector<Slot> old(slots_.size() * 2);
    old.swap(slots_);
    const std::size_t mask = slots_.size() - 1;
    for (const Slot& slot : old) {
      if (!slot.used) {
        continue;
      }
      std::size_t pos = SlotOf(slot.bb_index, slot.states) & mask;
      while (slots_[pos].used) {
        pos = (pos + 1) & mask;
      }
      slots_[pos] = slot;
    }
  }

  std::vector<Slot> slots_;
  std::size_t count_ = 0;
};
// End HA

class FirstAccessQueueChunk {
 public:
  explicit FirstAccessQueueChunk(std::size_t chunk_size) : buffer_size_(chunk_size) { buffer_.resize(chunk_size); }

  inline bool IsFull() const { return element_count_ == buffer_size_; }

  inline AccessInfo& GetNextAccessInfoBuffer() { return buffer_[element_count_++]; }

  std::future<std::vector<AccessInfo>*> GetEntryFuture() { return entry_boundary_first_addr_accesses.get_future(); }

  std::future<AbstractShadow*> GetExitFuture() { return exit_boundary_smem.get_future(); }

  inline std::vector<AccessInfo>* GetBuffer() { return &buffer_; }

  inline std::size_t GetElementCount() const { return element_count_; }

  std::promise<std::vector<AccessInfo>*> entry_boundary_first_addr_accesses;
  std::promise<AbstractShadow*> exit_boundary_smem;

 private:
  std::vector<AccessInfo> buffer_;
  std::size_t element_count_ = 0;
  const std::size_t buffer_size_;
};

class SecondAccessQueueElement {
 public:
  SecondAccessQueueElement(std::future<std::vector<AccessInfo>*> fut_first_addr_accesses,
                           std::future<AbstractShadow*> fut_exit_smem) {
    entry_boundary_first_addr_accesses = std::move(fut_first_addr_accesses);
    exit_boundary_smem = std::move(fut_exit_smem);
  }

  std::future<std::vector<AccessInfo>*> entry_boundary_first_addr_accesses;
  std::future<AbstractShadow*> exit_boundary_smem;
};

class SecondAccessQueue {
 public:
  explicit SecondAccessQueue(std::size_t arg_max_size) : max_size_(arg_max_size) {}

  void Push(SecondAccessQueueElement* elem) {
    // wait until the consumer has made room: every element keeps the shadow memory of a whole chunk alive,
    // so an unbounded queue grows by gigabytes when the single consumer falls behind the workers. The
    // size is checked under the lock, so that concurrent producers cannot overshoot max_size.
    while (true) {
      {
        const std::lock_guard<std::mutex> lock(internal_mtx_);
        if (internal_queue_.size() < max_size_) {
          internal_queue_.push(elem);
          queued_elements_.store(internal_queue_.size(), std::memory_order_relaxed);
          return;
        }
      }
      usleep(1000);
    }
  }

  void SetMaxSize(std::size_t arg_max_size) { max_size_ = std::max<std::size_t>(arg_max_size, 1); }

  SecondAccessQueueElement* Get() {
    const std::lock_guard<std::mutex> lock(internal_mtx_);
    // return nullptr if empty
    if (internal_queue_.size() == 0) {
      return nullptr;
    }
    SecondAccessQueueElement* buffer = internal_queue_.front();
    internal_queue_.pop();
    queued_elements_.store(internal_queue_.size(), std::memory_order_relaxed);
    return buffer;
  }

  bool empty() {
    const std::lock_guard<std::mutex> lock(internal_mtx_);
    return internal_queue_.empty();
  }

 private:
  std::queue<SecondAccessQueueElement*> internal_queue_;
  std::mutex internal_mtx_;
  // the size of internal_queue, readable without holding internal_mtx
  std::atomic<std::size_t> queued_elements_{0};
  std::size_t max_size_;
};

class FirstAccessQueue {
 public:
  explicit FirstAccessQueue(std::size_t arg_max_size) : max_size_(arg_max_size) {}

  // Asked by the profiled thread before every push, without taking the lock, so it reads the
  // counter instead of the queue: std::queue::size() while a worker is popping is a data race.
  bool CanAcceptEntries() { return queued_elements_.load(std::memory_order_relaxed) < max_size_; }

  void SetMaxSize(std::size_t arg_max_size) { max_size_ = std::max<std::size_t>(arg_max_size, 1); }

  void Push(FirstAccessQueueChunk* elem) {
    const std::lock_guard<std::mutex> lock(internal_mtx_);
    internal_queue_.push(elem);
    queued_elements_.store(internal_queue_.size(), std::memory_order_relaxed);
  }

  FirstAccessQueueChunk* Get(SecondAccessQueue* second_access_queue_ptr) {
    const std::lock_guard<std::mutex> lock(internal_mtx_);
    // return nullptr if empty
    if (internal_queue_.size() == 0) {
      return nullptr;
    }
    FirstAccessQueueChunk* buffer = internal_queue_.front();
    internal_queue_.pop();
    queued_elements_.store(internal_queue_.size(), std::memory_order_relaxed);

    // register Futures in SecondAccessQueue
    SecondAccessQueueElement* saqe = new SecondAccessQueueElement(buffer->GetEntryFuture(), buffer->GetExitFuture());
    second_access_queue_ptr->Push(saqe);

    return buffer;
  }

  bool empty() {
    const std::lock_guard<std::mutex> lock(internal_mtx_);
    return internal_queue_.empty();
  }

 private:
  std::queue<FirstAccessQueueChunk*> internal_queue_;
  std::mutex internal_mtx_;
  // the size of internal_queue, readable without holding internal_mtx
  std::atomic<std::size_t> queued_elements_{0};
  std::size_t max_size_;
};

class FirstAccessQueueChunkBuffer {
  // data structure to allow the allocation of chunks by worker threads, so the main thread registering the data
  // accesses does not lose this time
 public:
  explicit FirstAccessQueueChunkBuffer(std::size_t arg_size) : size_(arg_size) {}

  // free the chunks prepared but never handed out
  ~FirstAccessQueueChunkBuffer() {
    while (!internal_queue_.empty()) {
      delete internal_queue_.front();
      internal_queue_.pop();
    }
  }

  inline void PrepareChunkIfRequired(std::size_t chunk_size) {
    bool chunk_required = false;
    {
      const std::lock_guard<std::mutex> lock(internal_mtx_);
      if (internal_queue_.size() < size_) {
        chunk_required = true;
      }
    }

    if (chunk_required) {
      // NOLINTNEXTLINE(misc-const-correctness): the queue stores pointers to mutable chunks
      FirstAccessQueueChunk* new_chunk = new FirstAccessQueueChunk(chunk_size);
      const std::lock_guard<std::mutex> lock(internal_mtx_);
      internal_queue_.push(new_chunk);
    }
  }

  FirstAccessQueueChunk* GetPreparedChunk(std::size_t chunk_size) {
    FirstAccessQueueChunk* buffer;
    const std::lock_guard<std::mutex> lock(internal_mtx_);
    if (internal_queue_.size() > 0) {
      // prepared chunk exists
      buffer = internal_queue_.front();
      internal_queue_.pop();
      return buffer;
    }  // allocate a new chunk
    return new FirstAccessQueueChunk(chunk_size);
  }

  std::size_t GetQueueSize() {
    const std::lock_guard<std::mutex> lock(internal_mtx_);
    return internal_queue_.size();
  }

 private:
  std::queue<FirstAccessQueueChunk*> internal_queue_;
  std::mutex internal_mtx_;
  const std::size_t size_;
};

}  // namespace dp
