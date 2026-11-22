#include <gtest/gtest.h>

#include <cstdint>
#include <random>
#include <set>
#include <string>
#include <tuple>
#include <vector>

#include "memory/PerfectShadow.hpp"
#include "runtimeFunctions.hpp"
#include "runtimeFunctionsGlobals.hpp"

using namespace dp;

// The consumer of the second access queue analyzes a chunk address by address on one bucket per address
// (GroupEntryAccessesByAddress in the worker, AnalyzeChunkOnSlots in the consumer). It has to find the dependencies and
// leave the state the former analysis did: every entry access in its order through AnalyzeSingleAccess on a
// PerfectShadow2, then the chunk's exit state merged into it.
class SlotAnalysisTest : public ::testing::Test {
protected:
  void SetUp() override { previous_map_ = my_map; }

  void TearDown() override { my_map = previous_map_; }

private:
  DepMap *previous_map_ = nullptr;
};

namespace {

constexpr std::int64_t kNumAddresses = 6;
const char *const kVars[kNumAddresses] = {"a", "b", "c", "d", "e", "f"};

struct WorkerResult {
  std::vector<AccessInfo> entry_accesses;
  PerfectShadow2 shadow;
};

// What a first queue worker does with a chunk (without the deduplication, which only drops repeats before both
// variants see them): the accesses up to the first write of an address are entry accesses, the rest is analyzed
// against the chunk local shadow.
void RunWorker(const std::vector<AccessInfo> &chunk, WorkerResult &result) {
  DepMap worker_deps;
  my_map = &worker_deps;
  for (AccessInfo access : chunk) {
    if (result.shadow.TestInWrite(access.addr) == 0) {
      result.entry_accesses.push_back(access);
      if (access.is_read) {
        result.shadow.InsertToRead(access.addr, access.lid);
      } else {
        result.shadow.InsertToWrite(access.addr, access.lid);
      }
    } else {
      AnalyzeSingleAccess(&result.shadow, access);
    }
  }
  my_map = nullptr;
}

std::vector<std::vector<AccessInfo>> RandomChunks(std::uint32_t seed) {
  std::mt19937 random(seed);
  std::uniform_int_distribution<std::int64_t> address(0, kNumAddresses - 1);
  std::uniform_int_distribution<LID> lid(2, 12);
  std::uniform_int_distribution<int> percent(0, 99);
  std::uniform_int_distribution<int> chunk_size(0, 30);
  std::vector<std::vector<AccessInfo>> chunks(8);
  for (auto &chunk : chunks) {
    for (int i = chunk_size(random); i > 0; --i) {
      const std::int64_t addr = address(random);
      chunk.emplace_back(percent(random) < 55, lid(random), kVars[addr], 0, 8 * addr + 8, percent(random) < 10);
    }
  }
  return chunks;
}

// Dep has no operator==; the sets compare with EqDep, which ignores aa_var.
std::set<std::tuple<LID, int, LID, std::string>> Flatten(const DepMap &deps) {
  std::set<std::tuple<LID, int, LID, std::string>> flat;
  for (const auto &sink : deps) {
    for (const auto &dep : sink.second) {
      flat.emplace(sink.first, static_cast<int>(dep.type), dep.dep_on, dep.var);
    }
  }
  return flat;
}

} // namespace

TEST_F(SlotAnalysisTest, testFindsTheDependenciesAndTheStateOfTheFormerAnalysis) {
  for (std::uint32_t seed = 0; seed < 300; ++seed) {
    DepMap former_deps;
    DepMap slot_deps;
    PerfectShadow2 former_shadow;
    HashMap<std::int64_t, ShadowSlot> slots;

    for (const auto &chunk : RandomChunks(seed)) {
      WorkerResult worker;
      RunWorker(chunk, worker);

      my_map = &former_deps;
      std::vector<AccessInfo> in_order = worker.entry_accesses;
      for (auto &access : in_order) {
        AnalyzeSingleAccess(&former_shadow, access);
      }
      for (const auto &entry : worker.shadow.Summarize()) {
        former_shadow.UpdateInRead(entry.addr, entry.last_read);
        former_shadow.UpdateInWrite(entry.addr, entry.last_write);
      }

      my_map = &slot_deps;
      std::vector<AccessInfo> grouped = worker.entry_accesses;
      const std::vector<AddressRecord> records = GroupEntryAccessesByAddress(grouped, worker.shadow);
      AnalyzeChunkOnSlots(slots, grouped, records);
      my_map = nullptr;
    }

    ASSERT_FALSE(Flatten(former_deps).empty());
    ASSERT_EQ(Flatten(former_deps), Flatten(slot_deps)) << "seed " << seed;
    for (std::int64_t addr = 8; addr <= 8 * kNumAddresses; addr += 8) {
      const auto slot = slots.find(addr);
      const ShadowSlot state = slot == slots.end() ? ShadowSlot{} : slot->second;
      ASSERT_EQ(former_shadow.TestInRead(addr), state.last_read) << "seed " << seed << " addr " << addr;
      ASSERT_EQ(former_shadow.TestInWrite(addr), state.last_write) << "seed " << seed << " addr " << addr;
    }
  }
}

TEST_F(SlotAnalysisTest, testGroupingKeepsTheOrderOfTheAccessesOfAnAddress) {
  PerfectShadow2 chunk_shadow;
  chunk_shadow.InsertToRead(8, 5);
  chunk_shadow.InsertToWrite(8, 6);
  chunk_shadow.InsertToWrite(16, 0);
  std::vector<AccessInfo> entry_accesses = {AccessInfo(true, 2, "a", 0, 8), AccessInfo(true, 3, "b", 0, 16),
                                            AccessInfo(true, 4, "a", 0, 8), AccessInfo(false, 5, "a", 0, 8)};

  const std::vector<AddressRecord> records = GroupEntryAccessesByAddress(entry_accesses, chunk_shadow);

  ASSERT_EQ(records.size(), 2);
  EXPECT_EQ(records[0].addr, 8);
  EXPECT_EQ(records[0].num_entry_accesses, 3);
  EXPECT_EQ(records[0].last_read, 5);
  EXPECT_EQ(records[0].last_write, 6);
  EXPECT_EQ(records[1].addr, 16);
  EXPECT_EQ(records[1].num_entry_accesses, 1);
  EXPECT_EQ(records[1].last_read, 0);
  EXPECT_EQ(records[1].last_write, 0);
  ASSERT_EQ(entry_accesses.size(), 4);
  EXPECT_EQ(entry_accesses[0].lid, 2);
  EXPECT_EQ(entry_accesses[1].lid, 4);
  EXPECT_EQ(entry_accesses[2].lid, 5);
  EXPECT_EQ(entry_accesses[3].lid, 3);
}
