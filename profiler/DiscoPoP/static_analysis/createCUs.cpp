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

#include <map>
#include <set>
#include <string>
#include <vector>

#include "DiscoPoP.hpp"

using llvm::BasicBlock;
using llvm::BranchInst;
using llvm::CallBase;
using llvm::CallInst;
using llvm::cast;
using llvm::DataLayout;
using llvm::DebugLoc;
using llvm::DILocalScope;
using llvm::Function;
using llvm::InvokeInst;
using llvm::isa;
using llvm::LoadInst;
using llvm::Loop;
using llvm::LoopInfo;
using llvm::ModuleAnalysisManager;
using llvm::raw_string_ostream;
using llvm::Region;
using llvm::ReturnInst;
using llvm::StoreInst;
using llvm::Type;
using llvm::Value;

namespace {
// The head of the statement a call belongs to: the trailing instructions of a CU that evaluate the operands of the
// call. They follow the last store, call or terminator of the CU (the end of the statement before) and are not on a
// line before the call's: the arguments of a call continued on the next lines come before the call, but have later
// lines. Returns the position of the first one: the number of instructions if there is no head, 0 if the CU consists of
// nothing else.
size_t StatementHeadStart(const std::vector<llvm::Instruction*>& instructions, llvm::Instruction* call, int file_id) {
  LID const call_lid = dputil::GetLid(call, file_id);
  size_t start = instructions.size();
  while (start > 0) {
    llvm::Instruction* previous = instructions[start - 1];
    if (dputil::GetLid(previous, file_id) < call_lid || isa<StoreInst>(previous) || isa<CallBase>(previous) ||
        previous->isTerminator()) {
      break;
    }
    --start;
  }
  return start;
}
}  // namespace

