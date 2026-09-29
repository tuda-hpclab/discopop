#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/memory/Scope.hpp"

// Tests for old version (i.e., capturing functionality)

class ScopeTest : public ::testing::Test {};

class ScopeManagerTest : public ::testing::Test {};

TEST_F(ScopeTest, testConstructor) {
  const auto scope_1 = __dp::Scope(4);
  ASSERT_EQ(scope_1.get_id(), 4);

  ASSERT_TRUE(scope_1.get_first_read().empty());
  ASSERT_TRUE(scope_1.get_first_write().empty());

  const auto scope_2 = __dp::Scope(9);
  ASSERT_EQ(scope_2.get_id(), 9);

  ASSERT_TRUE(scope_2.get_first_read().empty());
  ASSERT_TRUE(scope_2.get_first_write().empty());
}

TEST_F(ScopeTest, testRegisterRead) {
  auto scope = __dp::Scope(3);
  const auto &reads = scope.get_first_read();
  const auto &writes = scope.get_first_write();

  scope.registerStackRead(24, 0, "");
  scope.registerStackRead(32, 1, "");

  ASSERT_TRUE(writes.empty());
  ASSERT_EQ(reads.size(), 2);

  ASSERT_NE(reads.find(24), reads.end());
  ASSERT_NE(reads.find(32), reads.end());

  scope.registerStackRead(72, 1, "");
  scope.registerStackRead(24, 6, "");
  scope.registerStackRead(32, 1, "");

  ASSERT_TRUE(writes.empty());
  ASSERT_EQ(reads.size(), 3);

  ASSERT_NE(reads.find(24), reads.end());
  ASSERT_NE(reads.find(32), reads.end());
  ASSERT_NE(reads.find(72), reads.end());
}

TEST_F(ScopeTest, testRegisterWrite) {
  auto scope = __dp::Scope(3);
  const auto &reads = scope.get_first_read();
  const auto &writes = scope.get_first_write();

  scope.registerStackWrite(1024, 0, "");
  scope.registerStackWrite(1032, 1, "");

  ASSERT_TRUE(reads.empty());
  ASSERT_EQ(writes.size(), 2);

  ASSERT_NE(writes.find(1024), writes.end());
  ASSERT_NE(writes.find(1032), writes.end());

  scope.registerStackWrite(1072, 1, "");
  scope.registerStackWrite(1024, 6, "");
  scope.registerStackWrite(1032, 1, "");

  ASSERT_TRUE(reads.empty());
  ASSERT_EQ(writes.size(), 3);

  ASSERT_NE(writes.find(1024), writes.end());
  ASSERT_NE(writes.find(1032), writes.end());
  ASSERT_NE(writes.find(1072), writes.end());
}

TEST_F(ScopeTest, testRegister) {
  auto scope = __dp::Scope(3);
  const auto &reads = scope.get_first_read();
  const auto &writes = scope.get_first_write();

  scope.registerStackRead(24, 0, "");
  scope.registerStackWrite(1024, 0, "");
  scope.registerStackWrite(1032, 1, "");

  ASSERT_EQ(reads.size(), 1);
  ASSERT_EQ(writes.size(), 2);

  ASSERT_NE(reads.find(24), reads.end());
  ASSERT_NE(writes.find(1024), writes.end());
  ASSERT_NE(writes.find(1032), writes.end());

  scope.registerStackRead(32, 1, "");
  scope.registerStackRead(1024, 5, "");
  scope.registerStackWrite(1876, 0, "");
  scope.registerStackWrite(24, 0, "");

  ASSERT_EQ(reads.size(), 2);
  ASSERT_EQ(writes.size(), 3);

  ASSERT_NE(reads.find(24), reads.end());
  ASSERT_NE(reads.find(32), reads.end());
  ASSERT_NE(writes.find(1024), writes.end());
  ASSERT_NE(writes.find(1024), writes.end());
  ASSERT_NE(writes.find(1876), writes.end());
}

