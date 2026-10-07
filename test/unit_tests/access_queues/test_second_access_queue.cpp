#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <thread>

#include "../../../../profiler/rtlib/runtimeFunctionsGlobals.hpp"
#include "../../../../profiler/rtlib/runtimeFunctionsTypes.hpp"
#include "../../../../profiler/rtlib/runtimeFunctions.hpp"

using namespace __dp;

class SecondAccessQueueTest : public ::testing::Test {};

// Test SAQ constructor
TEST_F(SecondAccessQueueTest, testConstructor) {
    auto SAQ = SecondAccessQueue(10);
    ASSERT_TRUE(SAQ.empty());
}

// Test SAQ get empty
TEST_F(SecondAccessQueueTest, testGetEmpty) {
    auto SAQ = SecondAccessQueue(10);
    ASSERT_EQ(SAQ.get(), nullptr);
}

// Test SAQ push and get
TEST_F(SecondAccessQueueTest, testPush) {
    auto SAQ = SecondAccessQueue(10);

    ASSERT_TRUE(SAQ.empty());
    int dummy_int = 42;
    void* dummy_ptr = &dummy_int;
    SAQ.push((SecondAccessQueueElement*) dummy_ptr);
    ASSERT_FALSE(SAQ.empty());
    auto dummy = (void*) SAQ.get();
    ASSERT_EQ(dummy_ptr, dummy);
    ASSERT_TRUE(SAQ.empty());
}

// FAQ_SAQ test push & get
TEST_F(SecondAccessQueueTest, testPushAndGet) {
    auto FAQ = FirstAccessQueue(10);
    auto SAQ = SecondAccessQueue(10);
    ASSERT_TRUE(FAQ.empty());
    auto FAQC_ptr = new FirstAccessQueueChunk(100);
    FAQ.push(FAQC_ptr);
    ASSERT_FALSE(FAQ.empty());
    auto chunk_ptr = FAQ.get(&SAQ);
    ASSERT_FALSE(SAQ.empty());
    auto dummy = SAQ.get();
    ASSERT_TRUE(SAQ.empty());
    ASSERT_EQ(chunk_ptr, FAQC_ptr);
    ASSERT_TRUE(FAQ.empty());
    delete FAQC_ptr;
    delete dummy;
}

// SAQ test: push blocks while the queue is at its limit and continues once the consumer takes an element
TEST_F(SecondAccessQueueTest, testPushBlocksWhenFull) {
    auto SAQ = SecondAccessQueue(1);
    int dummy_1 = 1, dummy_2 = 2;
    SAQ.push((SecondAccessQueueElement*) &dummy_1);

    std::atomic<bool> pushed(false);
    std::thread producer([&]() {
        SAQ.push((SecondAccessQueueElement*) &dummy_2);
        pushed = true;
    });
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    ASSERT_FALSE(pushed);

    ASSERT_EQ((void*) SAQ.get(), (void*) &dummy_1);
    producer.join();
    ASSERT_TRUE(pushed);
    ASSERT_EQ((void*) SAQ.get(), (void*) &dummy_2);
    ASSERT_TRUE(SAQ.empty());
}

// SAQ test: set_max_size raises the limit, a limit of 0 is clamped to 1
TEST_F(SecondAccessQueueTest, testSetMaxSize) {
    auto SAQ = SecondAccessQueue(1);
    SAQ.set_max_size(0);
    int dummy = 42;
    SAQ.push((SecondAccessQueueElement*) &dummy);  // must not block: the limit is at least 1
    SAQ.set_max_size(2);
    SAQ.push((SecondAccessQueueElement*) &dummy);  // must not block: the limit is 2 now
    ASSERT_NE(SAQ.get(), nullptr);
    ASSERT_NE(SAQ.get(), nullptr);
    ASSERT_TRUE(SAQ.empty());
}
