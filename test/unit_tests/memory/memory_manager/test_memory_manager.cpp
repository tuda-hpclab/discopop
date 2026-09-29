#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/memory/MemoryManager.hpp"

#include <cstdint>
#include <vector>

// Tests for old version (i.e., capturing functionality)

class MemoryManagerTest : public ::testing::Test {};

TEST_F(MemoryManagerTest, testConstructor) {
  auto mm = __dp::MemoryManager{};

  ASSERT_EQ(mm.get_smallest_allocated_addr(), std::numeric_limits<ADDR>::max());
  ASSERT_EQ(mm.get_largest_allocated_addr(), std::numeric_limits<ADDR>::min());

  for (auto i = 1; i < 1024; i++) {
    ASSERT_EQ(mm.get_next_free_memory_region_id(), i);
  }

  ASSERT_EQ(mm.get_smallest_allocated_addr(), std::numeric_limits<ADDR>::max());
  ASSERT_EQ(mm.get_largest_allocated_addr(), std::numeric_limits<ADDR>::min());
}

TEST_F(MemoryManagerTest, testStack) {
  auto mm = __dp::MemoryManager{};

  mm.enter_new_function();
  mm.update_stack_addresses(0x1000, 0x2000);
  mm.enter_new_function();
  mm.update_stack_addresses(0x3000, 0x4000);
  mm.enter_new_function();
  mm.update_stack_addresses(0x5000, 0x6000);

  auto addr = mm.pop_last_stack_address();
  ASSERT_EQ(addr.first, 0x5000);
  ASSERT_EQ(addr.second, 0x6000);

  addr = mm.pop_last_stack_address();
  ASSERT_EQ(addr.first, 0x3000);
  ASSERT_EQ(addr.second, 0x4000);

  addr = mm.pop_last_stack_address();
  ASSERT_EQ(addr.first, 0x1000);
  ASSERT_EQ(addr.second, 0x2000);
}

TEST_F(MemoryManagerTest, testUpdateStackAddresses) {
  auto mm = __dp::MemoryManager{};

  mm.enter_new_function();
  mm.update_stack_addresses(0x2000, 0x3000);
  mm.update_stack_addresses(0x1000, 0x4000);

  auto addr = mm.pop_last_stack_address();
  ASSERT_EQ(addr.first, 0x1000);
  ASSERT_EQ(addr.second, 0x4000);
}

