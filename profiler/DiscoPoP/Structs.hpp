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

#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include "llvm/Analysis/LoopInfo.h"
#include "llvm/IR/BasicBlock.h"
#include "llvm/IR/Instruction.h"
#include "llvm/IR/Instructions.h"

#include "Enums.hpp"
#include "Globals.hpp"
#include "lid_constants.hpp"

// the identity of a loop in the output of the pass, as written to loopstate_positions.txt: the id of its
// loop node in Data.xml and its start location (file_id:line)
struct LoopIdentity {
  std::string pet_node_id;
  std::string start_location;
};

struct Variable {
  std::string name;
  std::string type;
  std::string def_line;
  std::string is_array;
  bool read_access;
  bool write_access;

  Variable(const Variable& other)
      : name(other.name),
        type(other.type),
        def_line(other.def_line),
        read_access(other.read_access),
        write_access(other.write_access) {}

  Variable(std::string n, std::string t, std::string d, bool read_access, bool write_access)
      : name(std::move(n)),
        type(std::move(t)),
        def_line(std::move(d)),
        read_access(read_access),
        write_access(write_access) {}

  // We have a set of this struct. The set doesn't know how to order the
  // elements.
  inline bool operator<(const Variable& rhs) const { return name < rhs.name; }

  inline bool operator>(const Variable& rhs) const { return name > rhs.name; }
};

struct Node {
  std::string id;
  NodeTypes type;
  LID start_line;
  LID end_line;
  llvm::BasicBlock* bb;

  // Only for func type
  std::string name;
  std::vector<Variable> arguments_list;
  std::set<LID> return_lines;

  std::vector<Node*> children_nodes;
  Node* parent_node;

  // isRecursive function (Mo 5.11.2019)
  std::string recursive_function_call = "";

  Node() {
    id = std::to_string(file_id) + ":" + std::to_string(cu_id_counter++);
    parent_node = nullptr;
    bb = nullptr;
  }
};

struct CU : Node {
  std::string bb_id;  // BasicBlock Id where the CU appears in

  unsigned read_data_size;   // number of bytes read from memory by the cu
  unsigned write_data_size;  // number of bytes written into memory during the cu
  unsigned instructions_count;

  // basic block id & successor basic blocks for control dependence
  std::vector<std::string> successor_cus;  // keeps IDs of control dependent CUs
  std::string basic_block_name;

  std::set<LID> instructions_line_numbers;
  std::set<LID> read_phase_line_numbers;
  std::set<LID> write_phase_line_numbers;
  std::set<LID> return_instructions;

  std::set<Variable> local_variable_names;
  std::set<Variable> global_variable_names;

  bool performs_file_io;

  // Map to record function call line numbers
  std::map<LID, std::vector<Node*>> call_line_to_function_map;
  // Map to record function call instruction ids
  std::map<LID, std::vector<llvm::Instruction*>> call_line_to_call_instruction_map;

  CU() {
    type = NodeTypes::kCu;
    read_data_size = 0;
    write_data_size = 0;
    instructions_count = 0;
    // BB = NULL;
    performs_file_io = false;
  }

  void RemoveCu() {
    cu_id_counter--;  // if a CU does not contain any instruction, e.g. entry
                      // basic blocks, then remove it.
  }
};

struct InstrInfoT {
  std::string var_name;
  std::string var_type;
  int loop_line_nr;
  int file_id;
  llvm::StoreInst* store_inst;
  llvm::LoadInst* load_inst;
  char operation = ' ';
};

struct LoopInfoT {
  unsigned int line_nr;
  int file_id;
  llvm::Instruction* first_body_instr;
  std::string start_line;
  std::string end_line;
  std::string function_name;
  int loop_id;
};

// The CU graph of one function: built by DiscoPoP::buildCUGraph, written to Data.xml by
// DiscoPoP::writeCUGraph once the function is instrumented (see DiscoPoP::runOnFunction).
struct FunctionCUGraph {
  Node* root = nullptr;  // the function node; like the loop nodes, never freed
  std::vector<CU*> cus;  // freed by writeCUGraph
  std::map<std::string, std::vector<CU*>> bb_id_to_cus;
  // variables which appear in more than one basic block
  std::set<std::string> global_variables;
  // id of the loop node in Data.xml per llvm::Loop (read by CFA for loopstate_positions.txt)
  std::map<llvm::Loop*, std::string> loop_to_pet_node_id;
};
