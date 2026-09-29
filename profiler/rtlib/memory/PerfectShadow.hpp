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

#include "AbstractShadow.hpp"

#include "../DPTypes.hpp"

#include <cstdint>
#include <iostream>
#include <unordered_map>
#include <unordered_set>

namespace __dp {

class PerfectShadow : public AbstractShadow {
public:
  PerfectShadow(int slotSize, int size, int numHash) : PerfectShadow() {}

  PerfectShadow() {
    sigRead = new std::unordered_map<int64_t, sigElement>();
    sigWrite = new std::unordered_map<int64_t, sigElement>();
  }

  PerfectShadow(const PerfectShadow &other) = delete;
  PerfectShadow(PerfectShadow &&other) {
    sigRead = other.sigRead;
    sigWrite = other.sigWrite;

    other.sigRead = nullptr;
    other.sigWrite = nullptr;
  }

  PerfectShadow &operator=(const PerfectShadow &other) = delete;
  PerfectShadow &operator=(PerfectShadow &&other) {
    std::swap(sigRead, other.sigRead);
    std::swap(sigWrite, other.sigWrite);

    return *this;
  }

  ~PerfectShadow() {
    delete sigRead;
    delete sigWrite;
  }

  inline sigElement testInRead(std::int64_t memAddr) { return (*sigRead)[memAddr]; }

  inline sigElement testInWrite(std::int64_t memAddr) { return (*sigWrite)[memAddr]; }

  inline sigElement insertToRead(std::int64_t memAddr, sigElement value) {
    sigElement oldValue = testInRead(memAddr);
    (*sigRead)[memAddr] = value;
    return oldValue;
  }

  inline sigElement insertToWrite(std::int64_t memAddr, sigElement value) {
    sigElement oldValue = testInWrite(memAddr);
    (*sigWrite)[memAddr] = value;
    return oldValue;
  }

  inline void updateInRead(std::int64_t memAddr, sigElement newValue) { (*sigRead)[memAddr] = newValue; }

  inline void updateInWrite(std::int64_t memAddr, sigElement newValue) { (*sigWrite)[memAddr] = newValue; }

  inline void removeFromRead(std::int64_t memAddr) { (*sigRead)[memAddr] = 0; }

  inline void removeFromWrite(std::int64_t memAddr) { (*sigWrite)[memAddr] = 0; }

  inline std::unordered_set<ADDR> getAddrsInRange(std::int64_t startAddr, std::int64_t endAddr) {
    std::unordered_set<ADDR> result;
    for (auto pair : (*sigWrite)) {
      if ((pair.first >= startAddr) && (pair.first <= endAddr)) {
        result.insert(pair.first);
      }
    }
    for (auto pair : (*sigRead)) {
      if ((pair.first >= startAddr) && (pair.first <= endAddr)) {
        result.insert(pair.first);
      }
    }
    return result;
  }

  const std::unordered_map<std::int64_t, sigElement> *getSigRead() const noexcept { return sigRead; }

  const std::unordered_map<std::int64_t, sigElement> *getSigWrite() const noexcept { return sigWrite; }

  std::vector<std::pair<std::int64_t, sigElement>> getReadKVPairs() {
    std::vector<std::pair<std::int64_t, sigElement>> kv_pairs;
    kv_pairs.reserve(sigRead->size());
    for (auto kv_pair : *sigRead) {
      kv_pairs.push_back(kv_pair);
    }
    return kv_pairs;
  }

  std::vector<std::pair<std::int64_t, sigElement>> getWriteKVPairs() {
    std::vector<std::pair<std::int64_t, sigElement>> kv_pairs;
    kv_pairs.reserve(sigWrite->size());
    for (auto kv_pair : *sigWrite) {
      kv_pairs.push_back(kv_pair);
    }
    return kv_pairs;
  }