TEST_F(MemoryManagerTest, testIsStackAccess) {
  auto mm = __dp::MemoryManager{};

  mm.enter_new_function();

  ASSERT_FALSE(mm.is_stack_access(0x1000));
  ASSERT_FALSE(mm.is_stack_access(0x1500));
  ASSERT_FALSE(mm.is_stack_access(0x2000));
  ASSERT_FALSE(mm.is_stack_access(0x2500));
  ASSERT_FALSE(mm.is_stack_access(0x3000));
  ASSERT_FALSE(mm.is_stack_access(0x3500));
  ASSERT_FALSE(mm.is_stack_access(0x4000));
  ASSERT_FALSE(mm.is_stack_access(0x4500));
  ASSERT_FALSE(mm.is_stack_access(0x5000));
  ASSERT_FALSE(mm.is_stack_access(0x5500));
  ASSERT_FALSE(mm.is_stack_access(0x6000));
  ASSERT_FALSE(mm.is_stack_access(0x6500));

  mm.update_stack_addresses(0x1000, 0x2000);
  mm.enter_new_function();

  ASSERT_FALSE(mm.is_stack_access(0x1000));
  ASSERT_FALSE(mm.is_stack_access(0x1500));
  ASSERT_FALSE(mm.is_stack_access(0x2000));
  ASSERT_FALSE(mm.is_stack_access(0x2500));
  ASSERT_FALSE(mm.is_stack_access(0x3000));
  ASSERT_FALSE(mm.is_stack_access(0x3500));
  ASSERT_FALSE(mm.is_stack_access(0x4000));
  ASSERT_FALSE(mm.is_stack_access(0x4500));
  ASSERT_FALSE(mm.is_stack_access(0x5000));
  ASSERT_FALSE(mm.is_stack_access(0x5500));
  ASSERT_FALSE(mm.is_stack_access(0x6000));
  ASSERT_FALSE(mm.is_stack_access(0x6500));

  mm.update_stack_addresses(0x3000, 0x4000);
  mm.enter_new_function();

  ASSERT_FALSE(mm.is_stack_access(0x1000));
  ASSERT_FALSE(mm.is_stack_access(0x1500));
  ASSERT_FALSE(mm.is_stack_access(0x2000));
  ASSERT_FALSE(mm.is_stack_access(0x2500));
  ASSERT_FALSE(mm.is_stack_access(0x3000));
  ASSERT_FALSE(mm.is_stack_access(0x3500));
  ASSERT_FALSE(mm.is_stack_access(0x4000));
  ASSERT_FALSE(mm.is_stack_access(0x4500));
  ASSERT_FALSE(mm.is_stack_access(0x5000));
  ASSERT_FALSE(mm.is_stack_access(0x5500));
  ASSERT_FALSE(mm.is_stack_access(0x6000));
  ASSERT_FALSE(mm.is_stack_access(0x6500));

  mm.update_stack_addresses(0x5000, 0x6000);

  ASSERT_FALSE(mm.is_stack_access(0x1000));
  ASSERT_FALSE(mm.is_stack_access(0x1500));
  ASSERT_FALSE(mm.is_stack_access(0x2000));
  ASSERT_FALSE(mm.is_stack_access(0x2500));
  ASSERT_FALSE(mm.is_stack_access(0x3000));
  ASSERT_FALSE(mm.is_stack_access(0x3500));
  ASSERT_FALSE(mm.is_stack_access(0x4000));
  ASSERT_FALSE(mm.is_stack_access(0x4500));
  ASSERT_TRUE(mm.is_stack_access(0x5000));
  ASSERT_TRUE(mm.is_stack_access(0x5500));
  ASSERT_TRUE(mm.is_stack_access(0x6000));
  ASSERT_FALSE(mm.is_stack_access(0x6500));

  auto addr = mm.pop_last_stack_address();

  ASSERT_FALSE(mm.is_stack_access(0x1000));
  ASSERT_FALSE(mm.is_stack_access(0x1500));
  ASSERT_FALSE(mm.is_stack_access(0x2000));
  ASSERT_FALSE(mm.is_stack_access(0x2500));
  ASSERT_TRUE(mm.is_stack_access(0x3000));
  ASSERT_TRUE(mm.is_stack_access(0x3500));
  ASSERT_TRUE(mm.is_stack_access(0x4000));
  ASSERT_FALSE(mm.is_stack_access(0x4500));
  ASSERT_FALSE(mm.is_stack_access(0x5000));
  ASSERT_FALSE(mm.is_stack_access(0x5500));
  ASSERT_FALSE(mm.is_stack_access(0x6000));
  ASSERT_FALSE(mm.is_stack_access(0x6500));

  addr = mm.pop_last_stack_address();

  ASSERT_TRUE(mm.is_stack_access(0x1000));
  ASSERT_TRUE(mm.is_stack_access(0x1500));
  ASSERT_TRUE(mm.is_stack_access(0x2000));
  ASSERT_FALSE(mm.is_stack_access(0x2500));
  ASSERT_FALSE(mm.is_stack_access(0x3000));
  ASSERT_FALSE(mm.is_stack_access(0x3500));
  ASSERT_FALSE(mm.is_stack_access(0x4000));
  ASSERT_FALSE(mm.is_stack_access(0x4500));
  ASSERT_FALSE(mm.is_stack_access(0x5000));
  ASSERT_FALSE(mm.is_stack_access(0x5500));
  ASSERT_FALSE(mm.is_stack_access(0x6000));
  ASSERT_FALSE(mm.is_stack_access(0x6500));

  addr = mm.pop_last_stack_address();

  ASSERT_FALSE(mm.is_stack_access(0x1000));
  ASSERT_FALSE(mm.is_stack_access(0x1500));
  ASSERT_FALSE(mm.is_stack_access(0x2000));
  ASSERT_FALSE(mm.is_stack_access(0x2500));
  ASSERT_FALSE(mm.is_stack_access(0x3000));
  ASSERT_FALSE(mm.is_stack_access(0x3500));
  ASSERT_FALSE(mm.is_stack_access(0x4000));
  ASSERT_FALSE(mm.is_stack_access(0x4500));
  ASSERT_FALSE(mm.is_stack_access(0x5000));
  ASSERT_FALSE(mm.is_stack_access(0x5500));
  ASSERT_FALSE(mm.is_stack_access(0x6000));
  ASSERT_FALSE(mm.is_stack_access(0x6500));
}

TEST_F(MemoryManagerTest, testScoping) {
  auto manager = __dp::MemoryManager{};

  manager.enterScope("First scope", 0);
  const auto first_scope = manager.getCurrentScope();
  manager.leaveScope("Already gone", 0);

  ASSERT_EQ(first_scope.get_id(), 1);
  ASSERT_TRUE(first_scope.get_first_read().empty());
  ASSERT_TRUE(first_scope.get_first_write().empty());

  manager.enterScope("Hello", 1);
  manager.enterScope(" ", 20);
  manager.enterScope("world", 10);
  manager.enterScope("!\n", 1);

  for (auto i = 0; i < 4; i++) {
    const auto scope = manager.getCurrentScope();
    ASSERT_EQ(scope.get_id(), 5 - i);
    ASSERT_TRUE(scope.get_first_read().empty());
    ASSERT_TRUE(scope.get_first_write().empty());

    const auto scope_again = manager.getCurrentScope();
    ASSERT_EQ(scope_again.get_id(), 5 - i);
    ASSERT_TRUE(scope_again.get_first_read().empty());
    ASSERT_TRUE(scope_again.get_first_write().empty());

    manager.leaveScope("leave!", 55);
  }

  manager.enterScope("New version", 2);
  manager.enterScope("...\n", 5);

  const auto scope = manager.getCurrentScope();
  ASSERT_EQ(scope.get_id(), 7);
  ASSERT_TRUE(scope.get_first_read().empty());
  ASSERT_TRUE(scope.get_first_write().empty());

  manager.leaveScope("Leave.", 4);

  const auto last_scope = manager.getCurrentScope();
  ASSERT_EQ(last_scope.get_id(), 6);
  ASSERT_TRUE(last_scope.get_first_read().empty());
  ASSERT_TRUE(last_scope.get_first_write().empty());

  manager.leaveScope("Leave the last time", 0);
}

