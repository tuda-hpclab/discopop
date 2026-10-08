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

#include <new>
#include <utility>

namespace __dp {

// Storage for a global whose lifetime the runtime manages by hand.
//
// __dp_finalize writes the profiling results and has to run late: the destructors of the target's
// global objects are instrumented as well, and their accesses still have to be recorded. A plain
// namespace-scope object cannot be used from that point on. The compiler registers its destructor
// with __cxa_atexit when the object is constructed, so it is torn down together with the target's
// own globals, and reading it afterwards is undefined behaviour -- the kind that looks harmless in
// a test run, because the memory has not been reused yet.
//
// The object therefore lives in a union member, which is never destroyed on the compiler's behalf.
// Its lifetime is explicit instead: construct() when the runtime starts up, destroy() at the end of
// __dp_finalize, after the last use. Nothing is leaked and no destruction order can get in the way.
//
// Callers reach the object through a reference bound to `value`. That reference is an address
// constant, so it is established before any initializer runs; only the object behind it has to be
// constructed first.
template <typename T> union ImmortalStorage {
  T value;
  char placeholder;

  // leaves `value` unconstructed, and is constexpr, so this storage needs no initializer of its own
  constexpr ImmortalStorage() : placeholder() {}

  // deliberately empty -- `value` is destroyed by destroy(). The union still has a non-trivial
  // destructor, so an (empty) entry is registered with __cxa_atexit; it touches nothing.
  ~ImmortalStorage() {}

  ImmortalStorage(const ImmortalStorage &) = delete;
  ImmortalStorage &operator=(const ImmortalStorage &) = delete;

  template <typename... Args> void construct(Args &&...args) {
    ::new (static_cast<void *>(&value)) T(std::forward<Args>(args)...);
  }

  void destroy() { value.~T(); }
};

} // namespace __dp
