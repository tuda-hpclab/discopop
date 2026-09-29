#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/runtimeFunctionsGlobals.hpp"
#include "../../../../profiler/rtlib/runtimeFunctionsTypes.hpp"
#include "../../../../profiler/rtlib/runtimeFunctions.hpp"
#include "../../../../profiler/rtlib/memory/PerfectShadow.hpp"

using namespace __dp;

class SecondAccessQueueElementTest : public ::testing::Test {};

// Test SAQE constructor
TEST_F(SecondAccessQueueElementTest, testConstructor) {
    auto buffer = new FirstAccessQueueChunk(100);
    auto SAQE = new SecondAccessQueueElement(std::move(buffer->get_entry_future()), std::move(buffer->get_exit_future()));

    auto buffer_vector_ptr = new std::vector<AccessInfo>{AccessInfo(false, 1337, nullptr, 0, 42, false)};
    auto buffer_smem_ptr = new PerfectShadow();
    buffer->entry_boundary_first_addr_accesses.set_value(buffer_vector_ptr);
    buffer->exit_boundary_SMem.set_value(buffer_smem_ptr);

    std::vector<AccessInfo>* promised_vector_ptr = SAQE->entry_boundary_first_addr_accesses.get();
    AbstractShadow* promised_smem_ptr = SAQE->exit_boundary_SMem.get();

    ASSERT_EQ((*promised_vector_ptr)[0].lid, 1337);
    ASSERT_EQ((*promised_vector_ptr)[0].addr, 42);

    delete promised_vector_ptr;
    delete promised_smem_ptr;
    delete SAQE;
    delete buffer;
}