TEST_F(MemoryManagerTest, testRegisterRead) {
  auto manager = __dp::MemoryManager{};

  manager.enterScope("First", 1);

  manager.enterScope("Second", 2);
  manager.registerStackRead(24, 2, "");
  manager.registerStackRead(32, 1, "");

  manager.enterScope("Third", 3);
  manager.registerStackRead(1024, 0, "");

  manager.enterScope("Fourth", 4);

  const auto scope4 = manager.getCurrentScope();

  ASSERT_TRUE(scope4.get_first_read().empty());
  ASSERT_TRUE(scope4.get_first_write().empty());

  manager.leaveScope("Fourth", 4);

  manager.registerStackRead(52, 0, "");

  const auto scope3 = manager.getCurrentScope();
  const auto reads3 = scope3.get_first_read();

  ASSERT_TRUE(scope3.get_first_write().empty());
  ASSERT_EQ(reads3.size(), 2);
  ASSERT_NE(reads3.find(52), reads3.end());
  ASSERT_NE(reads3.find(1024), reads3.end());

  manager.leaveScope("Third", 3);

  manager.registerStackRead(24, 2, "");

  const auto scope2 = manager.getCurrentScope();
  const auto reads2 = scope2.get_first_read();

  ASSERT_TRUE(scope2.get_first_write().empty());
  ASSERT_EQ(reads2.size(), 2);
  ASSERT_NE(reads2.find(24), reads3.end());
  ASSERT_NE(reads2.find(32), reads3.end());

  manager.leaveScope("Second", 2);

  const auto scope1 = manager.getCurrentScope();

  ASSERT_TRUE(scope1.get_first_read().empty());
  ASSERT_TRUE(scope1.get_first_write().empty());

  manager.leaveScope("First", 1);
}

TEST_F(MemoryManagerTest, testRegisterWrite) {
  auto manager = __dp::MemoryManager{};

  manager.enterScope("First", 1);

  manager.enterScope("Second", 2);
  manager.registerStackWrite(24, 2, "");
  manager.registerStackWrite(32, 1, "");

  manager.enterScope("Third", 3);
  manager.registerStackWrite(1024, 0, "");

  manager.enterScope("Fourth", 4);

  const auto scope4 = manager.getCurrentScope();

  ASSERT_TRUE(scope4.get_first_read().empty());
  ASSERT_TRUE(scope4.get_first_write().empty());

  manager.leaveScope("Fourth", 4);

  manager.registerStackWrite(52, 0, "");

  const auto scope3 = manager.getCurrentScope();
  const auto writes3 = scope3.get_first_write();

  ASSERT_TRUE(scope3.get_first_read().empty());
  ASSERT_EQ(writes3.size(), 2);
  ASSERT_NE(writes3.find(52), writes3.end());
  ASSERT_NE(writes3.find(1024), writes3.end());

  manager.leaveScope("Third", 3);

  manager.registerStackWrite(24, 2, "");

  const auto scope2 = manager.getCurrentScope();
  const auto writes2 = scope2.get_first_write();

  ASSERT_TRUE(scope2.get_first_read().empty());
  ASSERT_EQ(writes2.size(), 2);
  ASSERT_NE(writes2.find(24), writes2.end());
  ASSERT_NE(writes2.find(32), writes2.end());

  manager.leaveScope("Second", 2);

  const auto scope1 = manager.getCurrentScope();

  ASSERT_TRUE(scope1.get_first_read().empty());
  ASSERT_TRUE(scope1.get_first_write().empty());

  manager.leaveScope("First", 1);
}

TEST_F(MemoryManagerTest, testRegister) {
  auto manager = __dp::MemoryManager{};

  manager.enterScope("First", 1);

  manager.registerStackRead(32, 0, "");
  manager.registerStackRead(24, 1, "");

  manager.enterScope("Second", 2);

  manager.registerStackRead(32, 3, "");
  manager.registerStackWrite(24, 4, "");

  manager.enterScope("Third", 3);

  manager.registerStackRead(24, 5, "");
  manager.registerStackWrite(24, 6, "");

  const auto scope3 = manager.getCurrentScope();
  const auto reads3 = scope3.get_first_read();
  const auto writes3 = scope3.get_first_write();

  manager.leaveScope("Third", 3);

  const auto scope2 = manager.getCurrentScope();
  const auto reads2 = scope2.get_first_read();
  const auto writes2 = scope2.get_first_write();

  manager.leaveScope("Second", 2);

  const auto scope1 = manager.getCurrentScope();
  const auto reads1 = scope1.get_first_read();
  const auto writes1 = scope1.get_first_write();

  manager.leaveScope("First", 1);

  ASSERT_TRUE(writes1.empty());
  ASSERT_EQ(reads1.size(), 2);
  ASSERT_NE(reads1.find(24), reads1.end());
  ASSERT_NE(reads1.find(32), reads1.end());

  ASSERT_EQ(reads2.size(), 1);
  ASSERT_EQ(writes2.size(), 1);
  ASSERT_NE(reads2.find(32), reads2.end());
  ASSERT_NE(writes2.find(24), writes2.end());

  ASSERT_TRUE(writes3.empty());
  ASSERT_EQ(reads3.size(), 1);
  ASSERT_NE(reads3.find(24), reads3.end());
}

