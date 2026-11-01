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

// Holds an exclusive lock for the lifetime of a single output operation. The lock is
// process-wide through the kernel and does not require a shared mutex object.
class FileLock {
 public:
  explicit FileLock(const std::string& name, bool is_full_path = false)
      : lock_path_((is_full_path ? name : Path(name)) + ".lock") {
    lock_fd_ = open(lock_path_.c_str(), O_CREAT | O_RDWR, 0666);
    if (lock_fd_ == -1) {
      throw std::runtime_error("Could not open output lock file: " + lock_path_);
    }
    if (flock(lock_fd_, LOCK_EX) == -1) {
      close(lock_fd_);
      throw std::runtime_error("Could not acquire output lock: " + lock_path_);
    }
  }

  FileLock(const FileLock&) = delete;
  FileLock& operator=(const FileLock&) = delete;

  ~FileLock() {
    if (lock_fd_ != -1) {
      flock(lock_fd_, LOCK_UN);
      close(lock_fd_);
    }
  }

 private:
  std::string lock_path_;
  int lock_fd_ = -1;
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
