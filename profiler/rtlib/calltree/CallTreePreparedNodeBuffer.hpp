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

#include <iostream>
#include <memory>
#include <mutex>
#include <queue>

#include "CallTreeNode.hpp"

namespace __dp {

#define CTNQC_CHUNK_SIZE 10000

class CallTreeNodeQueueChunk {
public:
  CallTreeNodeQueueChunk() : counter(CTNQC_CHUNK_SIZE) {
    // for(std::size_t i = 0; i < chunk_size; ++i){
    //     buffer.push_back(std::move(std::make_shared<CallTreeNode>()));
    // }
    for (std::size_t i = 0; i < CTNQC_CHUNK_SIZE; ++i) {
      buffer[i] = std::make_shared<CallTreeNode>();
    }
  }

  inline bool buffer_empty() {
    return !(counter != 0);
    //            return buffer.empty();
  }

  inline std::shared_ptr<CallTreeNode> get_prepared_node() {
    return std::move(buffer[--counter]);

    // std::shared_ptr<CallTreeNode> tmp = std::move(buffer.back());
    // buffer.pop_back();
    // return std::move(tmp);
  }

private:
  // std::vector<std::shared_ptr<CallTreeNode>> buffer;
  std::shared_ptr<CallTreeNode> buffer[CTNQC_CHUNK_SIZE];
  std::size_t counter;
};

class CallTreeNodeQueueChunkBuffer {
  // data structure to allow the creation of PreparedCallTreeNodeChunk by worker threads, so the main thread registering
  // the data accesses does not lose this time
public:
  CallTreeNodeQueueChunkBuffer(std::size_t arg_size) : size(arg_size) {}

  inline void prepare_chunk_if_required() {
    bool chunk_required = false;
    {
      const std::lock_guard<std::mutex> lock(internal_mtx);
      if (internal_queue.size() < size) {
        chunk_required = true;
      }
    }

    if (chunk_required) {
      CallTreeNodeQueueChunk *new_chunk = new CallTreeNodeQueueChunk();
      const std::lock_guard<std::mutex> lock(internal_mtx);
      internal_queue.push(new_chunk);
    } else {
      usleep(100); // todo: automatic tuning
    }
  }

  CallTreeNodeQueueChunk *get_prepared_chunk() {
    CallTreeNodeQueueChunk *buffer;
    const std::lock_guard<std::mutex> lock(internal_mtx);
    if (internal_queue.size() > 0) {
      // prepared chunk exists
      buffer = internal_queue.front();
      internal_queue.pop();
      return buffer;
    } else {
      // allocate a new chunk
      std::cout << "FETCH FAILED!" << std::endl;
      return new CallTreeNodeQueueChunk();
    }
  }

private:
  std::queue<CallTreeNodeQueueChunk *> internal_queue;
  std::mutex internal_mtx;
  const std::size_t size;
};

} // namespace __dp
