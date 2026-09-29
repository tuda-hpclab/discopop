#include <gtest/gtest.h>

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
}