TEST_F(ScopeTest, testCopy1) {
  const auto scope_1 = __dp::Scope(4);
  const auto scope_2 = __dp::Scope(scope_1);

  ASSERT_EQ(scope_1.get_id(), scope_2.get_id());
  ASSERT_TRUE(scope_1.get_first_read().empty());
  ASSERT_TRUE(scope_1.get_first_write().empty());
  ASSERT_TRUE(scope_2.get_first_read().empty());
  ASSERT_TRUE(scope_2.get_first_write().empty());
}

TEST_F(ScopeTest, testCopy2) {
  auto scope_1 = __dp::Scope(4);
  scope_1.registerStackRead(24, 0, "");
  scope_1.registerStackRead(32, 1, "");
  scope_1.registerStackWrite(1024, 0, "");
  scope_1.registerStackWrite(1032, 1, "");

  const auto scope_2 = __dp::Scope(scope_1);

  ASSERT_EQ(scope_1.get_id(), scope_2.get_id());
  ASSERT_EQ(scope_1.get_first_read(), scope_2.get_first_read());
  ASSERT_EQ(scope_1.get_first_write(), scope_2.get_first_write());
}

TEST_F(ScopeTest, testCopy3) {
  auto scope_1 = __dp::Scope(4);
  scope_1.registerStackRead(24, 0, "");
  scope_1.registerStackRead(32, 1, "");
  scope_1.registerStackWrite(1024, 0, "");
  scope_1.registerStackWrite(1032, 1, "");

  auto scope_2 = __dp::Scope(scope_1);
  auto scope_3 = __dp::Scope(scope_1);

  scope_2.registerStackRead(72, 1, "");
  scope_2.registerStackRead(24, 6, "");
  scope_2.registerStackRead(32, 1, "");

  scope_2.registerStackWrite(1072, 1, "");
  scope_2.registerStackWrite(1024, 6, "");
  scope_2.registerStackWrite(1032, 1, "");

  ASSERT_EQ(scope_1.get_id(), scope_3.get_id());
  ASSERT_EQ(scope_1.get_first_read(), scope_3.get_first_read());
  ASSERT_EQ(scope_1.get_first_write(), scope_3.get_first_write());
}

TEST_F(ScopeTest, testCopy4) {
  auto scope_1 = __dp::Scope(4);
  scope_1.registerStackRead(24, 0, "");
  scope_1.registerStackRead(32, 1, "");
  scope_1.registerStackWrite(1024, 0, "");
  scope_1.registerStackWrite(1032, 1, "");

  auto scope_2 = __dp::Scope(scope_1);
  auto scope_3 = __dp::Scope(scope_1);

  scope_2.registerStackRead(72, 1, "");
  scope_2.registerStackRead(24, 6, "");
  scope_2.registerStackRead(32, 1, "");

  scope_2.registerStackWrite(1072, 1, "");
  scope_2.registerStackWrite(1024, 6, "");
  scope_2.registerStackWrite(1032, 1, "");

  scope_2 = scope_3;

  ASSERT_EQ(scope_1.get_id(), scope_2.get_id());
  ASSERT_EQ(scope_1.get_first_read(), scope_2.get_first_read());
  ASSERT_EQ(scope_1.get_first_write(), scope_2.get_first_write());

  ASSERT_EQ(scope_1.get_id(), scope_3.get_id());
  ASSERT_EQ(scope_1.get_first_read(), scope_3.get_first_read());
  ASSERT_EQ(scope_1.get_first_write(), scope_3.get_first_write());
}

