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

#include <cassert>
#include <cstdint>

#include <iostream>

namespace __dp {

class Signature {
public:
  Signature(std::int32_t slotSize, std::int32_t size, std::int32_t numOfHash = 1)
      : sigSlotSize(slotSize), numSlot(size), numHash(numOfHash) {
    // Seven bytes is as wide as a slot can get: insert() and membershipCheck() assemble the value
    // in a sigElement, which is signed, so an eighth byte would run into the sign bit. The bound
    // used to be 32, which the shipped SIG_ELEM_BIT of 56 violates -- a debug build would abort
    // here for the width the runtime asks for.
    assert((slotSize % 8 == 0) && (slotSize <= 56 && slotSize >= 8) && "slotSize must be byte aligned!");
    sigSlotSizeInByte = sigSlotSize / 8;
    sigSizeInByte = sigSlotSizeInByte * numSlot;

    sigarray = new std::uint8_t[sigSizeInByte];
    for (int i = 0; i < sigSizeInByte; ++i) {
      sigarray[i] = 0;
    }

    insertedElem = 0;
    conflictElem = 0;
  }

  ~Signature() { delete[] sigarray; }

  sigElement insert(std::int64_t elem, sigElement value);

  void update(std::int64_t elem, sigElement newValue);

  void remove(std::int64_t elem);

  sigElement membershipCheck(std::int64_t elem);

  bool intersect(Signature &other);

  double expectedFalsePositiveRate();

private:
  std::int32_t sigSlotSize; // in bits
  std::int32_t numSlot;
  std::int32_t numHash;           // 1 by default
  std::int32_t sigSlotSizeInByte; // slot size in byte
  std::int32_t sigSizeInByte;     // total size in byte
  std::uint8_t *sigarray;

  std::int32_t insertedElem;
  std::int32_t conflictElem;

  std::uint32_t hash(std::int64_t value) { return (std::uint32_t)((value >> 8) + value) % numSlot; }
};

} // namespace __dp
