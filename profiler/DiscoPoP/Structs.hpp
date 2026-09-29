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

#include "Enums.hpp"
#include "Globals.hpp"

typedef struct Variable_struct {
  string name;
  string type;
  string defLine;
  string isArray;
  bool readAccess;
  bool writeAccess;

  Variable_struct(const Variable_struct &other)
      : name(other.name), type(other.type), defLine(other.defLine), readAccess(other.readAccess),
        writeAccess(other.writeAccess) {}

  Variable_struct(string n, string t, string d, bool readAccess, bool writeAccess)
      : name(n), type(t), defLine(d), readAccess(readAccess), writeAccess(writeAccess) {}

  // We have a set of this struct. The set doesn't know how to order the
  // elements.
  inline bool operator<(const Variable_struct &rhs) const { return name < rhs.name; }

  inline bool operator>(const Variable_struct &rhs) const { return name > rhs.name; }

} Variable;

typedef struct Node_struct {
  string ID;
  nodeTypes type;
  int startLine;
  int endLine;
  BasicBlock *BB;

  // Only for func type
  string name;
  vector<Variable> argumentsList;
  set<int> returnLines;

  vector<Node_struct *> childrenNodes;
  Node_struct *parentNode;

  // isRecursive function (Mo 5.11.2019)
  string recursiveFunctionCall = "";

  Node_struct() {
    ID = to_string(fileID) + ":" + to_string(CUIDCounter++);
    parentNode = NULL;
    BB = NULL;
  }
} Node;

typedef struct CU_struct : Node_struct {

  string BBID; // BasicBlock Id where the CU appears in

  unsigned readDataSize;  // number of bytes read from memory by the cu
  unsigned writeDataSize; // number of bytes written into memory during the cu
  unsigned instructionsCount;

  // basic block id & successor basic blocks for control dependence
  vector<string> successorCUs; // keeps IDs of control dependent CUs
  string basicBlockName;

  set<int> instructionsLineNumbers;
  set<int> readPhaseLineNumbers;
  set<int> writePhaseLineNumbers;
  set<int> returnInstructions;

  set<Variable> localVariableNames;
  set<Variable> globalVariableNames;

  bool performsFileIO;

  // Map to record function call line numbers
  map<int, vector<Node *>> callLineTofunctionMap;
  // Map to record function call instruction ids
  map<int, vector<Instruction*>> callLineToCallInstructionMap;

  CU_struct() {
    type = nodeTypes::cu;
    readDataSize = 0;
    writeDataSize = 0;
    instructionsCount = 0;
    // BB = NULL;
    performsFileIO = false;
  }

  void removeCU() {
    CUIDCounter--; // if a CU does not contain any instruction, e.g. entry
                   // basic blocks, then remove it.
  }

} CU;

struct instr_info_t {
  std::string var_name_;
  std::string var_type_;
  int loop_line_nr_;
  int file_id_;
  llvm::StoreInst *store_inst_;
  llvm::LoadInst *load_inst_;
  char operation_ = ' ';
};

struct loop_info_t {
  unsigned int line_nr_;
  int file_id_;
  llvm::Instruction *first_body_instr_;
  std::string start_line;
  std::string end_line;
  std::string function_name;
  int loop_id;
};
