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

namespace __dp {

struct loop_info_t {
  int line_nr_ = 0;
  int loop_id_ = 0;
  int file_id_ = 0;

  bool operator==(const loop_info_t &other) const noexcept {
    return line_nr_ == other.line_nr_ && loop_id_ == other.loop_id_ && file_id_ == other.file_id_;
  }

  bool operator!=(const loop_info_t &other) const noexcept { return !(*this == other); }
};

} // namespace __dp
