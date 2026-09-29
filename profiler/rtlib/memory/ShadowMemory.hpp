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

using namespace std;

namespace __dp {

class ShadowMemory : public AbstractShadow {
public:
  ShadowMemory(int slotSize, int size, int numHash) {
    sigRead = new Signature(slotSize, size, numHash);
    sigWrite = new Signature(slotSize, size, numHash);
  }

  ~ShadowMemory() {
    delete sigRead;
    delete sigWrite;
  }

  inline sigElement testInRead(std::int64_t memAddr) { return sigRead->membershipCheck(memAddr); }

  inline sigElement testInWrite(std::int64_t memAddr) { return sigWrite->membershipCheck(memAddr); }

  inline sigElement insertToRead(std::int64_t memAddr, sigElement value) { return sigRead->insert(memAddr, value); }

  inline sigElement insertToWrite(std::int64_t memAddr, sigElement value) { return sigWrite->insert(memAddr, value); }

  inline void updateInRead(std::int64_t memAddr, sigElement newValue) { sigRead->update(memAddr, newValue); }

  inline void updateInWrite(std::int64_t memAddr, sigElement newValue) { sigWrite->update(memAddr, newValue); }

  inline void removeFromRead(std::int64_t memAddr) { sigRead->remove(memAddr); }

  inline void removeFromWrite(std::int64_t memAddr) { sigWrite->remove(memAddr); }

  inline std::unordered_set<ADDR> getAddrsInRange(std::int64_t startAddr, std::int64_t endAddr) {
    // not possible for Shadow, since not all addresses are kept
    std::unordered_set<ADDR> result;
    return result;
  }

  inline std::vector<std::pair<std::int64_t, sigElement>> getReadKVPairs() {
    throw new std::string("NOT IMPLEMENTED!");
  }

  inline std::vector<std::pair<std::int64_t, sigElement>> getWriteKVPairs() {
    throw new std::string("NOT IMPLEMENTED!");
  };

  inline void print() {}

private:
  Signature *sigRead;
  Signature *sigWrite;
};

} // namespace __dp
