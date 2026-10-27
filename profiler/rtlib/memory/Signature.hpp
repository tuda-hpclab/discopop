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

#include <cassert>
#include <cstdint>
#include <iostream>

#include "DPTypes.hpp"

namespace dp {

class Signature {
 public:
  Signature(std::int32_t slot_size, std::int32_t size, std::int32_t num_of_hash = 1)
      : sig_slot_size_(slot_size), num_slot_(size), num_hash_(num_of_hash) {
    // Seven bytes is as wide as a slot can get: insert() and membershipCheck() assemble the value
    // in a sigElement, which is signed, so an eighth byte would run into the sign bit. The bound
    // used to be 32, which the shipped SIG_ELEM_BIT of 56 violates -- a debug build would abort
    // here for the width the runtime asks for.
    assert((slot_size % 8 == 0) && (slot_size <= 56 && slot_size >= 8) && "slotSize must be byte aligned!");
    sig_slot_size_in_byte_ = sig_slot_size_ / 8;
    sig_size_in_byte_ = sig_slot_size_in_byte_ * num_slot_;

    sigarray_ = new std::uint8_t[sig_size_in_byte_];
    for (int i = 0; i < sig_size_in_byte_; ++i) {
      sigarray_[i] = 0;
    }

    inserted_elem_ = 0;
    conflict_elem_ = 0;
  }

  ~Signature() { delete[] sigarray_; }

  SigElement Insert(std::int64_t elem, SigElement value);

  void Update(std::int64_t elem, SigElement new_value);

  void Remove(std::int64_t elem);

  SigElement MembershipCheck(std::int64_t elem);

  bool Intersect(Signature& other);

  double ExpectedFalsePositiveRate();

 private:
  std::int32_t sig_slot_size_;  // in bits
  std::int32_t num_slot_;
  [[maybe_unused]] std::int32_t num_hash_;  // 1 by default
  std::int32_t sig_slot_size_in_byte_;      // slot size in byte
  std::int32_t sig_size_in_byte_;           // total size in byte
  std::uint8_t* sigarray_;

  std::int32_t inserted_elem_;
  std::int32_t conflict_elem_;

  std::uint32_t Hash(std::int64_t value) const { return static_cast<std::uint32_t>((value >> 8) + value) % num_slot_; }
};

}  // namespace dp
