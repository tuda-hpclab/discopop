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
#include <fstream>
#include <iostream> // std::cerr
#include <sstream>
#include <stdexcept>
#include <stdint.h>
#include <string>
#include <unistd.h>
#include <utility>
#include <vector>

#include "DPTypes.hpp"

using namespace std;

namespace dputil {

inline void decodeLID(std::int64_t lid, std::ostream &out) {
  if (lid == 0) {
    out << '*';
    return;
  }

  // unpack metadata
  // potentially TODO, currently not necessary

  // remove metadata
  lid &= 0x00000000FFFFFFFF;

  out << (lid >> LIDSIZE) << ':' << lid % MAXLNO;
}

inline std::string decodeLID(std::int64_t lid) {
  std::stringstream ss;
  decodeLID(lid, ss);
  return ss.str();
}

inline vector<string> *split(string input, char delim) {
  vector<string> *substrings = new vector<string>();
  istringstream inputStringStream(input);
  string sub;

  while (getline(inputStringStream, sub, delim)) {
    substrings->push_back(sub);
  }

  return substrings;
}

inline int32_t getFileID(string fileMapping, string fullPathName) {
  int32_t index = 0; // if the associated file id is not found, then we return 0
  string line;
  ifstream fileMap(fileMapping.c_str());

  if (fileMap.is_open()) {
    vector<string> *substrings = NULL;
    while (getline(fileMap, line)) {
      substrings = split(line, '\t');
      if (substrings->size() == 2) {
        string indexString = (*substrings)[0];
        string fileName = (*substrings)[1];
        if (fileName.compare(fullPathName) == 0) {
          index = (int32_t)atoi(indexString.c_str());
          break;
        }
      }
      substrings->clear();
      delete substrings;
    }
    fileMap.close();
  }
  return index;
}

inline bool fexists(const string &filename) {
  ifstream ifile(filename.c_str());

  if (ifile.fail())
    return false;
  else
    return true;
}

inline string get_exe_dir() {
  char buff[1024];
  ssize_t len = ::readlink("/proc/self/exe", buff, sizeof(buff) - 1);
  if (len != -1) {
    buff[len] = '\0';
    string fullPath = std::string(buff);
    return fullPath.substr(0, fullPath.find_last_of('/'));
  } else {
    return "";
  }
}

} // namespace dputil
