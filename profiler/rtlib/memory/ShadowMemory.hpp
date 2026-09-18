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
#include "Signature.hpp"

#include <cstdint>
#include <iostream>
#include <stdexcept>

using namespace std;

namespace __dp {

class ShadowMemory : public AbstractShadow {
public:
  ShadowMemory(int slotSize, int size, int numHash) {
    sigRead = new Signature(slotSize, size, numHash);
    sigWrite = new Signature(slotSize, size, numHash);
  }

  ~ShadowMemory() override {
    delete sigRead;
    delete sigWrite;
  }

  inline sigElement testInRead(std::int64_t memAddr) override { return sigRead->membershipCheck(memAddr); }

  inline sigElement testInWrite(std::int64_t memAddr) override { return sigWrite->membershipCheck(memAddr); }

  inline sigElement insertToRead(std::int64_t memAddr, sigElement value) override {
    return sigRead->insert(memAddr, value);
  }

  inline sigElement insertToWrite(std::int64_t memAddr, sigElement value) override {
    return sigWrite->insert(memAddr, value);
  }

  inline void updateInRead(std::int64_t memAddr, sigElement newValue) override { sigRead->update(memAddr, newValue); }

  inline void updateInWrite(std::int64_t memAddr, sigElement newValue) override { sigWrite->update(memAddr, newValue); }

  inline void removeFromRead(std::int64_t memAddr) override { sigRead->remove(memAddr); }

  inline void removeFromWrite(std::int64_t memAddr) override { sigWrite->remove(memAddr); }

  inline std::unordered_set<ADDR> getAddrsInRange(std::int64_t startAddr, std::int64_t endAddr) override {
    // not possible for Shadow, since not all addresses are kept
    std::unordered_set<ADDR> result;
    return result;
  }

  // a signature does not keep the addresses it was given, so it cannot list them back
  inline std::vector<std::pair<std::int64_t, sigElement>> getReadKVPairs() override {
    throw std::logic_error("NOT IMPLEMENTED!");
  }

  inline std::vector<std::pair<std::int64_t, sigElement>> getWriteKVPairs() override {
    throw std::logic_error("NOT IMPLEMENTED!");
  }

  inline void print() override {}

private:
  Signature *sigRead;
  Signature *sigWrite;
};

} // namespace __dp
