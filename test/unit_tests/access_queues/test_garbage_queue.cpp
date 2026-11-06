#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <thread>
#include <vector>

#include "memory/PerfectShadow.hpp"
#include "runtimeFunctionsTypes.hpp"

using namespace dp;

namespace {

RetiredChunk MakeChunk() {
    RetiredChunk chunk;
    chunk.entry_accesses = new std::vector<AccessInfo>(3);
    chunk.exit_shadow = new PerfectShadow2();
    return chunk;
}

}  // namespace

class GarbageQueueTest : public ::testing::Test {};

// A retired chunk comes out again, and the queue refuses chunks beyond its limit
TEST_F(GarbageQueueTest, testRetireAndTake) {
    GarbageQueue queue(2);
    RetiredChunk a = MakeChunk();
    RetiredChunk b = MakeChunk();
    RetiredChunk c = MakeChunk();
    ASSERT_TRUE(queue.TryRetire(a));
    ASSERT_TRUE(queue.TryRetire(b));
    ASSERT_FALSE(queue.TryRetire(c));  // full: the caller keeps ownership
    c.Destroy();

    RetiredChunk taken;
    ASSERT_TRUE(queue.Take(&taken));
    ASSERT_EQ(taken.entry_accesses, a.entry_accesses);
    taken.Destroy();
    ASSERT_TRUE(queue.Take(&taken));
    ASSERT_EQ(taken.exit_shadow, b.exit_shadow);
    taken.Destroy();
}

// A limit of 0 never accepts anything (CLEANUP_WORKERS=0)
TEST_F(GarbageQueueTest, testZeroLimitRefusesEverything) {
    GarbageQueue queue(0);
    RetiredChunk a = MakeChunk();
    ASSERT_FALSE(queue.TryRetire(a));
    a.Destroy();
}

// After Close, pending chunks are still handed out, then Take reports the end; new chunks are refused
TEST_F(GarbageQueueTest, testCloseDrainsPendingChunks) {
    GarbageQueue queue(4);
    RetiredChunk a = MakeChunk();
    ASSERT_TRUE(queue.TryRetire(a));
    queue.Close();

    RetiredChunk b = MakeChunk();
    ASSERT_FALSE(queue.TryRetire(b));
    b.Destroy();

    RetiredChunk taken;
    ASSERT_TRUE(queue.Take(&taken));
    taken.Destroy();
    ASSERT_FALSE(queue.Take(&taken));
}

// Take blocks until a chunk arrives, and Close wakes a blocked taker
TEST_F(GarbageQueueTest, testTakeBlocksUntilRetireOrClose) {
    GarbageQueue queue(4);
    std::atomic<int> taken_count(0);
    std::thread consumer([&]() {
        RetiredChunk chunk;
        while (queue.Take(&chunk)) {
            chunk.Destroy();
            ++taken_count;
        }
    });
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    ASSERT_EQ(taken_count.load(), 0);

    RetiredChunk a = MakeChunk();
    ASSERT_TRUE(queue.TryRetire(a));
    queue.Close();
    consumer.join();
    ASSERT_EQ(taken_count.load(), 1);
}

// Reopen makes a closed queue usable for the next initialization of the runtime
TEST_F(GarbageQueueTest, testReopen) {
    GarbageQueue queue(1);
    queue.Close();
    queue.Reopen();
    RetiredChunk a = MakeChunk();
    ASSERT_TRUE(queue.TryRetire(a));
    RetiredChunk taken;
    ASSERT_TRUE(queue.Take(&taken));
    taken.Destroy();
}

// Several cleanup workers free everything exactly once
TEST_F(GarbageQueueTest, testSeveralWorkersDrainEverything) {
    GarbageQueue queue(8);
    std::atomic<int> freed(0);
    std::vector<std::thread> workers;
    for (int i = 0; i < 3; ++i) {
        workers.emplace_back([&]() {
            RetiredChunk chunk;
            while (queue.Take(&chunk)) {
                chunk.Destroy();
                ++freed;
            }
        });
    }
    int accepted = 0;
    for (int i = 0; i < 100; ++i) {
        RetiredChunk chunk = MakeChunk();
        if (queue.TryRetire(chunk)) {
            ++accepted;
        } else {
            chunk.Destroy();
        }
    }
    queue.Close();
    for (auto& worker : workers) {
        worker.join();
    }
    ASSERT_EQ(freed.load(), accepted);
}
