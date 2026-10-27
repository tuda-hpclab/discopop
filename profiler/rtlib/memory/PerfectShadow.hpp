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

#include <cstdint>
#include <iostream>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "AbstractShadow.hpp"
#include "DPTypes.hpp"

namespace dp {

class PerfectShadow : public AbstractShadow {
 public:
  PerfectShadow(int /*slot_size*/, int /*size*/, int /*num_hash*/) : PerfectShadow() {}

  PerfectShadow() {
    sig_read_ = new std::unordered_map<int64_t, SigElement>();
    sig_write_ = new std::unordered_map<int64_t, SigElement>();
  }

  PerfectShadow(const PerfectShadow& other) = delete;
  PerfectShadow(PerfectShadow&& other) {
    sig_read_ = other.sig_read_;
    sig_write_ = other.sig_write_;

    other.sig_read_ = nullptr;
    other.sig_write_ = nullptr;
  }

  PerfectShadow& operator=(const PerfectShadow& other) = delete;
  PerfectShadow& operator=(PerfectShadow&& other) {
    std::swap(sig_read_, other.sig_read_);
    std::swap(sig_write_, other.sig_write_);

    return *this;
  }

  ~PerfectShadow() override {
    delete sig_read_;
    delete sig_write_;
  }

  inline SigElement TestInRead(std::int64_t mem_addr) override { return (*sig_read_)[mem_addr]; }

  inline SigElement TestInWrite(std::int64_t mem_addr) override { return (*sig_write_)[mem_addr]; }

  inline SigElement InsertToRead(std::int64_t mem_addr, SigElement value) override {
    const SigElement old_value = TestInRead(mem_addr);
    (*sig_read_)[mem_addr] = value;
    return old_value;
  }

  inline SigElement InsertToWrite(std::int64_t mem_addr, SigElement value) override {
    const SigElement old_value = TestInWrite(mem_addr);
    (*sig_write_)[mem_addr] = value;
    return old_value;
  }

  inline void UpdateInRead(std::int64_t mem_addr, SigElement new_value) override { (*sig_read_)[mem_addr] = new_value; }

  inline void UpdateInWrite(std::int64_t mem_addr, SigElement new_value) override {
    (*sig_write_)[mem_addr] = new_value;
  }

  inline void RemoveFromRead(std::int64_t mem_addr) override { (*sig_read_)[mem_addr] = 0; }

  inline void RemoveFromWrite(std::int64_t mem_addr) override { (*sig_write_)[mem_addr] = 0; }

  inline std::unordered_set<ADDR> GetAddrsInRange(std::int64_t start_addr, std::int64_t end_addr) override {
    std::unordered_set<ADDR> result;
    for (auto pair : (*sig_write_)) {
      if ((pair.first >= start_addr) && (pair.first <= end_addr)) {
        result.insert(pair.first);
      }
    }
    for (auto pair : (*sig_read_)) {
      if ((pair.first >= start_addr) && (pair.first <= end_addr)) {
        result.insert(pair.first);
      }
    }
    return result;
  }

  const std::unordered_map<std::int64_t, SigElement>* GetSigRead() const noexcept { return sig_read_; }

  const std::unordered_map<std::int64_t, SigElement>* GetSigWrite() const noexcept { return sig_write_; }

  std::vector<std::pair<std::int64_t, SigElement>> GetReadKvPairs() override {
    std::vector<std::pair<std::int64_t, SigElement>> kv_pairs;
    kv_pairs.reserve(sig_read_->size());
    for (auto kv_pair : *sig_read_) {
      kv_pairs.push_back(kv_pair);
    }
    return kv_pairs;
  }

  std::vector<std::pair<std::int64_t, SigElement>> GetWriteKvPairs() override {
    std::vector<std::pair<std::int64_t, SigElement>> kv_pairs;
    kv_pairs.reserve(sig_write_->size());
    for (auto kv_pair : *sig_write_) {
      kv_pairs.push_back(kv_pair);
    }
    return kv_pairs;
  }

  inline void Print() override { std::cout << "Hello from PerfectShadow" << std::endl; }