TEST_F(MemoryManagerTest, testFirstWritten) {
  auto manager = __dp::MemoryManager{};

  manager.enterScope("First", 1);
  manager.registerStackRead(24, 0, "");
  manager.registerStackWrite(24, 1, "");
  manager.registerStackWrite(12, 2, "");
  manager.registerStackRead(12, 3, "");

  manager.enterScope("Second", 2);
  manager.registerStackWrite(24, 2, "");
  manager.registerStackRead(24, 3, "");
  manager.registerStackRead(12, 0, "");
  manager.registerStackWrite(12, 1, "");

  manager.enterScope("Third", 3);
  manager.registerStackRead(32, 4, "");
  manager.registerStackWrite(36, 5, "");
  manager.registerStackRead(40, 6, "");

  ASSERT_TRUE(manager.isFirstWrittenInScope(36, true));
  ASSERT_TRUE(manager.isFirstWrittenInScope(1012, true));
  ASSERT_TRUE(manager.isFirstWrittenInScope(1024, true));

  ASSERT_FALSE(manager.isFirstWrittenInScope(12, true));
  ASSERT_FALSE(manager.isFirstWrittenInScope(24, true));
  ASSERT_FALSE(manager.isFirstWrittenInScope(32, true));
  ASSERT_FALSE(manager.isFirstWrittenInScope(32, false));
  ASSERT_FALSE(manager.isFirstWrittenInScope(40, true));
  ASSERT_FALSE(manager.isFirstWrittenInScope(40, false));
  ASSERT_FALSE(manager.isFirstWrittenInScope(1012, false));
  ASSERT_FALSE(manager.isFirstWrittenInScope(1024, false));
}

TEST_F(MemoryManagerTest, testPositiveChange) {
  auto scope = __dp::MemoryManager{};

  scope.enterScope("First", 1);
  scope.registerStackRead(24, 0, "");
  scope.registerStackRead(64, 1, "");

  scope.enterScope("Second", 2);
  scope.registerStackWrite(32, 2, "");

  scope.enterScope("Third", 3);
  scope.registerStackWrite(64, 3, "");

  ASSERT_TRUE(scope.positiveScopeChangeOccuredSinceLastAccess(12));
  ASSERT_TRUE(scope.positiveScopeChangeOccuredSinceLastAccess(24));
  ASSERT_TRUE(scope.positiveScopeChangeOccuredSinceLastAccess(32));
  ASSERT_FALSE(scope.positiveScopeChangeOccuredSinceLastAccess(64));

  scope.leaveScope("Third", 3);

  ASSERT_TRUE(scope.positiveScopeChangeOccuredSinceLastAccess(12));
  ASSERT_TRUE(scope.positiveScopeChangeOccuredSinceLastAccess(24));
  ASSERT_FALSE(scope.positiveScopeChangeOccuredSinceLastAccess(32));
  ASSERT_FALSE(scope.positiveScopeChangeOccuredSinceLastAccess(64));

  scope.leaveScope("Second", 2);

  ASSERT_TRUE(scope.positiveScopeChangeOccuredSinceLastAccess(12));
  ASSERT_FALSE(scope.positiveScopeChangeOccuredSinceLastAccess(24));
  ASSERT_FALSE(scope.positiveScopeChangeOccuredSinceLastAccess(32));
  ASSERT_FALSE(scope.positiveScopeChangeOccuredSinceLastAccess(64));

  scope.leaveScope("First", 1);

  // TODO(Lukas): Currently, there is no active scope.
  //      Think about your error handling.

  // ASSERT_TRUE(scope.positiveScopeChangeOccuredSinceLastAccess(12));
  // ASSERT_FALSE(scope.positiveScopeChangeOccuredSinceLastAccess(24));
  // ASSERT_FALSE(scope.positiveScopeChangeOccuredSinceLastAccess(32));
  // ASSERT_FALSE(scope.positiveScopeChangeOccuredSinceLastAccess(64));

  scope.enterScope("Forth", 4);

  scope.registerStackRead(24, 4, "");

  ASSERT_TRUE(scope.positiveScopeChangeOccuredSinceLastAccess(12));
  ASSERT_FALSE(scope.positiveScopeChangeOccuredSinceLastAccess(24));
  ASSERT_TRUE(scope.positiveScopeChangeOccuredSinceLastAccess(32));
  ASSERT_TRUE(scope.positiveScopeChangeOccuredSinceLastAccess(64));

  scope.enterScope("Fifth", 5);

  ASSERT_TRUE(scope.positiveScopeChangeOccuredSinceLastAccess(12));
  ASSERT_TRUE(scope.positiveScopeChangeOccuredSinceLastAccess(24));
  ASSERT_TRUE(scope.positiveScopeChangeOccuredSinceLastAccess(32));
  ASSERT_TRUE(scope.positiveScopeChangeOccuredSinceLastAccess(64));
}

TEST_F(MemoryManagerTest, testAllocateDummyRegion) {
  auto manager = __dp::MemoryManager{};

  ASSERT_EQ(manager.get_number_allocations(), 0);

  manager.allocate_dummy_region();

  ASSERT_EQ(manager.get_number_allocations(), 1);

  manager.allocate_dummy_region();

  ASSERT_EQ(manager.get_number_allocations(), 2);

  const auto &allocations = manager.get_allocated_memory_regions();
  ASSERT_EQ(allocations.size(), 2);

  for (const auto &allocation : allocations) {
    ASSERT_EQ(std::get<0>(allocation), 0);
    ASSERT_EQ(std::get<1>(allocation), "%%dummy%%");
    ASSERT_EQ(std::get<2>(allocation), 0);
    ASSERT_EQ(std::get<3>(allocation), 0);
    ASSERT_EQ(std::get<4>(allocation), 0);
    ASSERT_EQ(std::get<5>(allocation), 0);
  }
}

