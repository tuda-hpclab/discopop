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

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <new>
#include <type_traits>
#include <vector>

#include "lid_constants.hpp"

namespace dp {

// The live stack frames of the instrumented functions of one thread, so that stack memory is analyzed per frame
// instance instead of per address.
//
// The same stack address is reused by every function called at the same depth. Without frames, a read of a variable
// whose initialization the profiler did not see (written by uninstrumented code, or omitted by the hybrid analysis)
// depended on whatever was written last at that address: a local of a function called before, possibly in an earlier
// iteration of a loop, which then looked loop-carried. Analyzed under the key Key(addr) instead -- the frame instance
// that owns the address and the offset in it -- the variables of different frame instances never meet, while every
// access to the variables of one frame instance, also through a pointer from a callee, uses the same key.
//
// A frame is pushed by __dp_func_entry and popped by __dp_func_exit (and by __dp_landing_pad for frames left by an
// exception); its address range is the union of the allocas the function reports to __dp_alloca. Addresses outside
// the live frames (heap, globals, stack memory of uninstrumented code) keep their address as key.
//
// Trivially destructible on purpose: the thread_local instance must outlive the destructors of the thread_local
// objects, as __dp_finalize runs from _dl_fini, after them, and the instrumented global destructors before it still
// enter functions. A destroyed std::vector there took writes into freed memory. The buffer is only freed by Release().
class StackFrames {
 public:
  // Key layout: bit 62 marks a stack key (keys stay positive, as ADDR is signed), bits 24..61 hold the frame id,
  // bits 0..23 the offset in the frame. A frame that does not fit falls back to the plain address.
  static constexpr int kOffsetBits = 24;
  static constexpr int kIdBits = 38;
  static constexpr ADDR kStackKeyBit = ADDR{1} << 62;
  static constexpr ADDR kMaxOffset = (ADDR{1} << kOffsetBits) - 1;
  static constexpr std::uint64_t kMaxId = (std::uint64_t{1} << kIdBits) - 1;

  constexpr StackFrames() noexcept = default;
  StackFrames(const StackFrames&) = delete;
  StackFrames& operator=(const StackFrames&) = delete;

  // Frees the buffer and forgets all frames (frame ids keep growing)
  void Release() noexcept {
    std::free(frames_);
    frames_ = nullptr;
    size_ = 0;
    capacity_ = 0;
  }

  // __dp_func_entry: a new frame without memory yet; it inherits the bounds of the frames around it
  void Push() {
    if (size_ == capacity_) {
      Grow();
    }
    if (size_ == 0) {
      frames_[size_++] = Frame{kEmptyLo, kEmptyHi, next_id_++, kEmptyLo, kEmptyHi};
    } else {
      const Frame outer = frames_[size_ - 1];
      frames_[size_++] = Frame{kEmptyLo, kEmptyHi, next_id_++, outer.all_lo, outer.all_hi};
    }
  }

  // __dp_func_exit; leaving more frames than were entered (a runtime started inside a function) is ignored
  void Pop() noexcept {
    if (size_ != 0) {
      --size_;
    }
  }

  // __dp_alloca: [start, end) belongs to the innermost frame
  void Register(ADDR start, ADDR end) noexcept {
    if (size_ == 0 || end <= start) {
      return;
    }
    Frame& frame = frames_[size_ - 1];
    frame.lo = start < frame.lo ? start : frame.lo;
    frame.hi = end > frame.hi ? end : frame.hi;
    frame.all_lo = start < frame.all_lo ? start : frame.all_lo;
    frame.all_hi = end > frame.all_hi ? end : frame.all_hi;
  }

  // The key an access to addr is analyzed under. Two comparisons for memory outside the live frames; within them
  // usually one more, as most stack accesses go to the innermost frame.
  [[nodiscard]] ADDR Key(ADDR addr) const noexcept {
    if (size_ == 0) {
      return addr;
    }
    const Frame& innermost = frames_[size_ - 1];
    if (addr < innermost.all_lo || addr >= innermost.all_hi) {
      return addr;
    }
    for (std::size_t i = size_; i-- != 0;) {
      const Frame& frame = frames_[i];
      if (addr >= frame.lo && addr < frame.hi) {
        return Encode(frame, addr);
      }
    }
    return addr;
  }

