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

#include <assert.h>
#include <stdint.h>
#include <unistd.h>

#include <fstream>
#include <iostream>  // std::cerr
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "DPTypes.hpp"

namespace dputil {

inline void DecodeLid(std::int64_t lid, std::ostream& out) {
  if (lid == 0) {
    out << '*';
    return;
  }

  // unpack metadata
  // potentially TODO, currently not necessary

  // remove metadata
  lid &= 0x00000000FFFFFFFF;

  out << (lid >> kLidSize) << ':' << lid % kMaxLno;
}

inline std::string DecodeLid(std::int64_t lid) {
  std::stringstream ss;
  DecodeLid(lid, ss);
  return ss.str();
}

inline std::vector<std::string>* Split(const std::string& input, char delim) {
  std::vector<std::string>* substrings = new std::vector<std::string>();
  std::istringstream input_string_stream(input);
  std::string sub;

  while (getline(input_string_stream, sub, delim)) {
    substrings->push_back(sub);
  }

  return substrings;
}

inline int32_t GetFileId(const std::string& file_mapping, const std::string& full_path_name) {
  int32_t index = 0;  // if the associated file id is not found, then we return 0
  std::string line;
  std::ifstream file_map(file_mapping.c_str());

  if (file_map.is_open()) {
    std::vector<std::string>* substrings = nullptr;
    while (getline(file_map, line)) {
      substrings = Split(line, '\t');
      bool found = false;
      if (substrings->size() == 2) {
        const std::string index_string = (*substrings)[0];
        const std::string file_name = (*substrings)[1];
        if (file_name.compare(full_path_name) == 0) {
          index = atoi(index_string.c_str());
          found = true;
        }
      }
      // split() hands out ownership, so the line has to be released on the way out as well
      substrings->clear();
      delete substrings;
      if (found) {
        break;
      }
    }
    file_map.close();
  }
  return index;
}

inline bool FileExists(const std::string& filename) {
  const std::ifstream ifile(filename.c_str());

  if (ifile.fail()) {
    return false;
  }
  return true;
}

inline std::string GetExeDir() {
  char buff[1024];
  const ssize_t len = ::readlink("/proc/self/exe", buff, sizeof(buff) - 1);
  if (len != -1) {
    buff[len] = '\0';
    const std::string full_path = std::string(buff);
    return full_path.substr(0, full_path.find_last_of('/'));
  }
  return "";
}

}  // namespace dputil
