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

namespace dp {
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
SigElement Signature::Insert(std::int64_t elem, SigElement value) {
  std::int32_t begin = Hash(elem) * sig_slot_size_in_byte_;
  std::int32_t end = begin + sig_slot_size_in_byte_ - 1;
  SigElement old_value = 0;
  SigElement temp = 0;
  for (int i = end; i >= begin; --i) {
    temp = sigarray_[i];
    old_value += temp << (end - i) * 8;
    sigarray_[i] = static_cast<std::uint8_t>(value);
    value >>= 8;
  }
  return old_value;
}

// update the value of elem to newValue
// For update the conflict detection is not necessary.
void Signature::Update(std::int64_t elem, SigElement new_value) {
  std::int32_t begin = Hash(elem) * sig_slot_size_in_byte_;
  std::int32_t end = begin + sig_slot_size_in_byte_ - 1;
  for (int i = end; i >= begin; --i) {
    sigarray_[i] = static_cast<std::int8_t>(new_value);
    new_value >>= 8;
  }
}

// remove elem from sigarray
// should be checked.
void Signature::Remove(std::int64_t elem) {
  std::int32_t begin = Hash(elem) * sig_slot_size_in_byte_;
  std::int32_t end = begin + sig_slot_size_in_byte_ - 1;
  for (int i = begin; i <= end; ++i) {
    sigarray_[i] = 0;
  }
}

// test if elem is already exist in sigarray
// see comments for Signature::insert()
// for data layout information
SigElement Signature::MembershipCheck(std::int64_t elem) {
  SigElement res = 0;
  std::int32_t begin = Hash(elem) * sig_slot_size_in_byte_;
  std::int32_t end = begin + sig_slot_size_in_byte_ - 1;
  for (int i = begin; i <= end; ++i) {
    res = (res << 8) + sigarray_[i];
  }
  return res;
}

bool Signature::Intersect(Signature& /*other*/) { return false; }

double Signature::ExpectedFalsePositiveRate() {
  const double result = 0.0;
  return result;
}
}  // namespace dp