  [[nodiscard]] std::size_t Depth() const noexcept { return size_; }

  // The ids of the live frames, ascending (ids grow from the outermost frame inwards). Taken by the profiled thread
  // when it hands a chunk of accesses over: a frame missing from it has ended and its keys are never used again.
  void LiveIds(std::vector<std::uint64_t>& ids) const {
    ids.clear();
    for (std::size_t i = 0; i < size_; ++i) {
      ids.push_back(frames_[i].id);
    }
  }

  [[nodiscard]] static bool IsStackKey(ADDR key) noexcept { return key >= 0 && (key & kStackKeyBit) != 0; }

  [[nodiscard]] static std::uint64_t FrameIdOf(ADDR key) noexcept {
    return (static_cast<std::uint64_t>(key) & ~static_cast<std::uint64_t>(kStackKeyBit)) >> kOffsetBits;
  }

  // Removes the keys of frames that are not in live_ids (as taken by LiveIds) from a map keyed by access keys, e.g.
  // the shadow of the second access queue, which otherwise keeps a state for every variable of every frame instance.
  // Returns the number of removed keys.
  template <typename Map>
  static std::size_t EraseKeysOfEndedFrames(Map& map, const std::vector<std::uint64_t>& live_ids) {
    std::vector<ADDR> ended;
    for (const auto& entry : map) {
      const ADDR key = entry.first;
      if (IsStackKey(key) && !std::binary_search(live_ids.begin(), live_ids.end(), FrameIdOf(key))) {
        ended.push_back(key);
      }
    }
    for (const ADDR key : ended) {
      map.erase(key);
    }
    return ended.size();
  }

 private:
  struct Frame {
    ADDR lo;  // the memory of the frame's own allocas: [lo, hi)
    ADDR hi;
    std::uint64_t id;
    ADDR all_lo;  // the memory of this and all outer frames, to rule out other memory with two comparisons
    ADDR all_hi;
  };

  static constexpr ADDR kEmptyLo = INT64_MAX;
  static constexpr ADDR kEmptyHi = INT64_MIN;
  static constexpr std::size_t kInitialCapacity = 256;

  void Grow() {
    const std::size_t capacity = capacity_ == 0 ? kInitialCapacity : 2 * capacity_;
    void* frames = std::realloc(frames_, capacity * sizeof(Frame));  // Frame is trivially copyable
    if (frames == nullptr) {
      throw std::bad_alloc();
    }
    frames_ = static_cast<Frame*>(frames);
    capacity_ = capacity;
  }

  // The offset is taken from the top of the frame: the static allocas are all reported on entry, before the first
  // access, and allocas of variable size (alloca(), VLAs) reported later only extend the frame downwards, so an
  // address keeps its key for the whole lifetime of the frame.
  //
  // The shadow maps (emhash7 with the identity hash of integers) choose the bucket by the low bits of the key. The
  // offset alone would put the same variable of every frame instance into the same bucket, so the low bits hold the
  // offset rotated by a multiple of the frame id instead: for a given frame id a bijection, so the keys stay unique.
  [[nodiscard]] static ADDR Encode(const Frame& frame, ADDR addr) noexcept {
    const ADDR offset = frame.hi - 1 - addr;
    if (offset > kMaxOffset || frame.id > kMaxId) {
      return addr;
    }
    const auto spread = static_cast<ADDR>((static_cast<std::uint64_t>(offset) + frame.id * kSpreadFactor) &
                                          static_cast<std::uint64_t>(kMaxOffset));
    return kStackKeyBit | static_cast<ADDR>(frame.id << kOffsetBits) | spread;
  }

  static constexpr std::uint64_t kSpreadFactor = 0x9E3779B1;  // odd: consecutive ids land far apart

  Frame* frames_ = nullptr;  // frames_[0, size_), the innermost last
  std::size_t size_ = 0;
  std::size_t capacity_ = 0;
  std::uint64_t next_id_ = 1;
};

static_assert(std::is_trivially_destructible_v<StackFrames>,
              "stack_frames is used by the global destructors, after the thread_local objects were destroyed");

// The frames of the calling thread (defined in runtimeFunctionsGlobals.cpp); constant initialized and never destroyed,
// so the access needs no TLS wrapper. The buffer of a thread lives until the process ends.
extern constinit thread_local StackFrames stack_frames;

}  // namespace dp
