#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/runtimeFunctionsGlobals.hpp"
#include "../../../../profiler/rtlib/runtimeFunctionsTypes.hpp"
#include "../../../../profiler/rtlib/runtimeFunctions.hpp"
#include "../../../../profiler/rtlib/memory/PerfectShadow.hpp"

using namespace __dp;

class FirstAccessQueueChunkBufferTest : public ::testing::Test {};

// ctor
TEST_F(FirstAccessQueueChunkBufferTest, testConstructor) {
    auto FAQCB = FirstAccessQueueChunkBuffer(10);
}

// get queue size
TEST_F(FirstAccessQueueChunkBufferTest, testQueueSize) {
    auto FAQCB = FirstAccessQueueChunkBuffer(10);
    ASSERT_EQ(FAQCB.get_queue_size(), 0);
    FAQCB.prepare_chunk_if_required(10);
    ASSERT_EQ(FAQCB.get_queue_size(), 1);
}

// prepare if required empty
TEST_F(FirstAccessQueueChunkBufferTest, testPrepareEmpty) {
    auto FAQCB = FirstAccessQueueChunkBuffer(10);
    FAQCB.prepare_chunk_if_required(10);
    ASSERT_EQ(FAQCB.get_queue_size(), 1);
}


// prepare if required yes
TEST_F(FirstAccessQueueChunkBufferTest, testPrepareRequiredYes) {
    auto FAQCB = FirstAccessQueueChunkBuffer(10);
    FAQCB.prepare_chunk_if_required(10);
    FAQCB.prepare_chunk_if_required(10);
    FAQCB.prepare_chunk_if_required(10);
    ASSERT_EQ(FAQCB.get_queue_size(), 3);
    FAQCB.prepare_chunk_if_required(10);
    ASSERT_EQ(FAQCB.get_queue_size(), 4);
}

// prepare if required no
TEST_F(FirstAccessQueueChunkBufferTest, testPrepareRequiredNo) {
    auto FAQCB = FirstAccessQueueChunkBuffer(10);
    ASSERT_EQ(FAQCB.get_queue_size(), 0);
    for(int i = 0; i < 10; ++i){
        FAQCB.prepare_chunk_if_required(10);
    }
    ASSERT_EQ(FAQCB.get_queue_size(), 10);
    FAQCB.prepare_chunk_if_required(10);
    ASSERT_EQ(FAQCB.get_queue_size(), 10);
}

// get prepared chunk exists
TEST_F(FirstAccessQueueChunkBufferTest, testGetPreparedChunkExists) {
    auto FAQCB = FirstAccessQueueChunkBuffer(10);
    ASSERT_EQ(FAQCB.get_queue_size(), 0);
    FAQCB.prepare_chunk_if_required(10);
    FAQCB.prepare_chunk_if_required(10);
    FAQCB.prepare_chunk_if_required(10);
    ASSERT_EQ(FAQCB.get_queue_size(), 3);

    auto faqc_ptr = FAQCB.get_prepared_chunk(10);
    ASSERT_EQ(FAQCB.get_queue_size(), 2);
    ASSERT_EQ(faqc_ptr->get_element_count(), 0);
    delete faqc_ptr;
}

// get prepared chunk empty
TEST_F(FirstAccessQueueChunkBufferTest, testGetPreparedChunkDoesntExist) {
    auto FAQCB = FirstAccessQueueChunkBuffer(10);
    ASSERT_EQ(FAQCB.get_queue_size(), 0);
    auto faqc_ptr = FAQCB.get_prepared_chunk(10);
    ASSERT_EQ(faqc_ptr->get_element_count(), 0);
    ASSERT_EQ(FAQCB.get_queue_size(), 0);

    FAQCB.prepare_chunk_if_required(10);
    FAQCB.prepare_chunk_if_required(10);
    ASSERT_EQ(FAQCB.get_queue_size(), 2);

    delete faqc_ptr;
}
