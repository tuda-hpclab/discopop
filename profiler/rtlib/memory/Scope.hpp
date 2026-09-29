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

#include "../DPTypes.hpp"

#include <algorithm>
#include <iostream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace __dp {

// Data structure to store information on a single source code scope
struct Scope {
  Scope(unsigned long id) : scope_id(id) {}

  void registerStackRead(ADDR address, LID debug_lid, const char *debug_var) {
    if (!(first_written.find(address) != first_written.end())) {
      first_read.insert(address);
    }
  }

  void registerStackWrite(ADDR address, LID debug_lid, const char *debug_var) {
    if (!(first_read.find(address) != first_read.end())) {
      first_written.insert(address);
    }
  }

  unsigned long get_id() const noexcept { return scope_id; }

  const std::unordered_set<ADDR> &get_first_read() const noexcept { return first_read; }

  const std::unordered_set<ADDR> &get_first_write() const noexcept { return first_written; }

private:
  unsigned long scope_id;
  std::unordered_set<ADDR> first_read;
  std::unordered_set<ADDR> first_written;
};

// Data structure for stack access management in scopes
struct ScopeManager {
  const Scope &getCurrentScope() { return scopeStack.back(); }

  std::size_t number_open_scopes() const noexcept { return scopeStack.size(); }

  void enterScope(std::string type, LID debug_lid) { scopeStack.push_back(Scope(next_scope_id++)); }

  void leaveScope(std::string type, LID debug_lid) { scopeStack.pop_back(); }

  void registerStackRead(ADDR address, LID debug_lid, const char *debug_var) {
    scopeStack.back().registerStackRead(address, debug_lid, debug_var);
    addrToLastAccessScopeID[address] = scopeStack.back().get_id();
  }

  void registerStackWrite(ADDR address, LID debug_lid, const char *debug_var) {
    scopeStack.back().registerStackWrite(address, debug_lid, debug_var);
    addrToLastAccessScopeID[address] = scopeStack.back().get_id();
  }

  bool isOwnedByScope(ADDR addr, bool currentAccessIsWrite) {
    // currentAccessIsWrite is used in case no access to addr has been

    // check for first_writes in previous scopes (i.e.: search for the "owner"
    // of the stack variable)
    int idx = 0;
    for (auto scope : scopeStack) {
      if (scope.get_first_write().count(addr) > 0) {
        if (idx == scopeStack.size() - 1) {
          return true;
        } else {
          // scope variable "belongs" to a parent scope.
          // Thus, it may not be considered a scope variable for the inner
          // scope.
          return false;
        }
      }
      idx++;
    }

    // registered already
    if (scopeStack.back().get_first_write().count(addr) > 0) {
      return true;
    }

    if (scopeStack.back().get_first_read().count(addr) > 0) {
      return false;
    }

    // no access to addr registered in the current scope
    if (currentAccessIsWrite) {
      return true;
    }

    return false;
  }

  bool positiveScopeChangeOccuredSinceLastAccess(ADDR addr) {
    // positive Scope change --> current scope id higher than the id during the
    // last access
    if (!addrToLastAccessScopeID[addr]) {
      return true;
    }

    if (addrToLastAccessScopeID[addr] < scopeStack.back().get_id()) {
      return true;
    }

    return false;
  }

private:
  std::vector<Scope> scopeStack;
  unsigned long next_scope_id = 1; // 0 marks invalid in addrToLastAccessScopeID

  std::unordered_map<ADDR, unsigned long> addrToLastAccessScopeID;
};

// Hopefully faster version

struct Scope2 {
  // Can use vectors for a speed up when dealing with < 100 addresses
  Scope2(const unsigned long id) : scope_id(id) {
    first_read.reserve(64);
    first_written.reserve(64);
  }

  void registerStackRead(ADDR address, LID debug_lid, char *debug_var) {
    const auto not_found = first_written.find(address) == first_written.end();
    if (not_found) {
      first_read.insert(address);
    }
  }

  void registerStackWrite(ADDR address, LID debug_lid, char *debug_var) {
    const auto not_found = first_read.find(address) == first_read.end();
    if (not_found) {
      first_written.insert(address);
    }
  }

  unsigned long get_id() const noexcept { return scope_id; }

  const hashset<ADDR> &get_first_read() const noexcept { return first_read; }

  const hashset<ADDR> &get_first_write() const noexcept { return first_written; }

private:
  unsigned long scope_id;
  hashset<ADDR> first_read;
  hashset<ADDR> first_written;
};

struct ScopeManager2 {
  ScopeManager2() {
    scopeStack.reserve(32);
    addrToLastAccessScopeID.reserve(1024);
  }

  const Scope2 &getCurrentScope() const noexcept { return scopeStack.back(); }

  std::size_t number_open_scopes() const noexcept { return scopeStack.size(); }

  void enterScope(const char *type, LID debug_lid) { scopeStack.emplace_back(next_scope_id++); }

  void leaveScope(const char *type, LID debug_lid) { scopeStack.pop_back(); }

  void registerStackRead(ADDR address, LID debug_lid, char *debug_var) {
    auto &current_scope = scopeStack.back();

    current_scope.registerStackRead(address, debug_lid, debug_var);
    addrToLastAccessScopeID[address] = current_scope.get_id();
  }

  void registerStackWrite(ADDR address, LID debug_lid, char *debug_var) {
    auto &current_scope = scopeStack.back();

    current_scope.registerStackWrite(address, debug_lid, debug_var);
    addrToLastAccessScopeID[address] = current_scope.get_id();
  }

  bool isOwnedByScope(ADDR addr, bool currentAccessIsWrite) {
    // currentAccessIsWrite is used in case no access to addr has been

    // check for first_writes in previous scopes (i.e.: search for the "owner"
    // of the stack variable)
    int idx = 0;
    for (auto scope : scopeStack) {
      if (scope.get_first_write().count(addr) > 0) {
        if (idx == scopeStack.size() - 1) {
          return true;
        } else {
          // scope variable "belongs" to a parent scope.
          // Thus, it may not be considered a scope variable for the inner
          // scope.
          return false;
        }
      }
      idx++;
    }

    // registered already
    if (scopeStack.back().get_first_write().count(addr) > 0) {
      return true;
    }

    if (scopeStack.back().get_first_read().count(addr) > 0) {
      return false;
    }

    // no access to addr registered in the current scope
    if (currentAccessIsWrite) {
      return true;
    }

    return false;
  }

  bool positiveScopeChangeOccuredSinceLastAccess(const ADDR addr) noexcept {
    const auto iterator = addrToLastAccessScopeID.find(addr);
    if (iterator == addrToLastAccessScopeID.end()) {
      return true;
    }

    const auto val = iterator->second;
    return val < scopeStack.back().get_id();
  }

private:
  unsigned long next_scope_id = 1;

  std::vector<Scope2> scopeStack;
  hashmap<ADDR, unsigned long> addrToLastAccessScopeID;
};

} // namespace __dp
