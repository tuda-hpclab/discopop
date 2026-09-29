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

#include "../DPTypes.hpp"

#include <cstdint>
#include <unordered_set>

namespace __dp {

class AbstractShadow {
public:
  virtual ~AbstractShadow() {}

  virtual sigElement testInRead(std::int64_t memAddr) = 0;

  virtual sigElement testInWrite(std::int64_t memAddr) = 0;

  virtual sigElement insertToRead(std::int64_t memAddr, sigElement value) = 0;

  virtual sigElement insertToWrite(std::int64_t memAddr, sigElement value) = 0;

  virtual void updateInRead(std::int64_t memAddr, sigElement newValue) = 0;

  virtual void updateInWrite(std::int64_t memAddr, sigElement newValue) = 0;

  virtual void removeFromRead(std::int64_t memAddr) = 0;

  virtual void removeFromWrite(std::int64_t memAddr) = 0;

  virtual std::unordered_set<ADDR> getAddrsInRange(std::int64_t startAddr, std::int64_t endAddr) = 0;

  virtual std::vector<std::pair<std::int64_t, sigElement>> getReadKVPairs() = 0;

  virtual std::vector<std::pair<std::int64_t, sigElement>> getWriteKVPairs() = 0;

  virtual void print() = 0;
};

} // namespace __dp
