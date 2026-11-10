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
#include <cstddef>
#include <cstdint>
#include <future>
#include <iostream>
#include <memory>
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
#include "memory/PerfectShadow.hpp"
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
//
// In front of the table, every sink state has a small direct mapped cache of
// the executions recorded in it, indexed by the low bits of the block index:
// a state sees only the reporting blocks of its function, which have
// consecutive indices, so the cache answers nearly every report with one
// comparison. Keying the cache by the state rather than by the block matters:
// a block in a loop executes in a cycle of iteration states (the iteration
// counters wrap around), which a cache per block never matched.
//
// A state's cache is a table of kStateCacheSize = 64 entries of 8 bytes,
// taken at its first report from a pool, in which the tables of the states lie
// next to each other in the order of their first reports. The memory of the
// caches (the tables, their owners and the table pointer per state id) never
// exceeds the allowance BB_REPORT_CACHE_MB of dp.conf (default 50 MiB, 0
// turns the caches off). At the limit, a state taking a table discards the
// cache of another state, round robin, which only costs lookups in the hash
// table when that state reports again. With the default, about 100000 states
// get a table; measured on 640M (LULESH -s 10, 8974 states with reports)
// resp. 2.2G reports (miniFE 32^3, 17980 states), of which 52k resp. 49k were
// distinct, the caches used 4.6 resp. 9.2 MB and answered 88% resp. 99% of
// the reports. A cache growing up to 1024 entries for states with many
// reporting blocks (LULESH has up to 217 in one state) would answer 95% on
// LULESH and nothing more on miniFE; it was left out, as the extra misses
// cost LULESH below 0.5% of its run time, while the size every report would
// have to load costs all of them. A single direct mapped cache for all states
// (groups of 64 entries selected by the low bits of the state id) was 3-4%
// slower than these tables.
class ReportedBBRecorder {
 public:
  static constexpr std::size_t kDefaultCacheBytes = std::size_t{50} << 20;

  // cache_bytes: the allowance of the caches in front of the table, see the class comment
  explicit ReportedBBRecorder(std::size_t cache_bytes = kDefaultCacheBytes)
      : slots_(kInitialCapacity), cache_allowance_(cache_bytes) {
    if (cache_allowance_ < kBytesPerTable) {
      cache_allowance_ = 0;
      std::cerr << "DiscoPoP: warning: the caches of the basic block reports are turned off (BB_REPORT_CACHE_MB="
                << (cache_bytes >> 20) << " in dp.conf), which slows down the profiling\n";
      return;
    }
    // reserved only: the pages become resident when the tables are taken
    tables_.reserve(cache_allowance_ / kBytesPerTable * kStateCacheSize);
  }

  inline void Record(std::uint32_t bb_index, std::uint32_t source_state, std::uint32_t sink_state) {
    if (sink_state < table_of_state_.size()) {
      const CacheEntry* table = table_of_state_[sink_state];
      if (table != nullptr) {
        const CacheEntry& entry = table[bb_index & (kStateCacheSize - 1)];
        if (entry.bb_index == bb_index && entry.source_state == source_state) {
          return;
        }
      }
    }
    RecordInTable(bb_index, source_state, sink_state);
  }

