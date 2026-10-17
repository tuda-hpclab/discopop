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

void DiscoPoP::CreateCus(Region* top_region, std::set<std::string>& global_variables_set, std::vector<CU*>& cu_vector,
                         std::map<std::string, std::vector<CU*>>& bb_id_to_cu_ids_map, Node* root, LoopInfo& li,
                         ModuleAnalysisManager& mam) {
  const DataLayout* dl = &this_module_->getDataLayout();  // used to get data size of variables,
  // pointers, structs etc.
  Node* current_node = root;
  CU* cu;
  LID lid;
  std::string var_name;
  bool is_global_var = false;
  std::string var_type;
  std::set<std::string> suspicious_variables;
  std::string basic_block_name;

  std::map<Loop*, Node*> loop_to_node_map;

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
        cu->instructions_line_numbers.insert(lid);
        cu->instructions_count++;
        // find return instructions
        if (isa<ReturnInst>(instruction)) {
          cu->return_instructions.insert(lid);
        } else if (isa<BranchInst>(instruction)) {
          // find branches to return instructions, i.e. return statements
          if ((cast<BranchInst>(instruction))->isUnconditional()) {
            if ((cast<BranchInst>(instruction))->getNumSuccessors() == 1) {
              BasicBlock* successor_bb = (cast<BranchInst>(instruction))->getSuccessor(0);
              for (BasicBlock::iterator inner_instruction = successor_bb->begin();
                   inner_instruction != successor_bb->end(); ++inner_instruction) {
                if (isa<ReturnInst>(inner_instruction)) {
                  cu->return_instructions.insert(lid);
                  break;
                }
              }
            }
          }
        }
        if (isa<StoreInst>(instruction)) {
          // get size of data written into memory by this store instruction
          Value* operand = instruction->getOperand(1);
          Type* ty = operand->getType();
          const unsigned u = dl->getTypeSizeInBits(ty);
          cu->write_data_size += u;
          var_name = DetermineVariableNameStatic(&*instruction, is_global_var, false, "");
          var_type = DetermineVariableType(&*instruction);
          suspicious_variables.insert(var_name);
          if (lid > 0) {
            cu->write_phase_line_numbers.insert(lid);
          }
        } else if (isa<LoadInst>(instruction)) {
          // get size of data read from memory by this load instruction
          Type* ty = instruction->getType();
          const unsigned u = dl->getTypeSizeInBits(ty);
          cu->read_data_size += u;
          var_name = DetermineVariableNameStatic(&*instruction, is_global_var, false, "");
          if (suspicious_variables.count(var_name)) {
            // VIOLATION OF CAUTIOUS PROPERTY
            // it is a load instruction which read the value of a global
            // variable.
            // This global variable has already been stored previously.
            // A new CU should be created here.
            cu->read_phase_line_numbers.erase(lid);
            cu->write_phase_line_numbers.erase(lid);
            cu->instructions_line_numbers.erase(lid);
            cu->instructions_count--;
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
            CU* temp = cu;  // keep current CU to make a reference to the successor CU
            cu = new CU;

            cu->bb_id = bb->getName().str();
            cu->bb = *bb;

            current_node->children_nodes.push_back(cu);
            temp->successor_cus.push_back(cu->id);
            bb_id_to_cu_ids_map[bb->getName().str()].push_back(cu);
            if (lid > 0) {
              cu->read_phase_line_numbers.insert(lid);
              cu->instructions_line_numbers.insert(lid);
            }
          } else {
            if (global_variables_set.count(var_name) || program_global_variables_set_.count(var_name)) {
              if (lid > 0) {
                cu->read_phase_line_numbers.insert(lid);
              }
            }
          }
        } else if (isa<CallInst>(instruction) || isa<InvokeInst>(instruction)) {
          // allow only a single function call per CU
          // create new CU if the old one contains any instruction
          if ((!cu->read_phase_line_numbers.empty()) || (!cu->write_phase_line_numbers.empty()) ||
              (!cu->return_instructions.empty())) {
            cu->start_line = *(cu->instructions_line_numbers.begin());
            cu->end_line = *(cu->instructions_line_numbers.rbegin());

            cu->basic_block_name = basic_block_name;
            cu_vector.push_back(cu);
            suspicious_variables.clear();
            CU* temp = cu;  // keep current CU to make a reference to the successor CU
            cu = new CU;

            cu->bb_id = bb->getName().str();
            cu->bb = *bb;

            current_node->children_nodes.push_back(cu);
            temp->successor_cus.push_back(cu->id);
            bb_id_to_cu_ids_map[bb->getName().str()].push_back(cu);
          }

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
      }
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
          // locate the CU where this function call belongs
          for (auto i : bb_cus_vector) {
            LID const lid = dputil::GetLid(&*instruction, file_id);
            if (lid >= i->start_line && lid <= i->end_line) {
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
