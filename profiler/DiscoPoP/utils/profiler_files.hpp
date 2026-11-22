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

#include <cerrno>
#include <fstream>
#include <fcntl.h>
#include <ios>
#include <stdexcept>
#include <string>
#include <sys/file.h>
#include <unistd.h>

#include "DPUtils.hpp"

// The files the pass writes into the profiler directory (DOT_DISCOPOP_PROFILER, default
// .discopop/profiler). A stream returned by open closes itself, and so flushes, when it goes
// out of scope; a file that cannot be opened is a stream with failbit set, to which writing does nothing,
// as it did before.
namespace profiler_files {

inline std::string Path(const std::string& name) {
  return dputil::GetEnvOrDefault("DOT_DISCOPOP_PROFILER", ".discopop/profiler") + "/" + name;
}

inline std::string LockPath(const std::string& name, bool is_full_path) {
  if (is_full_path) {
    const std::string::size_type separator = name.rfind('/');

    if (separator == std::string::npos) {
      return name + ".lock";
    }

    return dputil::ProfilerLockPath(name.substr(0, separator), name.substr(separator + 1) + ".lock");
  }

  return dputil::ProfilerLockPath(dputil::GetEnvOrDefault("DOT_DISCOPOP_PROFILER", ".discopop/profiler"), name + ".lock");
}

// Holds an exclusive lock for the lifetime of a single output operation. The lock is
// process-wide through the kernel and does not require a shared mutex object.
class FileLock {
  private:
    std::string _lock_path;
    int _lock = -1;

 public:
  explicit FileLock(const std::string& name, bool is_full_path = false) : _lock_path(LockPath(name, is_full_path)) {
    _lock = open(_lock_path.c_str(), O_CREAT | O_RDWR, 0666);
    
    if (_lock == -1) {
      if (errno == ENOENT) {
        return;
      }

      throw std::runtime_error("Could not open output lock file: " + _lock_path);
    }
    
    if (flock(_lock, LOCK_EX) == -1) {
      close(_lock);
      throw std::runtime_error("Could not acquire output lock: " + _lock_path);
    }
  }

  FileLock(const FileLock&) = delete;
  FileLock& operator=(const FileLock&) = delete;

  ~FileLock() {
    if (_lock != -1) {
      flock(_lock, LOCK_UN);
      close(_lock);
    }
  }
};

// opened for appending by default: the files collect the results of every module of the program
inline std::ofstream Open(const std::string& name, std::ios_base::openmode mode = std::ios_base::app) {
  std::ofstream stream;
  stream.open(Path(name), std::ios_base::out | mode);
  return stream;
}

// replaces the content of the file with `value`: the counters hand their state over to the next module
template <typename T>
void WriteCounter(const std::string& name, const T& value) {
  FileLock lock(name);
  std::ofstream stream = Open(name, std::ios_base::trunc);
  if (stream.is_open()) {
    stream << value;
  }
}

}  // namespace profiler_files
