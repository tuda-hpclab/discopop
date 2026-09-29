#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/calltree/CallTree.hpp"
#include "../../../../profiler/rtlib/calltree/CallTreeGlobals.hpp"

#include <cstdint>
#include <vector>

// Tests for old version (i.e., capturing functionality)

class CallTreeTest : public ::testing::Test {
  void SetUp() override{
    __dp::call_tree_node_count = new std::atomic<unsigned int>(0);
  }

  void TearDown() override{
    delete __dp::call_tree_node_count;
    __dp::call_tree_node_count = nullptr;
  }
};

TEST_F(CallTreeTest, testConstructor) {
  auto ct = __dp::CallTree();

  ASSERT_EQ(__dp::call_tree_node_count->load(), (unsigned int) 1);
  ASSERT_EQ(ct.get_current_node_ptr()->get_node_type(), __dp::CallTreeNodeType::Root);
}

TEST_F(CallTreeTest, testIncreasingNodeCount) {
  auto ct = __dp::CallTree();

  ASSERT_EQ(ct.get_node_count(), 1);
  ct.enter_function(42);
  ASSERT_EQ(ct.get_node_count(), 2);
  ct.enter_function(43);
  ASSERT_EQ(ct.get_node_count(), 3);
}

TEST_F(CallTreeTest, testDecreasingNodeCount) {
  auto ct = __dp::CallTree();

  ASSERT_EQ(ct.get_node_count(), 1);
  ct.enter_function(42);
  ASSERT_EQ(ct.get_node_count(), 2);
  ct.enter_function(43);
  ASSERT_EQ(ct.get_node_count(), 3);
  ct.exit_function();
  ASSERT_EQ(ct.get_node_count(), 2);
  ct.exit_function();
  ASSERT_EQ(ct.get_node_count(), 1);
}

TEST_F(CallTreeTest, testEnterLoop) {
  auto ct = __dp::CallTree();
  ct.enter_loop(42);

  ASSERT_EQ(ct.get_node_count(), 2);
  ASSERT_EQ(ct.get_current_node_ptr()->get_node_type(), __dp::CallTreeNodeType::Loop);
  ASSERT_EQ(ct.get_current_node_ptr()->get_loop_or_function_id(), 42);
}

TEST_F(CallTreeTest, testExitLoop) {
  auto ct = __dp::CallTree();
  ct.enter_function(42);
  ct.enter_loop(43);
  ct.enter_iteration(1);
  ct.enter_iteration(2);
  ct.exit_loop();

  ASSERT_EQ(ct.get_current_node_ptr()->get_node_type(), __dp::CallTreeNodeType::Function);
  ASSERT_EQ(ct.get_current_node_ptr()->get_loop_or_function_id(), 42);
  ASSERT_EQ(ct.get_node_count(), 2);
}

TEST_F(CallTreeTest, testEnterFunction) {
  auto ct = __dp::CallTree();
  ct.enter_function(42);

  ASSERT_EQ(ct.get_node_count(), 2);
  ASSERT_EQ(ct.get_current_node_ptr()->get_node_type(), __dp::CallTreeNodeType::Function);
  ASSERT_EQ(ct.get_current_node_ptr()->get_loop_or_function_id(), 42);
}

TEST_F(CallTreeTest, testExitFunctionSimple) {
  auto ct = __dp::CallTree();
  ct.enter_function(42);
  ct.enter_loop(43);
  ct.enter_iteration(1);
  ct.enter_iteration(2);
  ct.exit_function();

  ASSERT_EQ(ct.get_current_node_ptr()->get_node_type(), __dp::CallTreeNodeType::Root);
  ASSERT_EQ(ct.get_node_count(), 1);
}

TEST_F(CallTreeTest, testExitFunction) {
  auto ct = __dp::CallTree();
  ct.enter_function(42);
  ct.enter_loop(43);
  ct.enter_iteration(1);
  ct.enter_iteration(2);
  ct.exit_loop();
  ct.enter_loop(44);
  ct.enter_iteration(1);
  // ct.exit_loop(); missing on purpose
  ct.exit_function();

  ASSERT_EQ(ct.get_current_node_ptr()->get_node_type(), __dp::CallTreeNodeType::Root);
  ASSERT_EQ(ct.get_node_count(), 1);
}

TEST_F(CallTreeTest, testEnterIterations) {
  auto ct = __dp::CallTree();
  ct.enter_loop(42);

  ASSERT_EQ(ct.get_node_count(), 2);
  ASSERT_EQ(ct.get_current_node_ptr()->get_node_type(), __dp::CallTreeNodeType::Loop);
  ASSERT_EQ(ct.get_current_node_ptr()->get_loop_or_function_id(), 42);

  ct.enter_iteration(1);
  ASSERT_EQ(ct.get_node_count(), 3);
  ASSERT_EQ(ct.get_current_node_ptr()->get_node_type(), __dp::CallTreeNodeType::Iteration);
  ASSERT_EQ(ct.get_current_node_ptr()->get_loop_or_function_id(), 42);
  ASSERT_EQ(ct.get_current_node_ptr()->get_iteration_id(), 1);

  ct.enter_iteration(2);
  // node of iteration 1 will be deleted, as ct.current pointer is redirected
  ASSERT_EQ(ct.get_node_count(), 3);
  ASSERT_EQ(ct.get_current_node_ptr()->get_node_type(), __dp::CallTreeNodeType::Iteration);
  ASSERT_EQ(ct.get_current_node_ptr()->get_loop_or_function_id(), 42);
  ASSERT_EQ(ct.get_current_node_ptr()->get_iteration_id(), 2);
}

TEST_F(CallTreeTest, testAutomaticCleanup) {
  auto ct = __dp::CallTree();
  ct.enter_function(42);
  ct.enter_loop(43);
  ct.enter_iteration(1);
  ASSERT_EQ(ct.get_node_count(), 4);

  ct.enter_iteration(2);
  // iteration node 1 shall be deleted, since it is not referenced anymore
  ASSERT_EQ(ct.get_node_count(), 4);
}

TEST_F(CallTreeTest, testPreventAutomaticCleanup) {
  auto ct = __dp::CallTree();
  ct.enter_function(42);
  ct.enter_loop(43);
  ct.enter_iteration(1);
  ASSERT_EQ(ct.get_node_count(), 4);

  {
    // save ptr to iteration 1 to prevent cleanup
    std::shared_ptr<__dp::CallTreeNode> dummy_ptr = ct.get_current_node_ptr();

    ct.enter_iteration(2);
    // iteration node 1 shall NOT be deleted, since a referenced still exists
  }

  // dummy_ptr shall now be deleted. Check for automatic cleanup of iteration node 1
  ASSERT_EQ(ct.get_node_count(), 4);
}

TEST_F(CallTreeTest, testImmediateFuncExit) {
  auto ct = __dp::CallTree();
  ct.exit_function();
  // check for segfaults
  ASSERT_TRUE(true);
}
