#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/calltree/CallTreeNode.hpp"
#include "../../../../profiler/rtlib/calltree/CallTreeNodeType.hpp"

class CallTreeNodeTest : public ::testing::Test {};

TEST_F(CallTreeNodeTest, testConstructor) {
  auto ctn = __dp::CallTreeNode(nullptr, nullptr, __dp::CallTreeNodeType::Function, 1, 0);

  ASSERT_EQ(ctn.get_loop_or_function_id(), 1);
  ASSERT_EQ(ctn.get_node_type(), __dp::CallTreeNodeType::Function);
}

TEST_F(CallTreeNodeTest, testDefaultConstructor) {
  auto ctn = __dp::CallTreeNode();

  ASSERT_EQ(ctn.get_loop_or_function_id(), 0);
  ASSERT_EQ(ctn.get_node_type(), __dp::CallTreeNodeType::Root);
  ASSERT_EQ(ctn.get_iteration_id(), 0);
  ASSERT_EQ(ctn.get_parent_ptr(), nullptr);
}

TEST_F(CallTreeNodeTest, testGetIterationId) {
  auto ctn = __dp::CallTreeNode(nullptr, nullptr, __dp::CallTreeNodeType::Root, 0, 0);
  ASSERT_EQ(ctn.get_loop_or_function_id(), 0);
  ASSERT_EQ(ctn.get_node_type(), __dp::CallTreeNodeType::Root);
  ASSERT_EQ(ctn.get_iteration_id(), 0);

  ctn = __dp::CallTreeNode(nullptr, nullptr, __dp::CallTreeNodeType::Root, 0, 1);
  ASSERT_EQ(ctn.get_loop_or_function_id(), 0);
  ASSERT_EQ(ctn.get_node_type(), __dp::CallTreeNodeType::Root);
  ASSERT_EQ(ctn.get_iteration_id(), 0);

  ctn = __dp::CallTreeNode(nullptr, nullptr, __dp::CallTreeNodeType::Function, 1, 0);
  ASSERT_EQ(ctn.get_loop_or_function_id(), 1);
  ASSERT_EQ(ctn.get_node_type(), __dp::CallTreeNodeType::Function);
  ASSERT_EQ(ctn.get_iteration_id(), 0);

  ctn = __dp::CallTreeNode(nullptr, nullptr, __dp::CallTreeNodeType::Function, 1, 1);
  ASSERT_EQ(ctn.get_loop_or_function_id(), 1);
  ASSERT_EQ(ctn.get_node_type(), __dp::CallTreeNodeType::Function);
  ASSERT_EQ(ctn.get_iteration_id(), 0);

  ctn = __dp::CallTreeNode(nullptr, nullptr, __dp::CallTreeNodeType::Loop, 2, 0);
  ASSERT_EQ(ctn.get_loop_or_function_id(), 2);
  ASSERT_EQ(ctn.get_node_type(), __dp::CallTreeNodeType::Loop);
  ASSERT_EQ(ctn.get_iteration_id(), 0);

  ctn = __dp::CallTreeNode(nullptr, nullptr, __dp::CallTreeNodeType::Loop, 2, 1);
  ASSERT_EQ(ctn.get_loop_or_function_id(), 2);
  ASSERT_EQ(ctn.get_node_type(), __dp::CallTreeNodeType::Loop);
  ASSERT_EQ(ctn.get_iteration_id(), 0);

  ctn = __dp::CallTreeNode(nullptr, nullptr, __dp::CallTreeNodeType::Iteration, 2, 1);
  ASSERT_EQ(ctn.get_loop_or_function_id(), 2);
  ASSERT_EQ(ctn.get_node_type(), __dp::CallTreeNodeType::Iteration);
  ASSERT_EQ(ctn.get_iteration_id(), 1);
}

TEST_F(CallTreeNodeTest, testGetParentPtr) {
  auto root = __dp::CallTreeNode();
  auto function = __dp::CallTreeNode(make_shared<__dp::CallTreeNode>(root), nullptr,__dp::CallTreeNodeType::Function, 1, 0);
  auto loop = __dp::CallTreeNode(make_shared<__dp::CallTreeNode>(function), nullptr, __dp::CallTreeNodeType::Loop, 2, 0);
  auto iteration = __dp::CallTreeNode(make_shared<__dp::CallTreeNode>(loop), nullptr, __dp::CallTreeNodeType::Iteration, 2, 1);

  ASSERT_EQ(iteration.get_parent_ptr()->get_node_type(), __dp::CallTreeNodeType::Loop);
  ASSERT_EQ(iteration.get_parent_ptr()->get_loop_or_function_id(), 2);
  ASSERT_EQ(iteration.get_parent_ptr()->get_iteration_id(), 0);

  ASSERT_EQ(iteration.get_parent_ptr()->get_parent_ptr()->get_node_type(), __dp::CallTreeNodeType::Function);
  ASSERT_EQ(iteration.get_parent_ptr()->get_parent_ptr()->get_loop_or_function_id(), 1);
  ASSERT_EQ(iteration.get_parent_ptr()->get_parent_ptr()->get_iteration_id(), 0);
}
