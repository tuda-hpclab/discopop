#include <gtest/gtest.h>

#include "runtimeFunctionsGlobals.hpp"
#include "runtimeFunctionsTypes.hpp"
#include "runtimeFunctions.hpp"
#include "memory/PerfectShadow.hpp"

using namespace dp;

class SecondAccessQueueElementTest : public ::testing::Test {};

// Test SAQE constructor
TEST_F(SecondAccessQueueElementTest, testConstructor) {
    auto buffer = new FirstAccessQueueChunk(100);
    auto SAQE = new SecondAccessQueueElement(std::move(buffer->GetEntryFuture()), std::move(buffer->GetExitFuture()));

    auto buffer_vector_ptr = new std::vector<AccessInfo>{AccessInfo(false, 1337, nullptr, 0, 42, false)};
    auto buffer_summary_ptr = new std::vector<AddressRecord>{AddressRecord{42, 7, 1337, 1}};
    buffer->entry_boundary_first_addr_accesses.set_value(buffer_vector_ptr);
    buffer->exit_boundary_summary.set_value(buffer_summary_ptr);

    std::vector<AccessInfo>* promised_vector_ptr = SAQE->entry_boundary_first_addr_accesses.get();
    std::vector<AddressRecord>* promised_summary_ptr = SAQE->exit_boundary_summary.get();

    ASSERT_EQ((*promised_vector_ptr)[0].lid, 1337);
    ASSERT_EQ((*promised_vector_ptr)[0].addr, 42);
    ASSERT_EQ(promised_summary_ptr->size(), 1);
    ASSERT_EQ((*promised_summary_ptr)[0].addr, 42);
    ASSERT_EQ((*promised_summary_ptr)[0].last_read, 7);
    ASSERT_EQ((*promised_summary_ptr)[0].last_write, 1337);
    ASSERT_EQ((*promised_summary_ptr)[0].num_entry_accesses, 1);

    delete promised_vector_ptr;
    delete promised_summary_ptr;
    delete SAQE;
    delete buffer;
}
