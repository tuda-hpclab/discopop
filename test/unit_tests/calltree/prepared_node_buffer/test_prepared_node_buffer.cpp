#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/calltree/CallTreeGlobals.hpp"
#include "../../../../profiler/rtlib/calltree/CallTreeNodeType.hpp"
#include "../../../../profiler/rtlib/calltree/CallTreePreparedNodeBuffer.hpp"

#include <atomic>
#include <cstddef>
#include <memory>

namespace {
constexpr unsigned int chunk_size = CTNQC_CHUNK_SIZE;
} // namespace

// The call tree does not allocate a node whenever a function is entered. It takes one from a chunk
// of CTNQC_CHUNK_SIZE nodes that the manager threads fill in the background, so the thread that
// records the accesses never waits for an allocation.
//
// call_tree_total_living_node_count counts the nodes that exist, prepared ones included. It is a
// null pointer unless someone switches it on, which is what the fixture does here.
class CallTreePreparedNodeBufferTest : public ::testing::Test {
protected:
  void SetUp() override { __dp::call_tree_total_living_node_count = &living_nodes; }
  void TearDown() override { __dp::call_tree_total_living_node_count = nullptr; }

  std::atomic<unsigned int> living_nodes{0};
};

TEST_F(CallTreePreparedNodeBufferTest, testAChunkBuildsItsNodesUpFront) {
  {
    const auto chunk = __dp::CallTreeNodeQueueChunk{};

    ASSERT_EQ(living_nodes.load(), chunk_size);
  }

  ASSERT_EQ(living_nodes.load(), 0u);
}

TEST_F(CallTreePreparedNodeBufferTest, testAChunkHandsOutExactlyItsSize) {
  auto chunk = __dp::CallTreeNodeQueueChunk{};

  ASSERT_FALSE(chunk.buffer_empty());

  for (unsigned int i = 0; i < chunk_size; ++i) {
    const auto node = chunk.get_prepared_node();

    ASSERT_NE(node, nullptr);
    // a prepared node is a default constructed one, which is a root. The call tree overwrites all
    // of that through set() when it takes the node into use.
    ASSERT_EQ(node->get_node_type(), __dp::CallTreeNodeType::Root);
    ASSERT_EQ(node->get_loop_or_function_id(), 0u);
    ASSERT_EQ(node->get_iteration_id(), 0u);
    ASSERT_EQ(node->get_parent_ptr(), nullptr);
  }

  ASSERT_TRUE(chunk.buffer_empty());
}

TEST_F(CallTreePreparedNodeBufferTest, testADrainedChunkHoldsNothingBack) {
  {
    auto chunk = __dp::CallTreeNodeQueueChunk{};
    for (unsigned int i = 0; i < chunk_size; ++i) {
      chunk.get_prepared_node();
    }

    // the nodes are moved out of the chunk, so dropping every returned pointer right away already
    // brings the count back to zero although the chunk is still alive
    ASSERT_EQ(living_nodes.load(), 0u);
  }

  ASSERT_EQ(living_nodes.load(), 0u);
}

TEST_F(CallTreePreparedNodeBufferTest, testAHandedOutNodeOutlivesItsChunk) {
  std::shared_ptr<__dp::CallTreeNode> node;

  {
    auto chunk = __dp::CallTreeNodeQueueChunk{};
    node = chunk.get_prepared_node();
  }

  ASSERT_NE(node, nullptr);
  ASSERT_EQ(node.use_count(), 1);
  ASSERT_EQ(living_nodes.load(), 1u);

  node = nullptr;
  ASSERT_EQ(living_nodes.load(), 0u);
}

TEST_F(CallTreePreparedNodeBufferTest, testAnEmptyPoolBuildsAChunkOnDemand) {
  auto buffer = __dp::CallTreeNodeQueueChunkBuffer{10};

  // nothing has been prepared yet, so the caller pays for the chunk itself instead of being told
  // that the pool ran dry
  auto *chunk = buffer.get_prepared_chunk();

  ASSERT_NE(chunk, nullptr);
  ASSERT_FALSE(chunk->buffer_empty());
  ASSERT_EQ(living_nodes.load(), chunk_size);

  delete chunk;
  ASSERT_EQ(living_nodes.load(), 0u);
}

TEST_F(CallTreePreparedNodeBufferTest, testThePoolStopsAtTheRequestedSize) {
  auto buffer = __dp::CallTreeNodeQueueChunkBuffer{2};

  // this is the call the manager threads repeat for as long as the call tree lives
  buffer.prepare_chunk_if_required();
  ASSERT_EQ(living_nodes.load(), chunk_size);

  buffer.prepare_chunk_if_required();
  ASSERT_EQ(living_nodes.load(), 2 * chunk_size);

  // the pool holds its size now, so the next call sleeps instead of preparing a third chunk
  buffer.prepare_chunk_if_required();
  ASSERT_EQ(living_nodes.load(), 2 * chunk_size);

  auto *first = buffer.get_prepared_chunk();
  auto *second = buffer.get_prepared_chunk();
  ASSERT_NE(first, second);
  delete first;
  delete second;

  ASSERT_EQ(living_nodes.load(), 0u);
}

TEST_F(CallTreePreparedNodeBufferTest, testThePoolFreesWhatIsLeftInIt) {
  {
    auto buffer = __dp::CallTreeNodeQueueChunkBuffer{2};
    buffer.prepare_chunk_if_required();
    buffer.prepare_chunk_if_required();

    ASSERT_EQ(living_nodes.load(), 2 * chunk_size);
  }

  // a chunk that was prepared but never handed out is owned by the pool alone, so nobody else can
  // free it
  ASSERT_EQ(living_nodes.load(), 0u);
}

TEST_F(CallTreePreparedNodeBufferTest, testACopiedNodeIsCountedAsWell) {
  auto node = __dp::CallTreeNode();
  ASSERT_EQ(living_nodes.load(), 1u);

  {
    // the destructor lowers the count for every node, so a copy has to raise it -- otherwise the
    // count drops below zero and wraps, because it is unsigned
    const auto copy = node;
    ASSERT_EQ(living_nodes.load(), 2u);
  }

  ASSERT_EQ(living_nodes.load(), 1u);

  // assignment replaces what a node holds without creating or destroying one, so it leaves the
  // count alone
  node = __dp::CallTreeNode(nullptr, nullptr, __dp::CallTreeNodeType::Function, 1, 0);
  ASSERT_EQ(living_nodes.load(), 1u);
  ASSERT_EQ(node.get_node_type(), __dp::CallTreeNodeType::Function);
}
