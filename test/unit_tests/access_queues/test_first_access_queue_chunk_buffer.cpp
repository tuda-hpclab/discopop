#include <gtest/gtest.h>

#include "../../../profiler/rtlib/runtimeFunctionsGlobals.hpp"
#include "../../../profiler/rtlib/runtimeFunctionsTypes.hpp"
#include "../../../profiler/rtlib/runtimeFunctions.hpp"
#include "../../../profiler/rtlib/memory/PerfectShadow.hpp"

using namespace __dp;

class FirstAccessQueueChunkBufferTest : public ::testing::Test {};

// the buffer does not free the chunks it still holds when it is destroyed
static void delete_prepared_chunks(FirstAccessQueueChunkBuffer &FAQCB) {
    while (FAQCB.get_queue_size() > 0) {
        delete FAQCB.get_prepared_chunk(10);
    }
}

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
    delete_prepared_chunks(FAQCB);
}

// prepare if required empty
TEST_F(FirstAccessQueueChunkBufferTest, testPrepareEmpty) {
    auto FAQCB = FirstAccessQueueChunkBuffer(10);
    FAQCB.prepare_chunk_if_required(10);
    ASSERT_EQ(FAQCB.get_queue_size(), 1);
    delete_prepared_chunks(FAQCB);
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
    delete_prepared_chunks(FAQCB);
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
    delete_prepared_chunks(FAQCB);
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
    delete_prepared_chunks(FAQCB);
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
    delete_prepared_chunks(FAQCB);
}
