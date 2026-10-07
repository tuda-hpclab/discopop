#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/runtimeFunctionsGlobals.hpp"
#include "../../../../profiler/rtlib/runtimeFunctionsTypes.hpp"
#include "../../../../profiler/rtlib/runtimeFunctions.hpp"

using namespace __dp;

class FirstAccessQueueTest : public ::testing::Test {};

TEST_F(FirstAccessQueueTest, testConstructor) {
    auto FAQ = FirstAccessQueue(10);
}


// FAQ test get empty
TEST_F(FirstAccessQueueTest, testGetEmpty) {
    auto FAQ = FirstAccessQueue(10);
    ASSERT_TRUE(firstAccessQueue.empty());
    ASSERT_EQ(firstAccessQueue.get(&secondAccessQueue), nullptr);
}

// FAQ test push
TEST_F(FirstAccessQueueTest, testPush) {
    auto FAQ = FirstAccessQueue(10);
    ASSERT_TRUE(FAQ.empty());
    auto FAQC_ptr = new FirstAccessQueueChunk(100);
    FAQ.push(FAQC_ptr);
    ASSERT_FALSE(FAQ.empty());
    delete FAQC_ptr;
}

// FAQ test can_accept_entries
TEST_F(FirstAccessQueueTest, testCanAcceptEntries) {
    auto FAQ = FirstAccessQueue(3);
    auto SAQ = SecondAccessQueue(10);
    ASSERT_TRUE(FAQ.empty());
    auto FAQC_ptr_1 = new FirstAccessQueueChunk(100);
    auto FAQC_ptr_2 = new FirstAccessQueueChunk(100);
    auto FAQC_ptr_3 = new FirstAccessQueueChunk(100);

    ASSERT_TRUE(FAQ.can_accept_entries());
    FAQ.push(FAQC_ptr_1);
    ASSERT_TRUE(FAQ.can_accept_entries());
    FAQ.push(FAQC_ptr_2);
    ASSERT_TRUE(FAQ.can_accept_entries());
    FAQ.push(FAQC_ptr_3);
    ASSERT_FALSE(FAQ.can_accept_entries());
    FAQ.get(&SAQ);
    ASSERT_TRUE(FAQ.can_accept_entries());
    // FAQ.get registers a SecondAccessQueueElement per chunk; nobody consumes them here
    while (auto saqe = SAQ.get()) {
        delete saqe;
    }

    delete FAQC_ptr_1;
    delete FAQC_ptr_2;
    delete FAQC_ptr_3;
}

// FAQ test empty
TEST_F(FirstAccessQueueTest, testEmpty) {
    auto FAQ = FirstAccessQueue(3);
    auto SAQ = SecondAccessQueue(10);
    ASSERT_TRUE(FAQ.empty());
    auto FAQC_ptr_1 = new FirstAccessQueueChunk(100);
    auto FAQC_ptr_2 = new FirstAccessQueueChunk(100);
    auto FAQC_ptr_3 = new FirstAccessQueueChunk(100);


    FAQ.push(FAQC_ptr_1);
    ASSERT_FALSE(FAQ.empty());
    FAQ.push(FAQC_ptr_2);
    ASSERT_FALSE(FAQ.empty());
    FAQ.push(FAQC_ptr_3);
    ASSERT_FALSE(FAQ.empty());

    FAQ.get(&SAQ);
    ASSERT_FALSE(FAQ.empty());
    FAQ.get(&SAQ);
    ASSERT_FALSE(FAQ.empty());
    FAQ.get(&SAQ);
    ASSERT_TRUE(FAQ.empty());
    // FAQ.get registers a SecondAccessQueueElement per chunk; nobody consumes them here
    while (auto saqe = SAQ.get()) {
        delete saqe;
    }

    delete FAQC_ptr_1;
    delete FAQC_ptr_2;
    delete FAQC_ptr_3;

}

// FAQ test: set_max_size changes the limit checked by can_accept_entries, a limit of 0 is clamped to 1
TEST_F(FirstAccessQueueTest, testSetMaxSize) {
    auto FAQ = FirstAccessQueue(100);
    auto FAQC_ptr_1 = new FirstAccessQueueChunk(100);
    auto FAQC_ptr_2 = new FirstAccessQueueChunk(100);

    FAQ.set_max_size(0);
    ASSERT_TRUE(FAQ.can_accept_entries());
    FAQ.push(FAQC_ptr_1);
    ASSERT_FALSE(FAQ.can_accept_entries());
    FAQ.set_max_size(2);
    ASSERT_TRUE(FAQ.can_accept_entries());
    FAQ.push(FAQC_ptr_2);
    ASSERT_FALSE(FAQ.can_accept_entries());

    delete FAQC_ptr_1;
    delete FAQC_ptr_2;
}