  // the memory the caches occupy, never more than their allowance
  std::size_t CacheBytes() const {
    return table_of_state_.capacity() * sizeof(CacheEntry*) + owners_.size() * sizeof(std::uint32_t) +
           tables_.size() * sizeof(CacheEntry);
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
  static constexpr std::size_t kStateCacheSize = 64;  // entries per state, a power of two (see the class comment)
  struct CacheEntry {
    std::uint32_t bb_index = ~std::uint32_t{0};  // no block has this index
    std::uint32_t source_state = 0;
  };
  // a table and its owner
  static constexpr std::size_t kBytesPerTable = kStateCacheSize * sizeof(CacheEntry) + sizeof(std::uint32_t);
  struct Slot {
    std::uint64_t states = 0;
    std::uint32_t bb_index = 0;
    bool used = false;
  };

  // the execution was not in the sink state's cache: records it in the table and in the cache
  [[gnu::noinline]] void RecordInTable(std::uint32_t bb_index, std::uint32_t source_state, std::uint32_t sink_state) {
    CacheInState(bb_index, source_state, sink_state);

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

  // remembers the execution in the cache of the sink state, taking a table for the state if it has none
  void CacheInState(std::uint32_t bb_index, std::uint32_t source_state, std::uint32_t sink_state) {
    if (cache_allowance_ == 0) {
      return;
    }
    if (sink_state >= table_of_state_.size()) {
      // the table pointers of the states grow with the highest state id that reported; within the allowance
      const std::size_t needed = static_cast<std::size_t>(sink_state) + 1;
      std::size_t capacity = std::max(needed, 2 * table_of_state_.capacity());
      const std::size_t others = owners_.size() * sizeof(std::uint32_t) + tables_.size() * sizeof(CacheEntry);
      if (others + capacity * sizeof(CacheEntry*) > cache_allowance_) {
        capacity = needed;
        if (others + capacity * sizeof(CacheEntry*) > cache_allowance_) {
          return;  // the state stays without a cache
        }
      }
      std::vector<CacheEntry*> grown;
      grown.reserve(capacity);
      grown.assign(table_of_state_.begin(), table_of_state_.end());
      grown.resize(needed, nullptr);
      table_of_state_.swap(grown);
    }
    CacheEntry*& table = table_of_state_[sink_state];
    if (table == nullptr) {
      if (CacheBytes() + kBytesPerTable <= cache_allowance_ && tables_.size() < tables_.capacity()) {
        owners_.push_back(sink_state);
        tables_.resize(tables_.size() + kStateCacheSize);  // within the reserved capacity: no table moves
        table = tables_.data() + tables_.size() - kStateCacheSize;
      } else if (!owners_.empty()) {
        // at the limit: discard the cache of another state, round robin
        if (!limit_reached_) {
          limit_reached_ = true;
          std::cerr << "DiscoPoP: the caches of the basic block reports reached their allowance (BB_REPORT_CACHE_MB in "
                       "dp.conf), states now discard each other's caches, which slows down the profiling\n";
        }
        const std::uint32_t victim = next_victim_;
        next_victim_ = (next_victim_ + 1) % static_cast<std::uint32_t>(owners_.size());
        table_of_state_[owners_[victim]] = nullptr;
        owners_[victim] = sink_state;
        table = tables_.data() + static_cast<std::size_t>(victim) * kStateCacheSize;
        std::fill_n(table, kStateCacheSize, CacheEntry{});
      } else {
        return;
      }
    }
    table[bb_index & (kStateCacheSize - 1)] = CacheEntry{bb_index, source_state};
  }

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
  // the caches, see the class comment
  std::size_t cache_allowance_;
  std::vector<CacheEntry*> table_of_state_;    // per state id: its table in tables_, or nullptr
  std::vector<std::uint32_t> owners_;          // per table: the state using it
  std::vector<CacheEntry> tables_;             // kStateCacheSize entries per table, capacity reserved at once
  std::uint32_t next_victim_ = 0;
  bool limit_reached_ = false;
};
// End HA

class FirstAccessQueueChunk {
 public:
  explicit FirstAccessQueueChunk(std::size_t chunk_size) : buffer_size_(chunk_size) { buffer_.resize(chunk_size); }

  inline bool IsFull() const { return element_count_ == buffer_size_; }

  inline AccessInfo& GetNextAccessInfoBuffer() { return buffer_[element_count_++]; }

  std::future<std::vector<AccessInfo>*> GetEntryFuture() { return entry_boundary_first_addr_accesses.get_future(); }

  std::future<std::vector<AddressRecord>*> GetExitFuture() { return exit_boundary_summary.get_future(); }

  inline std::vector<AccessInfo>* GetBuffer() { return &buffer_; }

  inline std::size_t GetElementCount() const { return element_count_; }

  // grouped by address, in the order of the records of exit_boundary_summary (GroupEntryAccessesByAddress)
  std::promise<std::vector<AccessInfo>*> entry_boundary_first_addr_accesses;
  // one record per address the chunk touched: the state its last access left, and its number of entry accesses
  std::promise<std::vector<AddressRecord>*> exit_boundary_summary;

 private:
  std::vector<AccessInfo> buffer_;
  std::size_t element_count_ = 0;
  const std::size_t buffer_size_;
};

class SecondAccessQueueElement {
 public:
  SecondAccessQueueElement(std::future<std::vector<AccessInfo>*> fut_first_addr_accesses,
                           std::future<std::vector<AddressRecord>*> fut_exit_summary) {
    entry_boundary_first_addr_accesses = std::move(fut_first_addr_accesses);
    exit_boundary_summary = std::move(fut_exit_summary);
  }

  std::future<std::vector<AccessInfo>*> entry_boundary_first_addr_accesses;
  std::future<std::vector<AddressRecord>*> exit_boundary_summary;
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
