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

#include "CallTree.hpp"

namespace __dp {
CallTree::CallTree() : ctnqcb(CallTreeNodeQueueChunkBuffer(10)), garbage_collection_chunk_counter(0) {
  current = make_shared<CallTreeNode>();
  if (call_tree_node_count) {
    *call_tree_node_count += 1;
  }
  current_raw = current.get();
  prepared_chunk = ctnqcb.get_prepared_chunk();

  // prepare garbage collection offloading
  garbage_collection_chunk = new std::shared_ptr<CallTreeNode>[CT_GARBAGE_COLLECTION_CHUNK_SIZE];

  // spawn CallTree management thread
  calltree_thread_stop = false;
  pthread_attr_t attr;
  pthread_attr_init(&attr);
  pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_JOINABLE);
  pthread_create(&calltree_thread, &attr, manage_calltree, this);
  pthread_attr_destroy(&attr);

  pthread_attr_t attr_2;
  pthread_attr_init(&attr_2);
  pthread_attr_setdetachstate(&attr_2, PTHREAD_CREATE_JOINABLE);
  pthread_create(&calltree_thread_2, &attr_2, manage_calltree, this);
  pthread_attr_destroy(&attr_2);
}

CallTree::~CallTree() {
  // join CallTree management thread
  calltree_thread_stop = true;

  // collect unregistered garbage
  for (std::size_t i = 0; i < garbage_collection_chunk_counter; ++i) {
    std::shared_ptr<CallTreeNode> to_be_dropped = std::move(garbage_collection_chunk[i]);
  }
  delete[] garbage_collection_chunk;

  pthread_join(calltree_thread, NULL);
  pthread_join(calltree_thread_2, NULL);
  std::cout << "Joined calltree_threads" << std::endl;
}

unsigned int CallTree::get_node_count() {
  if (call_tree_node_count) {
    return call_tree_node_count->load();
  }
  return 0;
}

std::shared_ptr<CallTreeNode> CallTree::get_current_node_ptr() { return current; }

inline void CallTree::offload_garbage_collection() {
  if (garbage_collection_chunk_counter == CT_GARBAGE_COLLECTION_CHUNK_SIZE) {
    // chunk full
    // Offload to worker threads
    {
      std::lock_guard<std::mutex> register_garbage_guard(garbage_collection_buffer_mutex);
      garbage_collection_buffer.push(garbage_collection_chunk);
    }
    // prepare new chunk
    garbage_collection_chunk = new std::shared_ptr<CallTreeNode>[CT_GARBAGE_COLLECTION_CHUNK_SIZE];
    // reset chunk counter
    garbage_collection_chunk_counter = 0;
  }
}

void CallTree::check_and_free_garbage() {
  std::shared_ptr<CallTreeNode> *garbage_chunk_ptr = nullptr;
  {
    // retrieve garbage chunk if one exists
    std::lock_guard<std::mutex> register_garbage_guard(garbage_collection_buffer_mutex);
    if (!(garbage_collection_buffer.empty())) {
      garbage_chunk_ptr = garbage_collection_buffer.front();
      garbage_collection_buffer.pop();
    }
  }

  // process chunk if one has been retrieved
  if (garbage_chunk_ptr) {
    for (std::size_t i = 0; i < CT_GARBAGE_COLLECTION_CHUNK_SIZE; ++i) {
      std::shared_ptr<CallTreeNode> to_be_dropped = std::move(garbage_chunk_ptr[i]);
    }
    delete[] garbage_chunk_ptr;
  }
}

void CallTree::enter_function(unsigned int function_id) {
  if (prepared_chunk->buffer_empty()) {
    delete prepared_chunk;
    prepared_chunk = ctnqcb.get_prepared_chunk();
  }
  std::shared_ptr<CallTreeNode> new_node = std::move(prepared_chunk->get_prepared_node());
  CallTreeNode *new_node_raw = new_node.get();
  new_node_raw->set(std::move(current), current_raw, CallTreeNodeType::Function, function_id, 0);
  current_raw = new_node.get();
  current = std::move(new_node);

  if (call_tree_node_count) {
    *call_tree_node_count += 1;
  }
}

void CallTree::enter_loop(unsigned int loop_id) {
  if (prepared_chunk->buffer_empty()) {
    delete prepared_chunk;
    prepared_chunk = ctnqcb.get_prepared_chunk();
  }
  std::shared_ptr<CallTreeNode> new_node = std::move(prepared_chunk->get_prepared_node());
  new_node->set(std::move(current), current_raw, CallTreeNodeType::Loop, loop_id, 0);
  current_raw = new_node.get();
  current = std::move(new_node);

  if (call_tree_node_count) {
    *call_tree_node_count += 1;
  }
}