void DiscoPoP::CreateCus(Region* top_region, std::set<std::string>& global_variables_set, std::vector<CU*>& cu_vector,
                         std::map<std::string, std::vector<CU*>>& bb_id_to_cu_ids_map, Node* root, LoopInfo& li,
                         ModuleAnalysisManager& mam) {
  const DataLayout* dl = &this_module_->getDataLayout();  // used to get data size of variables,
  // pointers, structs etc.
  Node* current_node = root;
  CU* cu;
  LID lid;
  bool is_global_var = false;
  std::set<std::string> suspicious_variables;
  std::string basic_block_name;

  std::map<Loop*, Node*> loop_to_node_map;

  // loads that start a CU because of a violation of the cautious property: they count as its read phase
  std::set<llvm::Instruction*> cautious_loads;

  // the data of a CU that one instruction contributes
  auto account = [&](CU* c, llvm::Instruction* i) {
    LID const l = dputil::GetLid(i, file_id);
    if (l <= 0) {
      return;
    }
    c->instructions_line_numbers.insert(l);
    c->instructions_count++;
    // find return instructions
    if (isa<ReturnInst>(i)) {
      c->return_instructions.insert(l);
    } else if (isa<BranchInst>(i)) {
      // find branches to return instructions, i.e. return statements
      if ((cast<BranchInst>(i))->isUnconditional()) {
        if ((cast<BranchInst>(i))->getNumSuccessors() == 1) {
          BasicBlock* successor_bb = (cast<BranchInst>(i))->getSuccessor(0);
          for (BasicBlock::iterator inner_instruction = successor_bb->begin(); inner_instruction != successor_bb->end();
               ++inner_instruction) {
            if (isa<ReturnInst>(inner_instruction)) {
              c->return_instructions.insert(l);
              break;
            }
          }
        }
      }
    }
    if (isa<StoreInst>(i)) {
      // size of data written into memory by this store instruction
      const unsigned u = dl->getTypeSizeInBits(i->getOperand(1)->getType());
      c->write_data_size += u;
      c->write_phase_line_numbers.insert(l);
    } else if (isa<LoadInst>(i)) {
      // size of data read from memory by this load instruction
      const unsigned u = dl->getTypeSizeInBits(i->getType());
      c->read_data_size += u;
      const std::string name = DetermineVariableNameStatic(i, is_global_var, false, "");
      if (cautious_loads.count(i) || global_variables_set.count(name) || program_global_variables_set_.count(name)) {
        c->read_phase_line_numbers.insert(l);
      }
    }
  };

  // recompute the data of a CU from its instructions, after instructions were taken out
  auto rebuild = [&](CU* c) {
    c->instructions_line_numbers.clear();
    c->read_phase_line_numbers.clear();
    c->write_phase_line_numbers.clear();
    c->return_instructions.clear();
    c->instructions_count = 0;
    c->read_data_size = 0;
    c->write_data_size = 0;
    for (llvm::Instruction* i : c->instructions) {
      account(c, i);
    }
  };

  for (Region::block_iterator bb = top_region->block_begin(); bb != top_region->block_end(); ++bb) {
    // Get the closest loop where bb lives in.
    // (loop == NULL) if bb is not in any loop.
    Loop* loop = li.getLoopFor(*bb);
    if (loop) {
      // if bb is in a loop and if we have already created a node for that loop,
      // assign it to currentNode.
      if (loop_to_node_map.find(loop) != loop_to_node_map.end()) {
        current_node = loop_to_node_map[loop];
      } else {
        // else, create a new Node for the loop, add it as children of currentNode
        // and add it to the map.
        Node* n = new Node;
        n->type = NodeTypes::kLoop;
        n->parent_node = current_node;
        current_node->children_nodes.push_back(n);

        loop_to_node_map[loop] = n;
        current_node = n;
      }
    } else {
      // end of loops. go to the parent of the loop. may have to jump several
      // nodes in case of nested loops
      for (std::map<Loop*, Node*>::iterator it = loop_to_node_map.begin(); it != loop_to_node_map.end(); it++) {
        if (it->second == current_node) {  // current node found in loop map jump to its parent.
          current_node = current_node->parent_node;
          it = loop_to_node_map.begin();     // search the whole map again for current node
          if (it->second == current_node) {  // due to it++ we need to check first
            // element of map ourself
            current_node = current_node->parent_node;
          }
        }
      }
    }

    cu = new CU;

    if (bb->getName().size() == 0) {
      bb->setName(cu->id);
    }

    cu->bb_id = bb->getName().str();
    cu->bb = *bb;
    current_node->children_nodes.push_back(cu);
    std::vector<CU*> basic_block_cu_vector;
    basic_block_cu_vector.push_back(cu);
    bb_id_to_cu_ids_map.insert(std::pair<std::string, std::vector<CU*>>(bb->getName(), basic_block_cu_vector));
    DILocalScope* scope_buffer = nullptr;

    // the line of the call of the CU being built, 0 if it has none
    LID call_line = 0;

    // the CU is complete: derive its lines
    auto close_cu = [&](CU* c) {
      if (c->instructions_line_numbers.empty()) {
        c->start_line = -1;
        c->end_line = -1;
      } else {
        c->start_line = *(c->instructions_line_numbers.begin());
        c->end_line = *(c->instructions_line_numbers.rbegin());
      }
      c->basic_block_name = basic_block_name;
      cu_vector.push_back(c);
    };

    // a CU that follows the given one in the basic block
    auto new_cu = [&](CU* previous) {
      suspicious_variables.clear();
      call_line = 0;
      CU* next = new CU;
      next->bb_id = bb->getName().str();
      next->bb = *bb;
      current_node->children_nodes.push_back(next);
      previous->successor_cus.push_back(next->id);
      bb_id_to_cu_ids_map[bb->getName().str()].push_back(next);
      return next;
    };

    for (BasicBlock::iterator instruction = (*bb)->begin(); instruction != (*bb)->end(); ++instruction) {
      // NOTE: 'instruction' --> '&*instruction'
      lid = dputil::GetLid(&*instruction, file_id);
      basic_block_name = bb->getName().str();

      // Do not allow to combine Instructions from different scopes in the
      // source code.
      if ((&*instruction)->getDebugLoc()) {
        if ((&*instruction)->getDebugLoc()->getScope() != scope_buffer) {
          // scopes are not equal

          int scope_is_parent_of_buffer = 0;
          if (scope_buffer) {
            scope_is_parent_of_buffer = (&*instruction)->getDebugLoc()->getScope() == scope_buffer->getScope();
          }

          if (scope_is_parent_of_buffer) {
            // allow a combination of two CU's if the second scope is the parent
            // of the first scope
          } else {
            // create a new CU. Do not allow to combine Instructions from
            // different scopes in the source code.

            // create new CU if the old one contains any instruction
            if ((!cu->read_phase_line_numbers.empty()) || (!cu->write_phase_line_numbers.empty()) ||
                (!cu->return_instructions.empty())) {
              cu->start_line = *(cu->instructions_line_numbers.begin());
              cu->end_line = *(cu->instructions_line_numbers.rbegin());

              cu->basic_block_name = basic_block_name;
              cu_vector.push_back(cu);
              suspicious_variables.clear();
              call_line = 0;
              CU* temp = cu;  // keep current CU to make a reference to the successor CU
              cu = new CU;

              cu->bb_id = bb->getName().str();
              cu->bb = *bb;

              current_node->children_nodes.push_back(cu);
              temp->successor_cus.push_back(cu->id);
              bb_id_to_cu_ids_map[bb->getName().str()].push_back(cu);
            }
          }
          // update scopeBuffer
          scope_buffer = (&*instruction)->getDebugLoc()->getScope();
        }
      }

      if (lid > 0) {
        if (call_line != 0 && lid != call_line) {
          // the statement of the call is complete: the CU ends with it
          close_cu(cu);
          cu = new_cu(cu);
        }
        if (isa<LoadInst>(instruction) &&
            suspicious_variables.count(DetermineVariableNameStatic(&*instruction, is_global_var, false, ""))) {
          // VIOLATION OF CAUTIOUS PROPERTY
          // it is a load instruction which read the value of a variable that has already been stored
          // previously in this CU. A new CU should be created here.
          close_cu(cu);
          cu = new_cu(cu);
          cautious_loads.insert(&*instruction);
        } else if (isa<CallInst>(instruction) || isa<InvokeInst>(instruction)) {
          // allow only a single function call per CU
          // create new CU if the old one contains any instruction
          // the statement of the call is not split: a CU that holds nothing else than its head is the CU of the call
          const size_t head = StatementHeadStart(cu->instructions, &*instruction, file_id);
          if (head > 0 && ((!cu->read_phase_line_numbers.empty()) || (!cu->write_phase_line_numbers.empty()) ||
                           (!cu->return_instructions.empty()))) {
            CU* previous = cu;
            cu = new_cu(cu);
            // the head (the operands) moves along with the call
            if (head < previous->instructions.size()) {
              const std::vector<llvm::Instruction*> moved(previous->instructions.begin() + head,
                                                          previous->instructions.end());
              previous->instructions.resize(head);
              rebuild(previous);
              for (llvm::Instruction* i : moved) {
                cu->instructions.push_back(i);
                account(cu, i);
                if (isa<StoreInst>(i)) {
                  suspicious_variables.insert(DetermineVariableNameStatic(i, is_global_var, false, ""));
                }
              }
            }
            close_cu(previous);
          }
          call_line = lid;

          // get the name of the called function and check if a FileIO function
          // is called
          const std::set<std::string> io_functions{
              "fopen",       "fopen_s",      "freopen",    "freopen_s",      "fclose",    "fflush",     "setbuf",
              "setvbuf",     "fwide",        "fread",      "fwrite",         "fgetc",     "getc",       "fgets",
              "fputc",       "putc",         "fputs",      "getchar",        "gets",      "gets_s",     "putchar",
              "puts",        "ungetc",       "fgetwc",     "getwc",          "fgetws",    "fputwc",     "putwc",
              "fputws",      "getwchar",     "putwchar",   "ungetwc",        "scanf",     "fscanf",     "sscanf",
              "scanf_s",     "fscanf_s",     "sscanf_s",   "vscanf",         "vfscanf",   "vsscanf",    "vscanf_s",
              "vfscanf_s",   "vsscanf_s",    "printf",     "fprintf",        "sprintf",   "snprintf",   "printf_s",
              "fprintf_s",   "sprintf_s",    "snprintf_s", "vprintf",        "vfprintf",  "vsprintf",   "vsnprintf",
              "vprintf_s",   "vfprintf_s",   "vsprintf_s", "vsnprintf_s",    "wscanf",    "fwscanf",    "swscanf",
              "wscanf_s",    "fwscanf_s",    "swscanf_s",  "vwscanf",        "vfwscanf",  "vswscanf",   "vwscanf_s",
              "vfwscanf_s",  "vswscanf_s",   "wprintf",    "fwprintf",       "swprintf",  "wprintf_s",  "wprintf_s",
              "swprintf_s",  "snwprintf_s",  "vwprintf",   "vfwprintf",      "vswprintf", "vwprintf_s", "vfwprintf_s",
              "vswprintf_s", "vsnwprintf_s", "ftell",      "fgetpos",        "fseek",     "fsetpos",    "rewind",
              "clearerr",    "feof",         "ferror",     "perror",         "remove",    "rename",     "tmpfile",
              "tmpfile_s",   "tmpnam",       "tmpnam_s",   "__isoc99_fscanf"};

          CallBase* ci = cast<CallBase>(instruction);
          if (ci) {
            if (ci->getCalledFunction()) {
              if (ci->getCalledFunction()->hasName()) {
                if (std::find(io_functions.begin(), io_functions.end(), ci->getCalledFunction()->getName().str()) !=
                    io_functions.end()) {
                  // Called function performs FileIO
                  cu->performs_file_io = true;
                }
              }
            }
          }
        }
        account(cu, &*instruction);
        if (isa<StoreInst>(instruction)) {
          suspicious_variables.insert(DetermineVariableNameStatic(&*instruction, is_global_var, false, ""));
        }
      }
      // after the splits above, cu is the CU the instruction belongs to: a call or a load that
      // violates the cautious property starts a new one
      cu->instructions.push_back(&*instruction);
    }
    if (cu->instructions_line_numbers.empty()) {
      // cu->removeCU();
      cu->start_line = -1;
      cu->end_line = -1;
    } else {
      cu->start_line = *(cu->instructions_line_numbers.begin());
      cu->end_line = *(cu->instructions_line_numbers.rbegin());
    }

    cu->basic_block_name = basic_block_name;
    cu_vector.push_back(cu);
    suspicious_variables.clear();

    // check for call instructions in current basic block
    for (BasicBlock::iterator instruction = (*bb)->begin(); instruction != (*bb)->end(); ++instruction) {
      // Note: Don't create nodes for library functions (c++/llvm).
      LID const lid = dputil::GetLid(&*instruction, file_id);
      if (lid > 0) {
        if (isa<CallInst>(instruction) || isa<InvokeInst>(instruction)) {
          Function* f = nullptr;

          if (isa<CallInst>(instruction)) {
            CallInst* ci = cast<CallInst>(instruction);
            f = ci->getCalledFunction();
          } else if (isa<InvokeInst>(instruction)) {
            InvokeInst* ci = cast<InvokeInst>(instruction);
            f = ci->getCalledFunction();
          }

          std::string lid;
          if (f) {
            bool external_function = true;
            for (Function::iterator fi = f->begin(), fe = f->end(); fi != fe; ++fi) {
              external_function = false;
              auto temp_bi = fi->begin();
              if (DebugLoc dl = temp_bi->getDebugLoc()) {
                lid = std::to_string(dl->getLine());
              } else {
                if (temp_bi->getFunction()->getSubprogram()) {
                  lid = std::to_string(temp_bi->getFunction()->getSubprogram()->getLine());
                } else {
                  lid = "LineNotFound";
                }
              }
              break;
            }
            if (external_function) {
              continue;
            }
          } else {
            lid = "LineNotFound";
          }

          Node* n = new Node;
          n->type = NodeTypes::kDummy;
          // For ordinary function calls, F has a name.
          // However, sometimes the function being called
          // in IR is encapsulated by "bitcast()" due to
          // the way of compiling and linking. In this way,
          // getCalledFunction() method returns NULL.
          // Also, getName() returns NULL if this is an indirect function call.
          if (f) {
            n->name = f->getName().str();

            // @Zia: This for loop appeared after the else part. For some
            // function calls, the value of f is null. I guess that is why you
            // have checked if f is not null here. Anyway, I (Mohammad) had to
            // bring the for loop inside to avoid the segmentation fault. If you
            // think it is not appropriate, find a solution for it. 14.2.2016
            for (Function::arg_iterator it = f->arg_begin(); it != f->arg_end(); it++) {
              std::string type_str;
              raw_string_ostream rso(type_str);
              (it->getType())->print(rso);
              const Variable v(std::string(it->getName()), rso.str(), lid, true, true);
              n->arguments_list.push_back(v);
            }
          } else {  // get name of the indirect function which is called
            Value* v = (cast<CallBase>(instruction))->getCalledOperand();
            Value* sv = v->stripPointerCasts();
            n->name = sv->getName().str();
          }

          // Recursive functions
          // CallGraphWrapperPass *CGWP = &(getAnalysis<CallGraphWrapperPass>());

          llvm::CallGraph& cg = mam.getResult<llvm::CallGraphAnalysis>(*this_module_);

          // if (isRecursive(*f, CGWP->getCallGraph())) {
          if (IsRecursive(*f, cg)) {
            LID const lid = dputil::GetLid(&*instruction, file_id);
            n->recursive_function_call = n->name + " " + dputil::DecodeLid(lid) + ",";
          }

          const std::vector<CU*> bb_cus_vector = bb_id_to_cu_ids_map[bb->getName().str()];
          // locate the CU where this function call belongs: the one that holds the call instruction
          for (auto i : bb_cus_vector) {
            if (std::find(i->instructions.begin(), i->instructions.end(), &*instruction) != i->instructions.end()) {
              LID const lid = dputil::GetLid(&*instruction, file_id);
              i->instructions_line_numbers.insert(lid);
              i->children_nodes.push_back(n);
              i->call_line_to_function_map[lid].push_back(n);
              i->call_line_to_call_instruction_map[lid].push_back(&(*instruction));
              break;
            }
          }
        }
      }
    }
  }
}