TEST_F(ScopeManagerTest, testScoping) {
  auto manager = __dp::ScopeManager{};

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

TEST_F(ScopeManagerTest, testRegisterRead) {
  auto manager = __dp::ScopeManager{};

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

TEST_F(ScopeManagerTest, testRegisterWrite) {
  auto manager = __dp::ScopeManager{};

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

TEST_F(ScopeManagerTest, testRegister) {
  auto manager = __dp::ScopeManager{};

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

TEST_F(ScopeManagerTest, testFirstWritten) {
  auto manager = __dp::ScopeManager{};

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

  ASSERT_TRUE(manager.isOwnedByScope(36, true));
  ASSERT_TRUE(manager.isOwnedByScope(1012, true));
  ASSERT_TRUE(manager.isOwnedByScope(1024, true));

  ASSERT_FALSE(manager.isOwnedByScope(12, true));
  ASSERT_FALSE(manager.isOwnedByScope(24, true));
  ASSERT_FALSE(manager.isOwnedByScope(32, true));
  ASSERT_FALSE(manager.isOwnedByScope(32, false));
  ASSERT_FALSE(manager.isOwnedByScope(40, true));
  ASSERT_FALSE(manager.isOwnedByScope(40, false));
  ASSERT_FALSE(manager.isOwnedByScope(1012, false));
  ASSERT_FALSE(manager.isOwnedByScope(1024, false));
}

TEST_F(ScopeManagerTest, testPositiveChange) {
  auto scope = __dp::ScopeManager{};

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

// Tests for new version (i.e., reproducing functionality)

class Scope2Test : public ::testing::Test {};

class ScopeManager2Test : public ::testing::Test {};

TEST_F(Scope2Test, testConstructor) {
  const auto scope_1 = __dp::Scope2(4);
  ASSERT_EQ(scope_1.get_id(), 4);

  ASSERT_TRUE(scope_1.get_first_read().empty());
  ASSERT_TRUE(scope_1.get_first_write().empty());

  const auto scope_2 = __dp::Scope2(9);
  ASSERT_EQ(scope_2.get_id(), 9);

  ASSERT_TRUE(scope_2.get_first_read().empty());
  ASSERT_TRUE(scope_2.get_first_write().empty());
}

TEST_F(Scope2Test, testRegisterRead) {
  auto scope = __dp::Scope2(3);
  const auto &reads = scope.get_first_read();
  const auto &writes = scope.get_first_write();

  scope.registerStackRead(24, 0, "");
  scope.registerStackRead(32, 1, "");

  ASSERT_TRUE(writes.empty());
  ASSERT_EQ(reads.size(), 2);

  ASSERT_NE(reads.find(24), reads.end());
  ASSERT_NE(reads.find(32), reads.end());

  scope.registerStackRead(72, 1, "");
  scope.registerStackRead(24, 6, "");
  scope.registerStackRead(32, 1, "");

  ASSERT_TRUE(writes.empty());
  ASSERT_EQ(reads.size(), 3);

  ASSERT_NE(reads.find(24), reads.end());
  ASSERT_NE(reads.find(32), reads.end());
  ASSERT_NE(reads.find(72), reads.end());
}

TEST_F(Scope2Test, testRegisterWrite) {
  auto scope = __dp::Scope2(3);
  const auto &reads = scope.get_first_read();
  const auto &writes = scope.get_first_write();

  scope.registerStackWrite(1024, 0, "");
  scope.registerStackWrite(1032, 1, "");

  ASSERT_TRUE(reads.empty());
  ASSERT_EQ(writes.size(), 2);

  ASSERT_NE(writes.find(1024), writes.end());
  ASSERT_NE(writes.find(1032), writes.end());

  scope.registerStackWrite(1072, 1, "");
  scope.registerStackWrite(1024, 6, "");
  scope.registerStackWrite(1032, 1, "");

  ASSERT_TRUE(reads.empty());
  ASSERT_EQ(writes.size(), 3);

  ASSERT_NE(writes.find(1024), writes.end());
  ASSERT_NE(writes.find(1032), writes.end());
  ASSERT_NE(writes.find(1072), writes.end());
}

TEST_F(Scope2Test, testRegister) {
  auto scope = __dp::Scope2(3);
  const auto &reads = scope.get_first_read();
  const auto &writes = scope.get_first_write();

  scope.registerStackRead(24, 0, "");
  scope.registerStackWrite(1024, 0, "");
  scope.registerStackWrite(1032, 1, "");

  ASSERT_EQ(reads.size(), 1);
  ASSERT_EQ(writes.size(), 2);

  ASSERT_NE(reads.find(24), reads.end());
  ASSERT_NE(writes.find(1024), writes.end());
  ASSERT_NE(writes.find(1032), writes.end());

  scope.registerStackRead(32, 1, "");
  scope.registerStackRead(1024, 5, "");
  scope.registerStackWrite(1876, 0, "");
  scope.registerStackWrite(24, 0, "");

  ASSERT_EQ(reads.size(), 2);
  ASSERT_EQ(writes.size(), 3);

  ASSERT_NE(reads.find(24), reads.end());
  ASSERT_NE(reads.find(32), reads.end());
  ASSERT_NE(writes.find(1024), writes.end());
  ASSERT_NE(writes.find(1024), writes.end());
  ASSERT_NE(writes.find(1876), writes.end());
}

TEST_F(Scope2Test, testCopy1) {
  const auto scope_1 = __dp::Scope2(4);
  const auto scope_2 = __dp::Scope2(scope_1);

  ASSERT_EQ(scope_1.get_id(), scope_2.get_id());
  ASSERT_TRUE(scope_1.get_first_read().empty());
  ASSERT_TRUE(scope_1.get_first_write().empty());
  ASSERT_TRUE(scope_2.get_first_read().empty());
  ASSERT_TRUE(scope_2.get_first_write().empty());
}

TEST_F(Scope2Test, testCopy2) {
  auto scope_1 = __dp::Scope2(4);
  scope_1.registerStackRead(24, 0, "");
  scope_1.registerStackRead(32, 1, "");
  scope_1.registerStackWrite(1024, 0, "");
  scope_1.registerStackWrite(1032, 1, "");

  const auto scope_2 = __dp::Scope2(scope_1);

  ASSERT_EQ(scope_1.get_id(), scope_2.get_id());
  ASSERT_EQ(scope_1.get_first_read(), scope_2.get_first_read());
  ASSERT_EQ(scope_1.get_first_write(), scope_2.get_first_write());
}

TEST_F(Scope2Test, testCopy3) {
  auto scope_1 = __dp::Scope2(4);
  scope_1.registerStackRead(24, 0, "");
  scope_1.registerStackRead(32, 1, "");
  scope_1.registerStackWrite(1024, 0, "");
  scope_1.registerStackWrite(1032, 1, "");

  auto scope_2 = __dp::Scope2(scope_1);
  auto scope_3 = __dp::Scope2(scope_1);

  scope_2.registerStackRead(72, 1, "");
  scope_2.registerStackRead(24, 6, "");
  scope_2.registerStackRead(32, 1, "");

  scope_2.registerStackWrite(1072, 1, "");
  scope_2.registerStackWrite(1024, 6, "");
  scope_2.registerStackWrite(1032, 1, "");

  ASSERT_EQ(scope_1.get_id(), scope_3.get_id());
  ASSERT_EQ(scope_1.get_first_read(), scope_3.get_first_read());
  ASSERT_EQ(scope_1.get_first_write(), scope_3.get_first_write());
}

TEST_F(Scope2Test, testCopy4) {
  auto scope_1 = __dp::Scope2(4);
  scope_1.registerStackRead(24, 0, "");
  scope_1.registerStackRead(32, 1, "");
  scope_1.registerStackWrite(1024, 0, "");
  scope_1.registerStackWrite(1032, 1, "");

  auto scope_2 = __dp::Scope2(scope_1);
  auto scope_3 = __dp::Scope2(scope_1);

  scope_2.registerStackRead(72, 1, "");
  scope_2.registerStackRead(24, 6, "");
  scope_2.registerStackRead(32, 1, "");

  scope_2.registerStackWrite(1072, 1, "");
  scope_2.registerStackWrite(1024, 6, "");
  scope_2.registerStackWrite(1032, 1, "");

  scope_2 = scope_3;

  ASSERT_EQ(scope_1.get_id(), scope_2.get_id());
  ASSERT_EQ(scope_1.get_first_read(), scope_2.get_first_read());
  ASSERT_EQ(scope_1.get_first_write(), scope_2.get_first_write());

  ASSERT_EQ(scope_1.get_id(), scope_3.get_id());
  ASSERT_EQ(scope_1.get_first_read(), scope_3.get_first_read());
  ASSERT_EQ(scope_1.get_first_write(), scope_3.get_first_write());
}

TEST_F(ScopeManager2Test, testScoping) {
  auto manager = __dp::ScopeManager2{};

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

TEST_F(ScopeManager2Test, testRegisterRead) {
  auto manager = __dp::ScopeManager2{};

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

TEST_F(ScopeManager2Test, testRegisterWrite) {
  auto manager = __dp::ScopeManager2{};

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

TEST_F(ScopeManager2Test, testRegister) {
  auto manager = __dp::ScopeManager2{};

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

TEST_F(ScopeManager2Test, testFirstWritten) {
  auto manager = __dp::ScopeManager2{};

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

  ASSERT_TRUE(manager.isOwnedByScope(36, true));
  ASSERT_TRUE(manager.isOwnedByScope(1012, true));
  ASSERT_TRUE(manager.isOwnedByScope(1024, true));

  ASSERT_FALSE(manager.isOwnedByScope(12, true));
  ASSERT_FALSE(manager.isOwnedByScope(24, true));
  ASSERT_FALSE(manager.isOwnedByScope(32, true));
  ASSERT_FALSE(manager.isOwnedByScope(32, false));
  ASSERT_FALSE(manager.isOwnedByScope(40, true));
  ASSERT_FALSE(manager.isOwnedByScope(40, false));
  ASSERT_FALSE(manager.isOwnedByScope(1012, false));
  ASSERT_FALSE(manager.isOwnedByScope(1024, false));
}

TEST_F(ScopeManager2Test, testPositiveChange) {
  auto manager = __dp::ScopeManager2{};

  manager.enterScope("First", 1);
  manager.registerStackRead(24, 0, "");
  manager.registerStackRead(64, 1, "");

  manager.enterScope("Second", 2);
  manager.registerStackWrite(32, 2, "");

  manager.enterScope("Third", 3);
  manager.registerStackWrite(64, 3, "");

  ASSERT_TRUE(manager.positiveScopeChangeOccuredSinceLastAccess(12));
  ASSERT_TRUE(manager.positiveScopeChangeOccuredSinceLastAccess(24));
  ASSERT_TRUE(manager.positiveScopeChangeOccuredSinceLastAccess(32));
  ASSERT_FALSE(manager.positiveScopeChangeOccuredSinceLastAccess(64));

  manager.leaveScope("Third", 3);

  ASSERT_TRUE(manager.positiveScopeChangeOccuredSinceLastAccess(12));
  ASSERT_TRUE(manager.positiveScopeChangeOccuredSinceLastAccess(24));
  ASSERT_FALSE(manager.positiveScopeChangeOccuredSinceLastAccess(32));
  ASSERT_FALSE(manager.positiveScopeChangeOccuredSinceLastAccess(64));

  manager.leaveScope("Second", 2);

  ASSERT_TRUE(manager.positiveScopeChangeOccuredSinceLastAccess(12));
  ASSERT_FALSE(manager.positiveScopeChangeOccuredSinceLastAccess(24));
  ASSERT_FALSE(manager.positiveScopeChangeOccuredSinceLastAccess(32));
  ASSERT_FALSE(manager.positiveScopeChangeOccuredSinceLastAccess(64));

  manager.leaveScope("First", 1);

  // These do not work anymore
  // ASSERT_TRUE(scope.positiveScopeChangeOccuredSinceLastAccess(12));
  // ASSERT_FALSE(scope.positiveScopeChangeOccuredSinceLastAccess(24));
  // ASSERT_FALSE(scope.positiveScopeChangeOccuredSinceLastAccess(32));
  // ASSERT_FALSE(scope.positiveScopeChangeOccuredSinceLastAccess(64));

  manager.enterScope("Forth", 4);

  manager.registerStackRead(24, 4, "");

  ASSERT_TRUE(manager.positiveScopeChangeOccuredSinceLastAccess(12));
  ASSERT_FALSE(manager.positiveScopeChangeOccuredSinceLastAccess(24));
  ASSERT_TRUE(manager.positiveScopeChangeOccuredSinceLastAccess(32));
  ASSERT_TRUE(manager.positiveScopeChangeOccuredSinceLastAccess(64));

  manager.enterScope("Fifth", 5);

  ASSERT_TRUE(manager.positiveScopeChangeOccuredSinceLastAccess(12));
  ASSERT_TRUE(manager.positiveScopeChangeOccuredSinceLastAccess(24));
  ASSERT_TRUE(manager.positiveScopeChangeOccuredSinceLastAccess(32));
  ASSERT_TRUE(manager.positiveScopeChangeOccuredSinceLastAccess(64));
}
