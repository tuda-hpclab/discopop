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

#include <cstdint>
#include <iostream>
#include <vector>

#include "lid_utils.hpp"
#include "runtimeFunctions.hpp"
#include "runtimeFunctionsGlobals.hpp"
#include "timer.hpp"

namespace dp {

void AddDep(DepType type, LID curr, LID dep_on, const char* var, std::int64_t aa_var, ADDR /*addr*/) {
#ifdef DP_INTERNAL_TIMER
  const auto timer = Timer(timers, TimerRegion::kAddDep);
#endif

  // hybrid analysis
  if (dep_on == 0 && type == kWaw) {
    type = kInit;
  }
  // End HA

  // Remove metadata to preserve result correctness and add metadata to `Dep`
  // object

  // register dependency. operator[] creates the set when the lid is seen for the first time.
  (*my_map)[curr].insert(Dep(type, dep_on, var, aa_var));

  if (dp_debug) {
    std::cout << "inserted dep [" << dputil::DecodeLid(curr) << ", ";
    switch (type) {
      case kRaw:
        std::cout << "RAW";
        break;
      case kWar:
        std::cout << "WAR";
        break;
      case kWaw:
        std::cout << "WAW";
        break;
      case kInit:
        std::cout << "INIT";
        break;
      default:
        break;
    }
    std::cout << ", " << dputil::DecodeLid(dep_on) << "] into deps (" << my_map->size() << ")" << std::endl;
  }
}

void AnalyzeSingleAccess(dp::AbstractShadow* smem, dp::AccessInfo& access) {
  // analyze data dependences
#ifdef DP_INTERNAL_TIMER
  const auto timer = Timer(timers, TimerRegion::kAnalyzeSingleAccess);
#endif

  if (access.is_read) {
    // hybrid analysis
    if (access.skip) {
      smem->InsertToRead(access.addr, access.lid);
      return;
    }
    // End HA
    const SigElement last_write = smem->TestInWrite(access.addr);
    // Every read, not only the ones that turn out to be RAWs: a read that found no earlier write
    // is still the read a later write has to come after, and leaving it out of the shadow made
    // that WAR depend on whether the read happened to open a chunk.
    smem->InsertToRead(access.addr, access.lid);
    if (last_write != 0 && last_write != 1) {
      // RAW
      AddDep(kRaw, access.lid, last_write, access.var, access.aa_var, access.addr);
    }

  } else {
    const SigElement last_write = smem->InsertToWrite(access.addr, access.lid);
    if (access.skip) {
      return;
    }
    const SigElement last_read = smem->TestInRead(access.addr);
    if (last_write == 0 || last_write == 1) {
      // INIT
      AddDep(kInit, access.lid, 0, access.var, access.aa_var, access.addr);
      // A read that came before this write is a WAR no matter whether a write came before it as
      // well. Asking only in the branch below used to lose those dependencies -- and the chunked
      // analysis made that the common case rather than a corner case, because every chunk starts
      // from an empty shadow, so "no earlier write" there only means "none in this chunk".
      if (last_read != 0 && last_read != 1) {
        AddDep(kWar, access.lid, last_read, access.var, access.aa_var, access.addr);
        // Clear intermediate read ops
        smem->InsertToRead(access.addr, 0);
      }
    } else {
      if (last_read != 0 && last_read != 1) {
        // WAR
        AddDep(kWar, access.lid, last_read, access.var, access.aa_var, access.addr);
        // Clear intermediate read ops
        smem->InsertToRead(access.addr, 0);
      } else {
        // WAW
        AddDep(kWaw, access.lid, last_write, access.var, access.aa_var, access.addr);
      }
    }
  }
}

void AnalyzeAccessOnSlot(ShadowSlot& slot, const AccessInfo& access) {
  // the same decisions as AnalyzeSingleAccess, on the values its shadow lookups would return
  if (access.is_read) {
    if (access.skip) {
      slot.last_read = access.lid;
      return;
    }
    const SigElement last_write = slot.last_write;
    slot.last_read = access.lid;
    if (last_write != 0 && last_write != 1) {
      AddDep(kRaw, access.lid, last_write, access.var, access.aa_var, access.addr);
    }
    return;
  }

  const SigElement last_write = slot.last_write;
  slot.last_write = access.lid;
  if (access.skip) {
    return;
  }
  const SigElement last_read = slot.last_read;
  if (last_write == 0 || last_write == 1) {
    AddDep(kInit, access.lid, 0, access.var, access.aa_var, access.addr);
    if (last_read != 0 && last_read != 1) {
      AddDep(kWar, access.lid, last_read, access.var, access.aa_var, access.addr);
      slot.last_read = 0;
    }
  } else if (last_read != 0 && last_read != 1) {
    AddDep(kWar, access.lid, last_read, access.var, access.aa_var, access.addr);
    slot.last_read = 0;
  } else {
    AddDep(kWaw, access.lid, last_write, access.var, access.aa_var, access.addr);
  }
}

std::vector<AddressRecord> GroupEntryAccessesByAddress(std::vector<AccessInfo>& entry_accesses,
                                                       const PerfectShadow2& chunk_shadow) {
  std::vector<AddressRecord> records;
  HashMap<std::int64_t, std::uint32_t> record_of_address;
  record_of_address.reserve(entry_accesses.size());
  std::vector<std::uint32_t> record_of_access;
  record_of_access.reserve(entry_accesses.size());
  for (const auto& access : entry_accesses) {
    const auto inserted = record_of_address.try_emplace(access.addr, static_cast<std::uint32_t>(records.size()));
    if (inserted.second) {
      records.push_back(AddressRecord{access.addr, 0, 0, 0});
    }
    const std::uint32_t record = inserted.first->second;
    ++records[record].num_entry_accesses;
    record_of_access.push_back(record);
  }

  // a stable counting sort by record
  std::vector<std::uint32_t> next_position(records.size());
  std::uint32_t position = 0;
  for (std::size_t record = 0; record < records.size(); ++record) {
    next_position[record] = position;
    position += records[record].num_entry_accesses;
  }
  std::vector<AccessInfo> grouped(entry_accesses.size());
  for (std::size_t access = 0; access < entry_accesses.size(); ++access) {
    grouped[next_position[record_of_access[access]]++] = entry_accesses[access];
  }
  entry_accesses.swap(grouped);

  const auto* reads = chunk_shadow.GetSigRead();
  const auto* writes = chunk_shadow.GetSigWrite();
  for (auto& record : records) {
    const auto read = reads->find(record.addr);
    record.last_read = read == reads->end() ? 0 : read->second;
    const auto write = writes->find(record.addr);
    record.last_write = write == writes->end() ? 0 : write->second;
  }
  return records;
}

void AnalyzeChunkOnSlots(HashMap<std::int64_t, ShadowSlot>& shadow, const std::vector<AccessInfo>& entry_accesses,
                         const std::vector<AddressRecord>& records) {
  std::size_t next_access = 0;
  for (const auto& record : records) {
    ShadowSlot& slot = shadow[record.addr];
    for (std::uint32_t i = 0; i < record.num_entry_accesses; ++i) {
      AnalyzeAccessOnSlot(slot, entry_accesses[next_access++]);
    }
    // the chunk's last accesses replace whatever the entry accesses left, as merging its shadow did
    slot.last_read = record.last_read;
    slot.last_write = record.last_write;
  }
}

void AnalyzeSingleAccessOnMainThread(dp::AccessInfo& access) {
  AnalyzeSingleAccess(single_threaded_execution_smem, access);
}

}  // namespace dp
