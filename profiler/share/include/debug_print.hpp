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

#include <iostream>

template <std::size_t N> class DebugPrint {
public:
  DebugPrint(const char message[N]) {
    for (auto i = 0; i < N; i++) {
      buffer[i] = message[i];
    }

    std::cout << "enter: " << buffer << '\n';
  }

  ~DebugPrint() { std::cout << "exit: " << buffer << '\n'; }

private:
  char buffer[N];
};

template <std::size_t N> inline DebugPrint<N> make_debug_print(const char (&message)[N]) {
  return DebugPrint<N>(message);
}
