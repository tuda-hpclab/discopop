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

#include <string>

namespace __dp {

struct var_info_t {
  std::string var_name_;
  int file_id_ = 0;
  int instr_id_ = 0;
  int loop_line_nr_ = 0;
  int instr_line_ = 0;
  char operation_ = 0;

  bool operator==(const var_info_t &other) const noexcept {
    return var_name_ == other.var_name_ && file_id_ == other.file_id_ && instr_id_ == other.instr_id_ &&
           loop_line_nr_ == other.loop_line_nr_ && instr_line_ == other.instr_line_ && operation_ == other.operation_;
  }

  bool operator!=(const var_info_t &other) const noexcept { return !(*this == other); }
};

} // namespace __dp
