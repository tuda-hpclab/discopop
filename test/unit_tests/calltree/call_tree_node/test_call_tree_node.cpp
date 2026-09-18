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

TEST_F(CallTreeNodeTest, testEqualityNeedsTheSameTypeIdAndParent) {
  auto first_parent = __dp::CallTreeNode();
  auto second_parent = __dp::CallTreeNode();

  const auto node = __dp::CallTreeNode(nullptr, &first_parent, __dp::CallTreeNodeType::Function, 1, 0);
  const auto same = __dp::CallTreeNode(nullptr, &first_parent, __dp::CallTreeNodeType::Function, 1, 0);

  ASSERT_TRUE(node == same);

  // the shared_ptr to the parent is not looked at, only the raw one, which is what lets the
  // comparison run without touching a reference counter
  const auto same_with_an_owning_pointer =
      __dp::CallTreeNode(std::make_shared<__dp::CallTreeNode>(), &first_parent, __dp::CallTreeNodeType::Function, 1, 0);
  ASSERT_TRUE(node == same_with_an_owning_pointer);

  ASSERT_FALSE(node == __dp::CallTreeNode(nullptr, &first_parent, __dp::CallTreeNodeType::Loop, 1, 0));
  ASSERT_FALSE(node == __dp::CallTreeNode(nullptr, &first_parent, __dp::CallTreeNodeType::Function, 2, 0));
  ASSERT_FALSE(node == __dp::CallTreeNode(nullptr, &second_parent, __dp::CallTreeNodeType::Function, 1, 0));
}

TEST_F(CallTreeNodeTest, testEqualityIgnoresTheIterationNumber) {
  auto parent = __dp::CallTreeNode();

  // two iterations of the same loop under the same parent compare equal, which is what the comment
  // in the operator announces
  const auto first = __dp::CallTreeNode(nullptr, &parent, __dp::CallTreeNodeType::Iteration, 2, 1);
  const auto second = __dp::CallTreeNode(nullptr, &parent, __dp::CallTreeNodeType::Iteration, 2, 7);

  ASSERT_NE(first.get_iteration_id(), second.get_iteration_id());
  ASSERT_TRUE(first == second);
}

TEST_F(CallTreeNodeTest, testANodeWithoutAParentIsNotEvenEqualToItself) {
  const auto root = __dp::CallTreeNode();

  // a missing raw parent ends the comparison with false, so the root of a tree compares unequal to
  // everything including itself
  ASSERT_FALSE(root == root);
  ASSERT_FALSE(root == __dp::CallTreeNode());

  auto parent = __dp::CallTreeNode();
  const auto orphan = __dp::CallTreeNode(nullptr, nullptr, __dp::CallTreeNodeType::Function, 1, 0);
  const auto attached = __dp::CallTreeNode(nullptr, &parent, __dp::CallTreeNodeType::Function, 1, 0);

  ASSERT_FALSE(orphan == orphan);
  ASSERT_FALSE(orphan == attached);
}

TEST_F(CallTreeNodeTest, testSetOverwritesEverything) {
  auto parent = std::make_shared<__dp::CallTreeNode>();
  auto *parent_raw = parent.get();
  auto node = __dp::CallTreeNode();

  node.set(std::move(parent), parent_raw, __dp::CallTreeNodeType::Iteration, 2, 7);

  ASSERT_EQ(node.get_node_type(), __dp::CallTreeNodeType::Iteration);
  ASSERT_EQ(node.get_loop_or_function_id(), 2);
  ASSERT_EQ(node.get_iteration_id(), 7);
  ASSERT_NE(node.get_parent_ptr(), nullptr);
  ASSERT_EQ(node.get_parent_ptr_raw(), node.get_parent_ptr().get());

  // the parent is taken over, not shared: this is how the call tree hands its old current node to
  // the node that replaces it
  ASSERT_EQ(parent, nullptr);
  ASSERT_EQ(node.get_parent_ptr().use_count(), 2);
}

TEST_F(CallTreeNodeTest, testSetKeepsTheIterationNumberOfAnyType) {
  auto node = __dp::CallTreeNode();

  // the constructor drops the iteration number unless the node is an iteration node. set() does
  // not, so a function node can carry one. The call tree never passes one for a function, so the
  // difference stays invisible in production.
  node.set(nullptr, nullptr, __dp::CallTreeNodeType::Function, 1, 7);

  ASSERT_EQ(node.get_iteration_id(), 7);
  ASSERT_EQ(__dp::CallTreeNode(nullptr, nullptr, __dp::CallTreeNodeType::Function, 1, 7).get_iteration_id(), 0);
}

TEST_F(CallTreeNodeTest, testANodeCanBeReadThroughAConstReference) {
  auto parent = __dp::CallTreeNode();
  const auto node = __dp::CallTreeNode(nullptr, &parent, __dp::CallTreeNodeType::Iteration, 2, 7);
  const __dp::CallTreeNode &reference = node;

  ASSERT_EQ(reference.get_node_type(), __dp::CallTreeNodeType::Iteration);
  ASSERT_EQ(reference.get_loop_or_function_id(), 2);
  ASSERT_EQ(reference.get_iteration_id(), 7);
  ASSERT_EQ(reference.get_parent_ptr(), nullptr);
  ASSERT_EQ(reference.get_parent_ptr_raw(), &parent);
}