  inline void print() { std::cout << "Hello from PerfectShadow" << std::endl; }

private:
  std::unordered_map<std::int64_t, sigElement> *sigRead;
  std::unordered_map<std::int64_t, sigElement> *sigWrite;
};

// Hopefully faster version

class PerfectShadow2 : public AbstractShadow {
public:
  PerfectShadow2() {
    read_cache.reserve(1024);
    write_cache.reserve(1024);
  }

  ~PerfectShadow2() {}

  sigElement testInRead(const std::int64_t memAddr) noexcept { return read_cache[memAddr]; }

  sigElement testInWrite(const std::int64_t memAddr) noexcept { return write_cache[memAddr]; }

  sigElement insertToRead(const std::int64_t memAddr, const sigElement value) {
    const auto iterator = read_cache.find(memAddr);

    if (iterator == read_cache.end()) {
      read_cache[memAddr] = value;
      return 0;
    }

    const auto old_value = iterator->second;
    iterator->second = value;
    return old_value;
  }

  sigElement insertToWrite(const std::int64_t memAddr, const sigElement value) {
    const auto iterator = write_cache.find(memAddr);

    if (iterator == write_cache.end()) {
      write_cache[memAddr] = value;
      return 0;
    }

    const auto old_value = iterator->second;
    iterator->second = value;
    return old_value;
  }

  void updateInRead(const std::int64_t memAddr, const sigElement newValue) noexcept { read_cache[memAddr] = newValue; }

  void updateInWrite(const std::int64_t memAddr, const sigElement newValue) noexcept {
    write_cache[memAddr] = newValue;
  }

  void removeFromRead(const std::int64_t memAddr) { read_cache[memAddr] = 0; }

  void removeFromWrite(const std::int64_t memAddr) { write_cache[memAddr] = 0; }

  std::unordered_set<ADDR> getAddrsInRange(const std::int64_t startAddr, const std::int64_t endAddr) noexcept {
    std::unordered_set<ADDR> result{};
    result.reserve(read_cache.size() + write_cache.size());

    for (const auto &pair : read_cache) {
      const auto addr = pair.first;
      if (addr >= startAddr && addr <= endAddr) {
        result.insert(addr);
      }
    }

    for (const auto &pair : write_cache) {
      const auto addr = pair.first;
      if (addr >= startAddr && addr <= endAddr) {
        result.insert(addr);
      }
    }

    return result;
  }

  const hashmap<int64_t, sigElement> *getSigRead() const noexcept { return &read_cache; }

  const hashmap<int64_t, sigElement> *getSigWrite() const noexcept { return &write_cache; }

  std::vector<std::pair<std::int64_t, sigElement>> getReadKVPairs() {
    std::vector<std::pair<std::int64_t, sigElement>> kv_pairs;
    kv_pairs.reserve(read_cache.size());
    for (auto kv_pair : read_cache) {
      kv_pairs.emplace_back(kv_pair.first, kv_pair.second);
    }
    return kv_pairs;
  }

  std::vector<std::pair<std::int64_t, sigElement>> getWriteKVPairs() {
    std::vector<std::pair<std::int64_t, sigElement>> kv_pairs;
    kv_pairs.reserve(write_cache.size());
    for (auto kv_pair : write_cache) {
      kv_pairs.emplace_back(kv_pair.first, kv_pair.second);
    }
    return kv_pairs;
  }

  void print() {
    std::cout << "ADDR \t READ \t WRITE\t\t// Shadow Memory" << std::endl;
    std::cout << "-------------------------" << std::endl;
    for (auto pair : read_cache) {
      std::cout << "| " << pair.first << "\t| " << pair.second << "\t| " << write_cache[pair.first] << "\t|"
                << std::endl;
    }
    std::cout << "-------------------------" << std::endl;
    std::cout << std::endl;
  }

private:
  hashmap<int64_t, sigElement> read_cache{};
  hashmap<int64_t, sigElement> write_cache{};
};

} // namespace __dp