void CallTree::enter_iteration(unsigned int iteration_id) {
  // identify loop id of nearest loop
  CallTreeNode *node_ptr_raw = current_raw;
  if (!node_ptr_raw) {
    return;
  }
  unsigned int loop_id = 0;

  // check current node itself
  if (node_ptr_raw->get_node_type() == CallTreeNodeType::Loop) {
    // found nearest loop node
    loop_id = node_ptr_raw->get_loop_or_function_id();
    // create iteration node
    if (prepared_chunk->buffer_empty()) {
      delete prepared_chunk;
      prepared_chunk = ctnqcb.get_prepared_chunk();
    }
    std::shared_ptr<CallTreeNode> new_node = std::move(prepared_chunk->get_prepared_node());
    CallTreeNode *new_node_raw = new_node.get();
    new_node_raw->set(std::move(current), current_raw, CallTreeNodeType::Iteration, loop_id, iteration_id);
    current_raw = new_node.get();
    current = std::move(new_node);

    if (call_tree_node_count) {
      *call_tree_node_count += 1;
    }

    return;
  }

  // check parents. look ahead to allow retrieving the shared_ptr to the loop node via get_parent_ptr() .
  CallTreeNode *parent_ptr_raw = node_ptr_raw->get_parent_ptr_raw();
  while (parent_ptr_raw->get_node_type() != CallTreeNodeType::Root) {
    if (call_tree_node_count) {
      *call_tree_node_count -= 1;
    }
    if (parent_ptr_raw->get_node_type() == CallTreeNodeType::Loop) {
      // found nearest loop node
      loop_id = parent_ptr_raw->get_loop_or_function_id();
      break;
    }
    // continue search with parent node
    node_ptr_raw = node_ptr_raw->get_parent_ptr_raw();
    parent_ptr_raw = parent_ptr_raw->get_parent_ptr_raw();
  }
  // create iteration node
  if (prepared_chunk->buffer_empty()) {
    delete prepared_chunk;
    prepared_chunk = ctnqcb.get_prepared_chunk();
  }
  std::shared_ptr<CallTreeNode> new_node = std::move(prepared_chunk->get_prepared_node());
  CallTreeNode *new_node_raw = new_node.get();
  new_node_raw->set(std::move(node_ptr_raw->get_parent_ptr()), parent_ptr_raw, CallTreeNodeType::Iteration, loop_id,
                    iteration_id);
  garbage_collection_chunk[garbage_collection_chunk_counter++] = std::move(current);
  offload_garbage_collection();
  current_raw = new_node.get();
  current = std::move(new_node);

  if (call_tree_node_count) {
    *call_tree_node_count += 1;
  }
}

void CallTree::exit_function() {
  // set current to the parent of the closest function
  CallTreeNode *node_ptr_raw = current_raw;
  if (!node_ptr_raw) {
    return;
  }
  while (node_ptr_raw->get_node_type() != CallTreeNodeType::Root) {
    if (call_tree_node_count) {
      *call_tree_node_count -= 1;
    }
    if (node_ptr_raw->get_node_type() == CallTreeNodeType::Function) {
      // found closest function node
      break;
    }
    // continue search with parent
    node_ptr_raw = node_ptr_raw->get_parent_ptr_raw();
  }
  current_raw = node_ptr_raw->get_parent_ptr_raw();
  garbage_collection_chunk[garbage_collection_chunk_counter++] = std::move(current);
  offload_garbage_collection();
  current = std::move(node_ptr_raw->get_parent_ptr());
}

void CallTree::exit_loop() {
  // set current to the parent of the closest loop
  CallTreeNode *node_ptr_raw = current_raw;
  if (!node_ptr_raw) {
    return;
  }
  while (node_ptr_raw->get_node_type() != CallTreeNodeType::Root) {
    if (call_tree_node_count) {
      *call_tree_node_count -= 1;
    }
    if (node_ptr_raw->get_node_type() == CallTreeNodeType::Loop) {
      // found closest loop node
      break;
    }
    // continue search with parent
    node_ptr_raw = node_ptr_raw->get_parent_ptr_raw();
  }
  current_raw = node_ptr_raw->get_parent_ptr_raw();
  garbage_collection_chunk[garbage_collection_chunk_counter++] = std::move(current);
  offload_garbage_collection();
  current = std::move(node_ptr_raw->get_parent_ptr());
}

void *manage_calltree(void *arg) {
  std::cout << "Hello world from CallTree manager thread!" << std::endl;
  CallTree *call_tree_ptr = (CallTree *)arg;
  while (!calltree_thread_stop) {
    call_tree_ptr->ctnqcb.prepare_chunk_if_required();
    call_tree_ptr->check_and_free_garbage();
  }
  // collect remaining garbage
  bool garbage_empty = false;
  while (!garbage_empty) {
    call_tree_ptr->check_and_free_garbage();
    {
      std::lock_guard<std::mutex> cleanup_garbage_guard(call_tree_ptr->garbage_collection_buffer_mutex);
      garbage_empty = call_tree_ptr->garbage_collection_buffer.empty();
    }
  }
  pthread_exit(NULL);
  return nullptr;
}

} // namespace __dp