TEST_F(MemoryManagerTest, testAllocateRegion1) {
  auto manager = __dp::MemoryManager{};

  const auto lid = 43;
  const auto start_address = 0x2000'0000'0000'0000LL;
  const auto end_address = 0x2000'0000'0000'1000LL;
  const auto num_bytes = 0x1000LL;
  const auto num_elements = 0x100LL;

  manager.allocate_memory(lid, start_address, end_address, num_bytes, num_elements);

  for (auto i = start_address; i <= end_address; i++) {
    ASSERT_EQ(manager.get_memory_region_id(i, ""), "1");
  }

  ASSERT_EQ(manager.get_memory_region_id(0x0000'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x1000'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x5687'1400'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x3FF0'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x1242'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x4FFF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x2225'1684'6ac4'd4b6LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x2FFF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x3000'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x5300'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x530F'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x53FF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));

  ASSERT_EQ(manager.get_smallest_allocated_addr(), start_address);
  ASSERT_EQ(manager.get_largest_allocated_addr(), end_address);

  const auto &allocations = manager.get_allocated_memory_regions();
  ASSERT_EQ(allocations.size(), 1);
  ASSERT_EQ(manager.get_number_allocations(), 1);

  const auto &allocation = allocations[0];
  ASSERT_EQ(std::get<0>(allocation), lid);
  ASSERT_EQ(std::get<1>(allocation), "1");
  ASSERT_EQ(std::get<2>(allocation), start_address);
  ASSERT_EQ(std::get<3>(allocation), end_address);
  ASSERT_EQ(std::get<4>(allocation), num_bytes);
  ASSERT_EQ(std::get<5>(allocation), num_elements);

  ASSERT_EQ(manager.get_next_free_memory_region_id(), 2);
}

