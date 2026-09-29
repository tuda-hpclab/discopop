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

#include "Signature.hpp"

#include <cstdint>
#include <iostream>

using namespace std;

namespace __dp {
// Byte wise signature

// insert new value into signature
// low index of signature store the lower part of value
// for example value is in 16 bits store in
// sigarray[0] and sigarray[1]:
// value:    16 ------ 8 7 ------- 0
//           |         | |         |
// sigarray: |--- 0 ---| |--- 1 ---|
//
// The semantic of insert means elem is always a new
// element. Hence if the slot selected for elem is
// already used, a conflict is detected. In this case
// the value is still inserted, which means the old
// value is overwritten. Meanwhile, conflictElem is
// increased by 1.
sigElement Signature::insert(int64_t elem, sigElement value) {
  int32_t begin = hash(elem) * sigSlotSizeInByte;
  int32_t end = begin + sigSlotSizeInByte - 1;
  sigElement oldValue = 0;
  sigElement temp = 0;
  for (int i = end; i >= begin; --i) {
    temp = sigarray[i];
    oldValue += temp << (end - i) * 8;
    sigarray[i] = (uint8_t)value;
    value >>= 8;
  }
  return oldValue;
}

// update the value of elem to newValue
// For update the conflict detection is not necessary.
void Signature::update(int64_t elem, sigElement newValue) {
  int32_t begin = hash(elem) * sigSlotSizeInByte;
  int32_t end = begin + sigSlotSizeInByte - 1;
  for (int i = end; i >= begin; --i) {
    sigarray[i] = (int8_t)newValue;
    newValue >>= 8;
  }
}

// remove elem from sigarray
// should be checked.
void Signature::remove(int64_t elem) {
  int32_t begin = hash(elem) * sigSlotSizeInByte;
  int32_t end = begin + sigSlotSizeInByte - 1;
  for (int i = begin; i <= end; ++i) {
    sigarray[i] = 0;
  }
}

// test if elem is already exist in sigarray
// see comments for Signature::insert()
// for data layout information
sigElement Signature::membershipCheck(int64_t elem) {
  sigElement res = 0;
  int32_t begin = hash(elem) * sigSlotSizeInByte;
  int32_t end = begin + sigSlotSizeInByte - 1;
  for (int i = begin; i <= end; ++i) {
    res = (res << 8) + sigarray[i];
  }
  return res;
}

bool Signature::intersect(Signature &other) { return false; }

double Signature::expectedFalsePositiveRate() {
  double result = 0.0;
  return result;
}
} // namespace __dp