 private:
  std::unordered_map<std::int64_t, SigElement>* sig_read_;
  std::unordered_map<std::int64_t, SigElement>* sig_write_;
};

// Hopefully faster version

class PerfectShadow2 : public AbstractShadow {
 public:
  PerfectShadow2() {
    read_cache_.reserve(1024);
    write_cache_.reserve(1024);
  }

  ~PerfectShadow2() override {}

  SigElement TestInRead(const std::int64_t mem_addr) noexcept override { return read_cache_[mem_addr]; }

  SigElement TestInWrite(const std::int64_t mem_addr) noexcept override { return write_cache_[mem_addr]; }

  SigElement InsertToRead(const std::int64_t mem_addr, const SigElement value) override {
    const auto iterator = read_cache_.find(mem_addr);

    if (iterator == read_cache_.end()) {
      read_cache_[mem_addr] = value;
      return 0;
    }

    const auto old_value = iterator->second;
    iterator->second = value;
    return old_value;
  }

  SigElement InsertToWrite(const std::int64_t mem_addr, const SigElement value) override {
    const auto iterator = write_cache_.find(mem_addr);

    if (iterator == write_cache_.end()) {
      write_cache_[mem_addr] = value;
      return 0;
    }

    const auto old_value = iterator->second;
    iterator->second = value;
    return old_value;
  }

  void UpdateInRead(const std::int64_t mem_addr, const SigElement new_value) noexcept override {
    read_cache_[mem_addr] = new_value;
  }

  void UpdateInWrite(const std::int64_t mem_addr, const SigElement new_value) noexcept override {
    write_cache_[mem_addr] = new_value;
  }

  void RemoveFromRead(const std::int64_t mem_addr) override { read_cache_[mem_addr] = 0; }

  void RemoveFromWrite(const std::int64_t mem_addr) override { write_cache_[mem_addr] = 0; }

  std::unordered_set<ADDR> GetAddrsInRange(const std::int64_t start_addr,
                                           const std::int64_t end_addr) noexcept override {
    std::unordered_set<ADDR> result{};
    result.reserve(read_cache_.size() + write_cache_.size());

    for (const auto& pair : read_cache_) {
      const auto addr = pair.first;
      if (addr >= start_addr && addr <= end_addr) {
        result.insert(addr);
      }
    }

    for (const auto& pair : write_cache_) {
      const auto addr = pair.first;
      if (addr >= start_addr && addr <= end_addr) {
        result.insert(addr);
      }
    }

    return result;
  }

  const HashMap<int64_t, SigElement>* GetSigRead() const noexcept { return &read_cache_; }

  const HashMap<int64_t, SigElement>* GetSigWrite() const noexcept { return &write_cache_; }

  std::vector<std::pair<std::int64_t, SigElement>> GetReadKvPairs() override {
    std::vector<std::pair<std::int64_t, SigElement>> kv_pairs;
    kv_pairs.reserve(read_cache_.size());
    for (const auto& kv_pair : read_cache_) {
      kv_pairs.emplace_back(kv_pair.first, kv_pair.second);
    }
    return kv_pairs;
  }

  std::vector<std::pair<std::int64_t, SigElement>> GetWriteKvPairs() override {
    std::vector<std::pair<std::int64_t, SigElement>> kv_pairs;
    kv_pairs.reserve(write_cache_.size());
    for (const auto& kv_pair : write_cache_) {
      kv_pairs.emplace_back(kv_pair.first, kv_pair.second);
    }
    return kv_pairs;
  }

  void Print() override {
    std::cout << "ADDR \t READ \t WRITE\t\t// Shadow Memory" << std::endl;
    std::cout << "-------------------------" << std::endl;
    for (const auto& pair : read_cache_) {
      std::cout << "| " << pair.first << "\t| " << pair.second << "\t| " << write_cache_[pair.first] << "\t|"
                << std::endl;
    }
    std::cout << "-------------------------" << std::endl;
    std::cout << std::endl;
  }

 private:
  HashMap<int64_t, SigElement> read_cache_{};
  HashMap<int64_t, SigElement> write_cache_{};
};

}  // namespace dp