TEST_F(MemoryManagerTest, testAllocateRegion2) {
  auto manager = __dp::MemoryManager{};

  const auto lid_1 = 43;
  const auto start_address_1 = 0x2000'0000'0000'0000LL;
  const auto end_address_1 = 0x2000'0000'0000'1000LL;
  const auto num_bytes_1 = 0x1000LL;
  const auto num_elements_1 = 0x100LL;

  manager.allocate_memory(lid_1, start_address_1, end_address_1, num_bytes_1, num_elements_1);

  const auto lid_2 = 44;
  const auto start_address_2 = 0x3000'0000'0000'0000LL;
  const auto end_address_2 = 0x3000'0000'0000'5000LL;
  const auto num_bytes_2 = 0x5000LL;
  const auto num_elements_2 = 0x400LL;

  manager.allocate_memory(lid_2, start_address_2, end_address_2, num_bytes_2, num_elements_2);

  for (auto i = start_address_1; i <= end_address_1; i++) {
    ASSERT_EQ(manager.get_memory_region_id(i, ""), "1");
  }

  for (auto i = start_address_2; i <= end_address_2; i++) {
    ASSERT_EQ(manager.get_memory_region_id(i, ""), "2");
  }

  ASSERT_EQ(manager.get_memory_region_id(0x0000'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x1000'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x5687'1400'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x3FF0'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x1242'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x4FFF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x2225'1684'6ac4'd4b6LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x2FFF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x5300'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x530F'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x53FF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));

  ASSERT_EQ(manager.get_smallest_allocated_addr(), start_address_1);
  ASSERT_EQ(manager.get_largest_allocated_addr(), end_address_2);

  const auto &allocations = manager.get_allocated_memory_regions();
  ASSERT_EQ(allocations.size(), 2);
  ASSERT_EQ(manager.get_number_allocations(), 2);

  const auto &allocation_1 = allocations[0];
  ASSERT_EQ(std::get<0>(allocation_1), lid_1);
  ASSERT_EQ(std::get<1>(allocation_1), "1");
  ASSERT_EQ(std::get<2>(allocation_1), start_address_1);
  ASSERT_EQ(std::get<3>(allocation_1), end_address_1);
  ASSERT_EQ(std::get<4>(allocation_1), num_bytes_1);
  ASSERT_EQ(std::get<5>(allocation_1), num_elements_1);

  const auto &allocation_2 = allocations[1];
  ASSERT_EQ(std::get<0>(allocation_2), lid_2);
  ASSERT_EQ(std::get<1>(allocation_2), "2");
  ASSERT_EQ(std::get<2>(allocation_2), start_address_2);
  ASSERT_EQ(std::get<3>(allocation_2), end_address_2);
  ASSERT_EQ(std::get<4>(allocation_2), num_bytes_2);
  ASSERT_EQ(std::get<5>(allocation_2), num_elements_2);

  ASSERT_EQ(manager.get_next_free_memory_region_id(), 3);
}

TEST_F(MemoryManagerTest, testAllocateStackRegion1) {
  auto manager = __dp::MemoryManager{};

  manager.enter_new_function();

  const auto lid = 43;
  const auto start_address = 0x2000'0000'0000'0000LL;
  const auto end_address = 0x2000'0000'0000'1000LL;
  const auto num_bytes = 0x1000LL;
  const auto num_elements = 0x100LL;

  manager.allocate_stack_memory(lid, start_address, end_address, num_bytes, num_elements);

  for (auto i = start_address; i <= end_address; i++) {
    ASSERT_EQ(manager.get_memory_region_id(i, ""), "1");
  }

  ASSERT_EQ(manager.get_memory_region_id(0x0000'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x1000'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x5687'1400'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x3FF0'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x1242'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x4FFF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x2225'1684'6ac4'd4b6LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x2FFF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x3000'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x5300'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x530F'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x53FF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));

  ASSERT_EQ(manager.get_smallest_allocated_addr(), start_address);
  ASSERT_EQ(manager.get_largest_allocated_addr(), end_address);

  const auto &allocations = manager.get_allocated_memory_regions();
  ASSERT_EQ(allocations.size(), 1);
  ASSERT_EQ(manager.get_number_allocations(), 1);

  const auto &allocation = allocations[0];
  ASSERT_EQ(std::get<0>(allocation), lid);
  ASSERT_EQ(std::get<1>(allocation), "1");
  ASSERT_EQ(std::get<2>(allocation), start_address);
  ASSERT_EQ(std::get<3>(allocation), end_address);
  ASSERT_EQ(std::get<4>(allocation), num_bytes);
  ASSERT_EQ(std::get<5>(allocation), num_elements);

  ASSERT_EQ(manager.get_next_free_memory_region_id(), 2);

  const auto stack_addresses = manager.pop_last_stack_address();
  ASSERT_EQ(stack_addresses.first, start_address);
  ASSERT_EQ(stack_addresses.second, end_address);
}

TEST_F(MemoryManagerTest, testAllocateStackRegion2) {
  auto manager = __dp::MemoryManager{};

  manager.enter_new_function();

  const auto lid_1 = 43;
  const auto start_address_1 = 0x2000'0000'0000'0000LL;
  const auto end_address_1 = 0x2000'0000'0000'1000LL;
  const auto num_bytes_1 = 0x1000LL;
  const auto num_elements_1 = 0x100LL;

  manager.allocate_stack_memory(lid_1, start_address_1, end_address_1, num_bytes_1, num_elements_1);

  const auto lid_2 = 44;
  const auto start_address_2 = 0x3000'0000'0000'0000LL;
  const auto end_address_2 = 0x3000'0000'0000'5000LL;
  const auto num_bytes_2 = 0x5000LL;
  const auto num_elements_2 = 0x400LL;

  manager.allocate_stack_memory(lid_2, start_address_2, end_address_2, num_bytes_2, num_elements_2);

  for (auto i = start_address_1; i <= end_address_1; i++) {
    ASSERT_EQ(manager.get_memory_region_id(i, ""), "1");
  }

  for (auto i = start_address_2; i <= end_address_2; i++) {
    ASSERT_EQ(manager.get_memory_region_id(i, ""), "2");
  }

  ASSERT_EQ(manager.get_memory_region_id(0x0000'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x1000'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x5687'1400'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x3FF0'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x1242'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x4FFF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x2225'1684'6ac4'd4b6LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x2FFF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x5300'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x530F'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x53FF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));

  ASSERT_EQ(manager.get_smallest_allocated_addr(), start_address_1);
  ASSERT_EQ(manager.get_largest_allocated_addr(), end_address_2);

  const auto &allocations = manager.get_allocated_memory_regions();
  ASSERT_EQ(allocations.size(), 2);
  ASSERT_EQ(manager.get_number_allocations(), 2);

  const auto &allocation_1 = allocations[0];
  ASSERT_EQ(std::get<0>(allocation_1), lid_1);
  ASSERT_EQ(std::get<1>(allocation_1), "1");
  ASSERT_EQ(std::get<2>(allocation_1), start_address_1);
  ASSERT_EQ(std::get<3>(allocation_1), end_address_1);
  ASSERT_EQ(std::get<4>(allocation_1), num_bytes_1);
  ASSERT_EQ(std::get<5>(allocation_1), num_elements_1);

  const auto &allocation_2 = allocations[1];
  ASSERT_EQ(std::get<0>(allocation_2), lid_2);
  ASSERT_EQ(std::get<1>(allocation_2), "2");
  ASSERT_EQ(std::get<2>(allocation_2), start_address_2);
  ASSERT_EQ(std::get<3>(allocation_2), end_address_2);
  ASSERT_EQ(std::get<4>(allocation_2), num_bytes_2);
  ASSERT_EQ(std::get<5>(allocation_2), num_elements_2);

  ASSERT_EQ(manager.get_next_free_memory_region_id(), 3);

  const auto stack_addresses = manager.pop_last_stack_address();
  ASSERT_EQ(stack_addresses.first, start_address_1);
  ASSERT_EQ(stack_addresses.second, end_address_2);
}

TEST_F(MemoryManagerTest, testAllocateStackRegion3) {
  auto manager = __dp::MemoryManager{};

  manager.enter_new_function();

  const auto lid_1 = 43;
  const auto start_address_1 = 0x2000'0000'0000'0000LL;
  const auto end_address_1 = 0x2000'0000'0000'1000LL;
  const auto num_bytes_1 = 0x1000LL;
  const auto num_elements_1 = 0x100LL;

  manager.allocate_stack_memory(lid_1, start_address_1, end_address_1, num_bytes_1, num_elements_1);

  manager.enter_new_function();

  const auto lid_2 = 44;
  const auto start_address_2 = 0x3000'0000'0000'0000LL;
  const auto end_address_2 = 0x3000'0000'0000'5000LL;
  const auto num_bytes_2 = 0x5000LL;
  const auto num_elements_2 = 0x400LL;

  manager.allocate_stack_memory(lid_2, start_address_2, end_address_2, num_bytes_2, num_elements_2);

  for (auto i = start_address_1; i <= end_address_1; i++) {
    ASSERT_EQ(manager.get_memory_region_id(i, ""), "1");
  }

  for (auto i = start_address_2; i <= end_address_2; i++) {
    ASSERT_EQ(manager.get_memory_region_id(i, ""), "2");
  }

  ASSERT_EQ(manager.get_memory_region_id(0x0000'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x1000'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x5687'1400'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x3FF0'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x1242'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x4FFF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x2225'1684'6ac4'd4b6LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x2FFF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x5300'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x530F'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x53FF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));

  ASSERT_EQ(manager.get_smallest_allocated_addr(), start_address_1);
  ASSERT_EQ(manager.get_largest_allocated_addr(), end_address_2);

  const auto &allocations = manager.get_allocated_memory_regions();
  ASSERT_EQ(allocations.size(), 2);
  ASSERT_EQ(manager.get_number_allocations(), 2);

  const auto &allocation_1 = allocations[0];
  ASSERT_EQ(std::get<0>(allocation_1), lid_1);
  ASSERT_EQ(std::get<1>(allocation_1), "1");
  ASSERT_EQ(std::get<2>(allocation_1), start_address_1);
  ASSERT_EQ(std::get<3>(allocation_1), end_address_1);
  ASSERT_EQ(std::get<4>(allocation_1), num_bytes_1);
  ASSERT_EQ(std::get<5>(allocation_1), num_elements_1);

  const auto &allocation_2 = allocations[1];
  ASSERT_EQ(std::get<0>(allocation_2), lid_2);
  ASSERT_EQ(std::get<1>(allocation_2), "2");
  ASSERT_EQ(std::get<2>(allocation_2), start_address_2);
  ASSERT_EQ(std::get<3>(allocation_2), end_address_2);
  ASSERT_EQ(std::get<4>(allocation_2), num_bytes_2);
  ASSERT_EQ(std::get<5>(allocation_2), num_elements_2);

  ASSERT_EQ(manager.get_next_free_memory_region_id(), 3);

  const auto stack_addresses = manager.pop_last_stack_address();
  ASSERT_EQ(stack_addresses.first, start_address_2);
  ASSERT_EQ(stack_addresses.second, end_address_2);
}

TEST_F(MemoryManagerTest, testAllocate1) {
  auto manager = __dp::MemoryManager{};

  manager.enter_new_function();

  const auto lid_1 = 43;
  const auto start_address_1 = 0x2000'0000'0000'0000LL;
  const auto end_address_1 = 0x2000'0000'0000'1000LL;
  const auto num_bytes_1 = 0x1000LL;
  const auto num_elements_1 = 0x100LL;

  manager.allocate_stack_memory(lid_1, start_address_1, end_address_1, num_bytes_1, num_elements_1);

  const auto lid_2 = 44;
  const auto start_address_2 = 0x3000'0000'0000'0000LL;
  const auto end_address_2 = 0x3000'0000'0000'5000LL;
  const auto num_bytes_2 = 0x5000LL;
  const auto num_elements_2 = 0x400LL;

  manager.allocate_stack_memory(lid_2, start_address_2, end_address_2, num_bytes_2, num_elements_2);

  const auto lid_3 = 45;
  const auto start_address_3 = 0x1000'0000'0000'0000LL;
  const auto end_address_3 = 0x1000'0000'0000'2000LL;
  const auto num_bytes_3 = 0x2000LL;
  const auto num_elements_3 = 0x2000LL;

  manager.allocate_memory(lid_3, start_address_3, end_address_3, num_bytes_3, num_elements_3);

  for (auto i = start_address_1; i <= end_address_1; i++) {
    ASSERT_EQ(manager.get_memory_region_id(i, ""), "1");
  }

  for (auto i = start_address_2; i <= end_address_2; i++) {
    ASSERT_EQ(manager.get_memory_region_id(i, ""), "2");
  }

  for (auto i = start_address_3; i <= end_address_3; i++) {
    ASSERT_EQ(manager.get_memory_region_id(i, ""), "3");
  }

  ASSERT_EQ(manager.get_memory_region_id(0x0000'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x5687'1400'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x3FF0'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x1242'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x4FFF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x2225'1684'6ac4'd4b6LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x2FFF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x5300'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x530F'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x53FF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));

  ASSERT_EQ(manager.get_smallest_allocated_addr(), start_address_3);
  ASSERT_EQ(manager.get_largest_allocated_addr(), end_address_2);

  const auto &allocations = manager.get_allocated_memory_regions();
  ASSERT_EQ(allocations.size(), 3);
  ASSERT_EQ(manager.get_number_allocations(), 3);

  const auto &allocation_1 = allocations[0];
  ASSERT_EQ(std::get<0>(allocation_1), lid_1);
  ASSERT_EQ(std::get<1>(allocation_1), "1");
  ASSERT_EQ(std::get<2>(allocation_1), start_address_1);
  ASSERT_EQ(std::get<3>(allocation_1), end_address_1);
  ASSERT_EQ(std::get<4>(allocation_1), num_bytes_1);
  ASSERT_EQ(std::get<5>(allocation_1), num_elements_1);

  const auto &allocation_2 = allocations[1];
  ASSERT_EQ(std::get<0>(allocation_2), lid_2);
  ASSERT_EQ(std::get<1>(allocation_2), "2");
  ASSERT_EQ(std::get<2>(allocation_2), start_address_2);
  ASSERT_EQ(std::get<3>(allocation_2), end_address_2);
  ASSERT_EQ(std::get<4>(allocation_2), num_bytes_2);
  ASSERT_EQ(std::get<5>(allocation_2), num_elements_2);

  const auto &allocation_3 = allocations[2];
  ASSERT_EQ(std::get<0>(allocation_3), lid_3);
  ASSERT_EQ(std::get<1>(allocation_3), "3");
  ASSERT_EQ(std::get<2>(allocation_3), start_address_3);
  ASSERT_EQ(std::get<3>(allocation_3), end_address_3);
  ASSERT_EQ(std::get<4>(allocation_3), num_bytes_3);
  ASSERT_EQ(std::get<5>(allocation_3), num_elements_3);

  ASSERT_EQ(manager.get_next_free_memory_region_id(), 4);

  const auto stack_addresses = manager.pop_last_stack_address();
  ASSERT_EQ(stack_addresses.first, start_address_1);
  ASSERT_EQ(stack_addresses.second, end_address_2);
}

TEST_F(MemoryManagerTest, testAllocate2) {
  auto manager = __dp::MemoryManager{};

  manager.enter_new_function();

  const auto lid_1 = 43;
  const auto start_address_1 = 0x2000'0000'0000'0000LL;
  const auto end_address_1 = 0x2000'0000'0000'1000LL;
  const auto num_bytes_1 = 0x1000LL;
  const auto num_elements_1 = 0x100LL;

  manager.allocate_stack_memory(lid_1, start_address_1, end_address_1, num_bytes_1, num_elements_1);

  const auto lid_2 = 44;
  const auto start_address_2 = 0x3000'0000'0000'0000LL;
  const auto end_address_2 = 0x3000'0000'0000'5000LL;
  const auto num_bytes_2 = 0x5000LL;
  const auto num_elements_2 = 0x400LL;

  manager.allocate_stack_memory(lid_2, start_address_2, end_address_2, num_bytes_2, num_elements_2);

  const auto lid_3 = 45;
  const auto start_address_3 = 0x1000'0000'0000'0000LL;
  const auto end_address_3 = 0x1000'0000'0000'2000LL;
  const auto num_bytes_3 = 0x2000LL;
  const auto num_elements_3 = 0x2000LL;

  manager.allocate_memory(lid_3, start_address_3, end_address_3, num_bytes_3, num_elements_3);

  const auto lid_4 = 46;
  const auto start_address_4 = 0x5000'0000'0000'0000LL;
  const auto end_address_4 = 0x5000'0000'0000'0200LL;
  const auto num_bytes_4 = 0x200LL;
  const auto num_elements_4 = 0x2LL;

  manager.allocate_memory(lid_4, start_address_4, end_address_4, num_bytes_4, num_elements_4);

  for (auto i = start_address_1; i <= end_address_1; i++) {
    ASSERT_EQ(manager.get_memory_region_id(i, ""), "1");
  }

  for (auto i = start_address_2; i <= end_address_2; i++) {
    ASSERT_EQ(manager.get_memory_region_id(i, ""), "2");
  }

  for (auto i = start_address_3; i <= end_address_3; i++) {
    ASSERT_EQ(manager.get_memory_region_id(i, ""), "3");
  }

  for (auto i = start_address_4; i <= end_address_4; i++) {
    ASSERT_EQ(manager.get_memory_region_id(i, ""), "4");
  }

  ASSERT_EQ(manager.get_memory_region_id(0x0000'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x5687'1400'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x3FF0'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x1242'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x4FFF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x2225'1684'6ac4'd4b6LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x2FFF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x5300'0000'0000'0000LL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x530F'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));
  ASSERT_EQ(manager.get_memory_region_id(0x53FF'FFFF'FFFF'FFFFLL, "fallback"), std::string("fallback"));

  ASSERT_EQ(manager.get_smallest_allocated_addr(), start_address_3);
  ASSERT_EQ(manager.get_largest_allocated_addr(), end_address_4);

  const auto &allocations = manager.get_allocated_memory_regions();
  ASSERT_EQ(allocations.size(), 4);
  ASSERT_EQ(manager.get_number_allocations(), 4);

  const auto &allocation_1 = allocations[0];
  ASSERT_EQ(std::get<0>(allocation_1), lid_1);
  ASSERT_EQ(std::get<1>(allocation_1), "1");
  ASSERT_EQ(std::get<2>(allocation_1), start_address_1);
  ASSERT_EQ(std::get<3>(allocation_1), end_address_1);
  ASSERT_EQ(std::get<4>(allocation_1), num_bytes_1);
  ASSERT_EQ(std::get<5>(allocation_1), num_elements_1);

  const auto &allocation_2 = allocations[1];
  ASSERT_EQ(std::get<0>(allocation_2), lid_2);
  ASSERT_EQ(std::get<1>(allocation_2), "2");
  ASSERT_EQ(std::get<2>(allocation_2), start_address_2);
  ASSERT_EQ(std::get<3>(allocation_2), end_address_2);
  ASSERT_EQ(std::get<4>(allocation_2), num_bytes_2);
  ASSERT_EQ(std::get<5>(allocation_2), num_elements_2);

  const auto &allocation_3 = allocations[2];
  ASSERT_EQ(std::get<0>(allocation_3), lid_3);
  ASSERT_EQ(std::get<1>(allocation_3), "3");
  ASSERT_EQ(std::get<2>(allocation_3), start_address_3);
  ASSERT_EQ(std::get<3>(allocation_3), end_address_3);
  ASSERT_EQ(std::get<4>(allocation_3), num_bytes_3);
  ASSERT_EQ(std::get<5>(allocation_3), num_elements_3);

  const auto &allocation_4 = allocations[3];
  ASSERT_EQ(std::get<0>(allocation_4), lid_4);
  ASSERT_EQ(std::get<1>(allocation_4), "4");
  ASSERT_EQ(std::get<2>(allocation_4), start_address_4);
  ASSERT_EQ(std::get<3>(allocation_4), end_address_4);
  ASSERT_EQ(std::get<4>(allocation_4), num_bytes_4);
  ASSERT_EQ(std::get<5>(allocation_4), num_elements_4);

  ASSERT_EQ(manager.get_next_free_memory_region_id(), 5);

  const auto stack_addresses = manager.pop_last_stack_address();
  ASSERT_EQ(stack_addresses.first, start_address_1);
  ASSERT_EQ(stack_addresses.second, end_address_2);
}
