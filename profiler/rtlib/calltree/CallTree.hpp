/*
 * This file is part of the DiscoPoP software
 * (http://www.discopop.tu-darmstadt.de)
 *
 * Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
 *
 * This software may be modified and distributed under the terms of
 * the 3-Clause BSD License. See the LICENSE file in the package base
 * directory for details.
 *
 */

#pragma once

#include "../DPUtils.hpp"

#include "CallTreeGlobals.hpp"
#include "CallTreeNode.hpp"
#include "CallTreePreparedNodeBuffer.hpp"
#include <atomic>
#include <memory>

namespace __dp {

#define CT_GARBAGE_COLLECTION_CHUNK_SIZE 100000

class CallTree {
public:
  CallTree();
  ~CallTree();
  void enter_function(unsigned int function_id);
  void exit_function();
  void enter_loop(unsigned int loop_id);
  void exit_loop();
  void enter_iteration(unsigned int iteration_id);
  // exit_iteration not possible, as determining the iteration end is not trivial
  unsigned int get_node_count();
  std::shared_ptr<CallTreeNode> get_current_node_ptr();

  CallTreeNodeQueueChunkBuffer ctnqcb;

  // Garbage collection
  // idea: instead of overwriting current and potentially having to free multiple CallTreeNode's, move the shared_ptr to
  //       calltree_threads, such that they drop the potentially last reference and free the memory instead of the main
  //       thread.
  std::queue<std::shared_ptr<CallTreeNode> *> garbage_collection_buffer;
  std::shared_ptr<CallTreeNode> *garbage_collection_chunk;
  std::size_t garbage_collection_chunk_counter;
  std::mutex garbage_collection_buffer_mutex;
  void check_and_free_garbage(); // called inside manage_calltree

private:
  std::shared_ptr<CallTreeNode> current;
  CallTreeNode *current_raw;
  pthread_t calltree_thread;
  pthread_t calltree_thread_2;
  CallTreeNodeQueueChunk *prepared_chunk;

  inline void offload_garbage_collection();
};

void *manage_calltree(void *arg);

} // namespace __dp
