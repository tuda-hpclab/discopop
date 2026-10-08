#include <gtest/gtest.h>

#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

#include "../../../profiler/rtlib/Immortal.hpp"
#include "../../../profiler/rtlib/runtimeFunctionsTypes.hpp"

using namespace __dp;

namespace {

// Records what the storage does to the object it holds. The point of ImmortalStorage is that the
// compiler never destroys that object on its own, so the counters have to be observable from
// outside the storage.
struct Tracked {
  static int constructed;
  static int destroyed;
  static int last_argument;

  Tracked() { ++constructed; }
  explicit Tracked(const int argument) {
    ++constructed;
    last_argument = argument;
  }
  ~Tracked() { ++destroyed; }

  int value = 7;
};

int Tracked::constructed = 0;
int Tracked::destroyed = 0;
int Tracked::last_argument = 0;

} // namespace

// The storage of a global whose lifetime the runtime manages by hand, so that __dp_finalize can
// still use it after the target's own globals have been torn down. The union member is never
// destroyed by the compiler; construct() and destroy() bracket its lifetime instead.
class ImmortalStorageTest : public ::testing::Test {
protected:
  void SetUp() override {
    Tracked::constructed = 0;
    Tracked::destroyed = 0;
    Tracked::last_argument = 0;
  }
};

TEST_F(ImmortalStorageTest, testTheStorageLeavesItsObjectUnconstructed) {
  {
    ImmortalStorage<Tracked> storage;
  }

  EXPECT_EQ(Tracked::constructed, 0);
}

// the whole point: leaving the scope must not reach the object
TEST_F(ImmortalStorageTest, testLeavingTheScopeDoesNotDestroyTheObject) {
  {
    ImmortalStorage<Tracked> storage;
    storage.construct();
    ASSERT_EQ(Tracked::constructed, 1);
  }

  EXPECT_EQ(Tracked::destroyed, 0);
}

TEST_F(ImmortalStorageTest, testDestroyingTheObjectRunsItsDestructorExactlyOnce) {
  ImmortalStorage<Tracked> storage;
  storage.construct();

  storage.destroy();

  EXPECT_EQ(Tracked::destroyed, 1);
}

TEST_F(ImmortalStorageTest, testTheObjectCanBeConstructedAgainAfterItWasDestroyed) {
  ImmortalStorage<Tracked> storage;
  storage.construct();
  storage.destroy();

  storage.construct();

  EXPECT_EQ(Tracked::constructed, 2);
  EXPECT_EQ(Tracked::destroyed, 1);
  storage.destroy();
}

TEST_F(ImmortalStorageTest, testConstructionArgumentsReachTheObject) {
  ImmortalStorage<Tracked> storage;

  storage.construct(42);

  EXPECT_EQ(Tracked::last_argument, 42);
  storage.destroy();
}

TEST_F(ImmortalStorageTest, testTheConstructedObjectIsReachedThroughTheStorage) {
  ImmortalStorage<Tracked> storage;
  storage.construct();

  EXPECT_EQ(storage.value.value, 7);
  storage.destroy();
}

// Callers bind a reference to `value` at namespace scope, which requires the address to be an
// address constant -- established before any initializer runs and unchanged by construct().
TEST_F(ImmortalStorageTest, testTheAddressOfTheObjectDoesNotChange) {
  ImmortalStorage<Tracked> storage;
  const Tracked *const before = &storage.value;

  storage.construct();

  EXPECT_EQ(&storage.value, before);
  storage.destroy();
}

// The instantiations the runtime actually uses, see runtimeFunctionsGlobals.cpp. They are
// exercised here because the ones at namespace scope only complete their cycle when a profiled
// program shuts down.
TEST_F(ImmortalStorageTest, testTheGlobalsOfTheRuntimeCompleteTheirLifetime) {
  {
    ImmortalStorage<std::unordered_map<char *, long>> cuec;
    cuec.construct();
    cuec.value[nullptr] = 1;
    EXPECT_EQ(cuec.value.size(), 1u);
    cuec.destroy();
  }
  {
    ImmortalStorage<std::vector<std::uint32_t>> calls_without_executed_transitions;
    calls_without_executed_transitions.construct();
    calls_without_executed_transitions.value.push_back(3);
    EXPECT_EQ(calls_without_executed_transitions.value.size(), 1u);
    calls_without_executed_transitions.destroy();
  }
  {
    ImmortalStorage<std::vector<const char *>> registered_bb_deps;
    registered_bb_deps.construct();
    registered_bb_deps.value.push_back("0=1 NOM RAW 2|x(3)");
    EXPECT_EQ(registered_bb_deps.value.size(), 1u);
    registered_bb_deps.destroy();
  }
  {
    ImmortalStorage<FirstAccessQueue> first_access_queue;
    first_access_queue.construct(4);
    EXPECT_TRUE(first_access_queue.value.empty());
    first_access_queue.destroy();
  }
  {
    ImmortalStorage<SecondAccessQueue> second_access_queue;
    second_access_queue.construct(4);
    EXPECT_TRUE(second_access_queue.value.empty());
    second_access_queue.destroy();
  }
  {
    ImmortalStorage<FirstAccessQueueChunkBuffer> chunk_buffer;
    chunk_buffer.construct(1);
    EXPECT_EQ(chunk_buffer.value.get_queue_size(), 0u);
    chunk_buffer.destroy();
  }
}
