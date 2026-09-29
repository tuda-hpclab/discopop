#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/runtimeFunctionsGlobals.hpp"
#include "../../../../profiler/rtlib/runtimeFunctionsTypes.hpp"
#include "../../../../profiler/rtlib/runtimeFunctions.hpp"
#include "../../../../profiler/rtlib/memory/PerfectShadow.hpp"

using namespace __dp;

class FirstAccessQueueChunkTest : public ::testing::Test {};

// ctor
TEST_F(FirstAccessQueueChunkTest, testConstructor) {
    auto FAQC = FirstAccessQueueChunk(10);
}

// is_full false empty
TEST_F(FirstAccessQueueChunkTest, testIsFullFalseEmpty) {
    auto FAQC = FirstAccessQueueChunk(10);
    ASSERT_FALSE(FAQC.is_full());
}

// is_full false
TEST_F(FirstAccessQueueChunkTest, testIsFullFalse) {
    auto FAQC = FirstAccessQueueChunk(10);
    for(int i = 0; i < 5; ++i){
        FAQC.get_next_AccessInfo_buffer();
    }
    ASSERT_FALSE(FAQC.is_full());
}

// is_full true
TEST_F(FirstAccessQueueChunkTest, testIsFullTrue) {
    auto FAQC = FirstAccessQueueChunk(10);
    for(int i = 0; i < 10; i++){
        auto& dummy = FAQC.get_next_AccessInfo_buffer();
    }
    ASSERT_TRUE(FAQC.is_full());
}

// get_next_AccessInfo_buffer
TEST_F(FirstAccessQueueChunkTest, testGetNextAccessInfoBuffer) {
    auto FAQC = FirstAccessQueueChunk(10);
    while(!FAQC.is_full()){
        AccessInfo& buffer = FAQC.get_next_AccessInfo_buffer();
        buffer.lid = 1337;
        buffer.AAvar = 142;
        buffer.addr = 42;
        buffer.skip = true;
    }
    ASSERT_EQ(FAQC.get_element_count(), 10);

    // check stored values
    for(int i = 0; i < 10; ++i){
        ASSERT_EQ((*(FAQC.get_buffer()))[i].lid, 1337);
        ASSERT_EQ((*(FAQC.get_buffer()))[i].AAvar, 142);
        ASSERT_EQ((*(FAQC.get_buffer()))[i].addr, 42);
        ASSERT_EQ((*(FAQC.get_buffer()))[i].skip, true);
    }
}
