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

#include "hybrid_analysis/HybridAnalysis.hpp"

#include <cstdint>
#include <fstream>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "llvm/IR/Dominators.h"
#include "llvm/IR/IRBuilder.h"
#include "llvm/IR/IntrinsicInst.h"
#include "llvm/Transforms/Utils/ModuleUtils.h"

#include "Globals.hpp"
#include "hybrid_analysis/InstructionCFG.hpp"
#include "hybrid_analysis/InstructionDG.hpp"
#include "llvm_compat.hpp"
#include "utils/profiler_files.hpp"

using hybrid_analysis::HybridAnalysis;
using llvm::AllocaInst;
using llvm::appendToGlobalCtors;
using llvm::ArrayRef;
using llvm::BasicBlock;
using llvm::CallInst;
using llvm::ConstantInt;
using llvm::DbgInfoIntrinsic;
using llvm::DebugLoc;
using llvm::dyn_cast;
using llvm::errs;
using llvm::Function;
using llvm::FunctionAnalysisManagerModuleProxy;
using llvm::FunctionType;
using llvm::GlobalValue;
using llvm::Instruction;
using llvm::IRBuilder;
using llvm::isa;
using llvm::LoadInst;
using llvm::Module;
using llvm::ModuleAnalysisManager;
using llvm::PointerType;
using llvm::ReturnInst;
using llvm::StoreInst;
using llvm::StringRef;
using llvm::Twine;
using llvm::Type;
using llvm::Value;

constexpr bool kDumpToDot = false;
constexpr bool kDpHybridDebug = false;

// reads a counter persisted by an earlier module (see HybridAnalysis::finalize)
template <typename T>
static void ReadCounter(const std::string& name, T& value) {
  std::string counter_file(dputil::GetEnvOrDefault("DOT_DISCOPOP_PROFILER", ".discopop/profiler"));
  counter_file += "/" + name;
  if (dputil::FileExists(counter_file)) {
    std::fstream in_counter(counter_file, std::ios_base::in);
    in_counter >> value;
    in_counter.close();
  }
}

// Returns the instruction before which the hybrid analysis reports an execution
// of BB (__dp_report_bb / __dp_report_bb_pair) or records it in a semaphore
// (__dp_bb_state): the terminator, but in front of the instrumentation of a
// call or return right before it (__dp_call before an invoke, __dp_func_exit /
// __dp_finalize before a return), as these change the callpath state and the
// report has to see the state of BB's accesses.
static Instruction* GetHybridReportInsertionPoint(BasicBlock* bb) {
  Instruction* insertion_point = bb->getTerminator();
  for (Instruction* prev = insertion_point->getPrevNode(); prev; prev = prev->getPrevNode()) {
    if (isa<DbgInfoIntrinsic>(prev)) {
      continue;
    }
    CallInst* call = dyn_cast<CallInst>(prev);
    if (!call || !call->getCalledFunction()) {
      break;
    }
    StringRef fn = call->getCalledFunction()->getName();
    if (fn != "__dp_call" && fn != "__dp_func_exit" && fn != "__dp_finalize") {
      break;
    }
    insertion_point = prev;
  }
  return insertion_point;
}

// DPInstrumentationOmission
HybridAnalysis::HybridAnalysis(Module& m) {
  Type* void_type = Type::getVoidTy(m.getContext());
  int32_ = Type::getInt32Ty(m.getContext());

  bb_dep_count = 0;
  ReadCounter("DP_BBDepCounter.txt", bb_dep_count);

  next_free_static_memory_region_id_ = 0;
  ReadCounter("DP_StaticMemoryRegionIDCounter.txt", next_free_static_memory_region_id_);

  report_bb_ = m.getOrInsertFunction("__dp_report_bb", void_type, int32_);
  report_bb_pair_ = m.getOrInsertFunction("__dp_report_bb_pair", void_type, int32_, int32_);
  bb_state_ = m.getOrInsertFunction("__dp_bb_state", int32_);
  vnf_ = std::make_unique<dputil::VariableNameFinder>(m);
}

bool HybridAnalysis::AnalyzeFunction(Function& f, ModuleAnalysisManager& mam,
                                     std::map<Instruction*, CallInst*>& inserted_access_callbacks,
                                     std::map<std::string, std::string>& true_var_names_from_metadata_map) {
  if (f.getInstructionCount() == 0) {
    return false;
  }

// Enable / Disable hybrid profiling
#ifndef DP_HYBRID_PROFILING
#define DP_HYBRID_PROFILING 1
#endif

#if DP_HYBRID_PROFILING == 0
  return true;
#endif
  /////

  if (kDpHybridDebug) {
    errs() << "\n---------- Omission Analysis on " << f.getName() << " ----------\n";
  }

  DebugLoc dl;
  Value* v;

  std::set<Instruction*> omittable_instructions;

  std::set<Value*> statically_predictable_values;
  // Get local values (variables)
  for (Instruction& i : f.getEntryBlock()) {
    if (AllocaInst* ai = dyn_cast<AllocaInst>(&i)) {
      statically_predictable_values.insert(ai);
    }
  }
  for (BasicBlock& bb : f) {
    for (Instruction& i : bb) {
      // Remove from staticallyPredictableValues those which are passed to
      // other functions (by ref/ptr)
      if (CallInst* call_inst = dyn_cast<CallInst>(&i)) {
        if (call_inst->getCalledFunction()) {
          for (uint i = 0; i < call_inst->getNumOperands() - 1; ++i) {
            v = call_inst->getArgOperand(i);
            const std::set<Value*>::iterator it = statically_predictable_values.find(v);
            if (it != statically_predictable_values.end()) {
              statically_predictable_values.erase(v);
              if (kDpHybridDebug) {
                errs() << vnf_->GetVarName(v) << "\n";
              }
            }
          }
        }
      }
      // Remove values from locals if dereferenced
      if (isa<StoreInst>(i)) {
        v = i.getOperand(0);
        std::set<Value*> to_be_removed;
        for (Value* w : statically_predictable_values) {
          if (w == v) {
            to_be_removed.insert(v);
          }
        }
        for (Value* w : to_be_removed) {
          statically_predictable_values.erase(w);
        }
      }
    }
  }

  // assign static memory region IDs to statically predictable values and thus
  // dependencies
  std::unordered_map<std::string, std::pair<std::string, std::string>>
      static_value_name_to_mem_reg_id_map;  // <SSA variable name>: (original variable
                                            // name, statically assigned MemReg ID)
  std::int64_t next_id;
  std::string llvm_ir_var_name;
  std::string original_var_name;
  std::string static_memory_region_id;
  for (auto v : statically_predictable_values) {
    next_id = next_free_static_memory_region_id_++;
    llvm_ir_var_name = vnf_->GetVarName(v);
    // Note: Using variables names as keys is only possible at this point,
    // since the map is created for each function individually. Thus, we can
    // rely on the SSA properties of LLVM IR and can assume that e.g. scoping
    // is handled by LLVM and destinct variable names are introduced.
    original_var_name = true_var_names_from_metadata_map[llvm_ir_var_name];
    if (original_var_name.size() == 0) {
      // no original variable name could be identified using the available
      // metadata. Fall back to the LLVM IR name of the value.
      original_var_name = llvm_ir_var_name;
    }
    static_memory_region_id = "S" + std::to_string(next_id);
    static_value_name_to_mem_reg_id_map[llvm_ir_var_name] =
        std::pair<std::string, std::string>(original_var_name, static_memory_region_id);
  }

  if (kDpHybridDebug) {
    errs() << "--- Local Values ---\n";
    for (auto v : statically_predictable_values) {
      errs() << vnf_->GetVarName(v) << "\n";
    }
  }

  // Perform the SPA dependence analysis
  std::int32_t fid;
  dputil::DetermineFileId(f, fid);
  // The dependencies are reported per execution of the basic block holding
  // their sinks, together with the callpath states of their ends, so that
  // they can be attributed to calling contexts and loop iterations like the
  // dynamically profiled ones. The callpath state only changes at the
  // beginning of a basic block (loop entry, iteration, exit) and around calls,
  // which restore it on their return; hence the state at the end of a basic
  // block is the one of all of its accesses.
  // sink BB -> dependencies whose source lies in the same execution of the
  // sink BB, before the sink, or which have no source instruction (INIT):
  // both ends get the state of the sink BB's execution
  std::map<BasicBlock*, std::set<std::string>> conditional_bb_dep_map;
  // source BB -> variable -> sink BB -> dependencies whose source lies in an
  // earlier execution of the source BB (or of the sink BB itself). Per source
  // BB and variable, a per-invocation semaphore holds the state of the most
  // recent execution of the source BB, and is reset when another BB writes
  // the variable: that write replaces the source, so the dependency does not
  // exist anymore (e.g. "j = 0" before an inner loop ends the dependency of
  // the loop's header on the "j++" of its previous execution). The source
  // gets the semaphore's state, the sink the state of the sink BB's
  // execution. Only reported while the semaphore is set.
  std::map<BasicBlock*, std::map<Value*, std::map<BasicBlock*, std::set<std::string>>>> conditional_bb_pair_dep_map;

  // auto &DT = getAnalysis<DominatorTreeWrapperPass>(F).getDomTree();
  llvm::FunctionAnalysisManager& fam = mam.getResult<FunctionAnalysisManagerModuleProxy>(*f.getParent()).getManager();
  // llvm::LoopInfo &LI = fam.getResult<llvm::LoopAnalysis>(F);
  const llvm::DominatorTree& dt = fam.getResult<llvm::DominatorTreeAnalysis>(f);

  InstructionCFG cfg(vnf_.get(), f);
  InstructionDG dg(vnf_.get(), &cfg, fid);

  // collect init instruction to prevent false-positive WAW Dependences due to allocations in loops,
  // which will be moved to the function entry
  std::map<std::string, std::set<std::string>> line_to_initialized_vars_map;
  for (auto edge : dg.GetEdges()) {
    if (dg.EdgeIsInit(edge)) {
      const std::string init_line = dg.GetInitEdgeInstructionLine(edge);
      const std::string var_identifier = dg.GetValueNameAndMemRegIdFromEdge(edge, static_value_name_to_mem_reg_id_map);

      if (line_to_initialized_vars_map.find(init_line) == line_to_initialized_vars_map.end()) {
        const std::set<std::string> tmp;
        line_to_initialized_vars_map[init_line] = tmp;
      }
      line_to_initialized_vars_map[init_line].insert(var_identifier);
    }
  }

  for (auto edge : dg.GetEdges()) {
    Instruction* src = edge->GetSrc()->GetItem();
    Instruction* dst = edge->GetDst()->GetItem();

    v = src->getOperand(isa<StoreInst>(src) ? 1 : 0);
    if (isa<AllocaInst>(dst)) {
      v = dyn_cast<Value>(dst);
    }

    if (statically_predictable_values.find(v) == statically_predictable_values.end()) {
      continue;
    }

    if (src != dst && dt.dominates(dst, src) && (isa<AllocaInst>(dst) || dst->getParent() == src->getParent())) {
      if (!conditional_bb_dep_map.count(src->getParent())) {
        const std::set<std::string> tmp;
        conditional_bb_dep_map[src->getParent()] = tmp;
      }
      conditional_bb_dep_map[src->getParent()].insert(
          dg.EdgeToInstructionBasedDpDep(edge, static_value_name_to_mem_reg_id_map));
    } else {
      // Prevent reporting of false-positive WAW Dependencies due to alloca movement from e.g. loops to function entry
      bool insert_dep = true;
      if (dst == src) {  // check if instruciton are the same
        // check if initialization exists in the instruction line
        if (line_to_initialized_vars_map.find(dg.GetInstructionLine(dst)) != line_to_initialized_vars_map.end()) {
          // check if the accessed variable is initialed here
          const std::string var_identifier =
              dg.GetValueNameAndMemRegIdFromEdge(edge, static_value_name_to_mem_reg_id_map);
          if (line_to_initialized_vars_map[dg.GetInstructionLine(dst)].find(var_identifier) !=
              line_to_initialized_vars_map[dg.GetInstructionLine(dst)].end()) {
            // ignore this access as the initialized variable is accessed
            insert_dep = false;
          }
        }
      }

      if (insert_dep) {
        conditional_bb_pair_dep_map[dst->getParent()][v][src->getParent()].insert(
            dg.EdgeToInstructionBasedDpDep(edge, static_value_name_to_mem_reg_id_map));
      }
    }
    omittable_instructions.insert(src);
    omittable_instructions.insert(dst);
  }

  // Omit SPA instructions with no dependences
  for (auto node : dg.GetInstructionNodes()) {
    if (!isa<StoreInst>(node->GetItem()) && !!isa<LoadInst>(node->GetItem())) {
      continue;
    }
    v = node->GetItem()->getOperand(isa<StoreInst>(node->GetItem()) ? 1 : 0);
    if (!dg.GetInEdges(node).size() && !dg.GetOutEdges(node).size() &&
        statically_predictable_values.find(v) != statically_predictable_values.end()) {
      omittable_instructions.insert(node->GetItem());
    }
  }

  // Add observation of execution of single basic blocks
  for (const auto& pair : conditional_bb_dep_map) {
    // Insert call to reportbb
    Instruction* insertion_point = GetHybridReportInsertionPoint(pair.first);
    CallInst::Create(report_bb_, ConstantInt::get(int32_, bb_dep_count), "", insertion_point->getIterator());

    // ---- Insert deps into string ----
    if (bb_dep_count) {
      bb_dep_string_ += "/";
    }
    bool first = true;
    bb_dep_string_ += std::to_string(bb_dep_count) + "=";
    for (const auto& dep : pair.second) {
      if (!first) {
        bb_dep_string_ += ",";
      }
      bb_dep_string_ += dep;
      first = false;
    }
    // ---------------------------------
    ++bb_dep_count;
  }

  // Add observation of in-order execution of pairs of basic blocks
  // the basic blocks writing each variable which is the source of a pair dependency
  std::map<Value*, std::set<BasicBlock*>> writers_of_variable;
  for (auto& source_block : conditional_bb_pair_dep_map) {
    for (auto& variable : source_block.second) {
      writers_of_variable[variable.first];
    }
  }
  for (BasicBlock& bb : f) {
    for (Instruction& i : bb) {
      if (StoreInst* store = dyn_cast<StoreInst>(&i)) {
        auto writers = writers_of_variable.find(store->getPointerOperand());
        if (writers != writers_of_variable.end()) {
          writers->second.insert(&bb);
        }
      }
    }
  }
  // one semaphore per (source BB, variable)
  std::map<std::pair<BasicBlock*, Value*>, AllocaInst*> semaphores;
  for (auto& source_block : conditional_bb_pair_dep_map) {
    for (auto& variable : source_block.second) {
      auto ai = new AllocaInst(int32_, 0, "__dp_bb",
                               llvmcompat::NextInstruction(f.getEntryBlock().getFirstNonPHI())->getIterator());
      new StoreInst(ConstantInt::get(int32_, 0), ai, false, llvmcompat::NextInstruction(ai)->getIterator());
      semaphores[{source_block.first, variable.first}] = ai;
    }
  }
  // sink BB -> (semaphore, dependencies)
  std::map<BasicBlock*, std::vector<std::pair<AllocaInst*, const std::set<std::string>*>>> reports_of_block;
  for (auto& source_block : conditional_bb_pair_dep_map) {
    for (auto& variable : source_block.second) {
      for (auto& sink_block : variable.second) {
        reports_of_block[sink_block.first].push_back(
            {semaphores[{source_block.first, variable.first}], &sink_block.second});
      }
    }
  }
  // At the end of each basic block, in this order: report the pair
  // dependencies whose sinks it holds, reset the semaphores of the variables
  // it writes (of other source BBs), record its own state in its semaphores.
  // Reporting first lets a dependency on an earlier execution of the same
  // block see the state of that execution.
  for (BasicBlock& bb : f) {
    Instruction* insertion_point = GetHybridReportInsertionPoint(&bb);
    auto reports = reports_of_block.find(&bb);
    if (reports != reports_of_block.end()) {
      for (auto& report : reports->second) {
        auto li = new LoadInst(int32_, report.first, Twine(""), false, insertion_point->getIterator());
        CallInst::Create(report_bb_pair_, ArrayRef<Value*>({li, ConstantInt::get(int32_, bb_dep_count)}), "",
                         insertion_point->getIterator());
        // ---- Insert deps into string ----
        if (bb_dep_count) {
          bb_dep_string_ += "/";
        }
        bb_dep_string_ += std::to_string(bb_dep_count);
        bb_dep_string_ += "=";
        bool first = true;
        for (auto& dep : *report.second) {
          if (!first) {
            bb_dep_string_ += ",";
          }
          bb_dep_string_ += dep;
          first = false;
        }
        // ----------------------------------
        ++bb_dep_count;
      }
    }
    if (isa<ReturnInst>(bb.getTerminator())) {
      // no later execution of a sink in this invocation
      continue;
    }
    for (auto& writers : writers_of_variable) {
      if (writers.second.count(&bb) == 0) {
        continue;
      }
      for (auto& semaphore : semaphores) {
        if (semaphore.first.second == writers.first && semaphore.first.first != &bb) {
          new StoreInst(ConstantInt::get(int32_, 0), semaphore.second, false, insertion_point->getIterator());
        }
      }
    }
    auto source_block = conditional_bb_pair_dep_map.find(&bb);
    if (source_block != conditional_bb_pair_dep_map.end()) {
      // the current callpath state + 1, so that 0 keeps meaning "no source"
      auto bb_state_call = CallInst::Create(bb_state_, "", insertion_point->getIterator());
      for (auto& variable : source_block->second) {
        new StoreInst(bb_state_call, semaphores[{&bb, variable.first}], false, insertion_point->getIterator());
      }
    }
  }

  if (kDumpToDot) {
    cfg.DumpToDot(file_name_ + "_" + std::string(f.getName()) + ".CFG.dot");
    dg.DumpToDot(file_name_ + "_" + std::string(f.getName()) + ".DG.dot");
  }

  if (kDpHybridDebug) {
    errs() << "--- Conditional BB Dependences:\n";
    for (const auto& pair : conditional_bb_dep_map) {
      errs() << pair.first->getName() << ":\n";
      for (const auto& s : pair.second) {
        errs() << "\t" << s << "\n";
      }
    }

    errs() << "--- Conditional BB-Pair Dependences:\n";
    for (auto& pair1 : conditional_bb_pair_dep_map) {
      for (auto& variable : pair1.second) {
        for (auto& pair2 : variable.second) {
          errs() << pair1.first->getName() << "-";
          errs() << pair2.first->getName() << ":\n";
          for (const auto& s : pair2.second) {
            errs() << "\t" << s << "\n";
          }
        }
      }
    }
  }

  if (kDpHybridDebug) {
    errs() << "--- Program Instructions:\n";
    for (BasicBlock& bb : f) {
      for (Instruction& i : bb) {
        if (!isa<StoreInst>(i) && !isa<LoadInst>(i) && !isa<AllocaInst>(i)) {
          continue;
        }
        errs() << "\t" << (isa<StoreInst>(i) ? "Write " : (isa<AllocaInst>(i) ? "Alloca " : "Read ")) << " | ";
        if ((dl = i.getDebugLoc())) {
          errs() << dl.getLine() << "," << dl.getCol();
        } else {
          errs() << f.getSubprogram()->getLine() << ",*";
        }
        errs() << " | ";
        v = i.getOperand(isa<StoreInst>(i) ? 1 : 0);
        if (isa<AllocaInst>(i)) {
          v = dyn_cast<Value>(&i);
        }
        errs() << vnf_->GetVarName(v);

        if (omittable_instructions.find(&i) != omittable_instructions.end()) {
          errs() << " | OMITTED";
        }
        errs() << "\n";
      }
    }
  }

  // Remove omittable instructions from profiling
  //
  // By the call that was inserted for the instruction, not by whatever instruction happens
  // to sit next to it: the two are neighbours only as long as nothing between the
  // instrumentation and here moves them apart, and an instruction whose call is not found
  // keeps being profiled although its dependencies have been reported statically.
  for (Instruction* i : omittable_instructions) {
    const auto callback = inserted_access_callbacks.find(i);
    if (callback == inserted_access_callbacks.end()) {
      continue;
    }
    callback->second->eraseFromParent();
    inserted_access_callbacks.erase(callback);
  }

  // Report statically identified dependencies
  //
  // This file is the over-approximating record of the dependencies of the
  // omitted instructions: it drops the condition under which each of them
  // holds, so a dependency listed here is assumed to exist. Both maps have to
  // be written, for opposite reasons. Omitting the pair-conditional ones used
  // to lose exactly those dependencies whose write is not executed in every
  // iteration - a loop-carried accumulation guarded by an if, i.e. the shape
  // of a conditional reduction - and a lost dependency is what produces a
  // wrong suggestion. An over-approximated one only costs a suggestion.

  std::ofstream static_dependency_file = profiler_files::Open("static_dependencies.txt");

  for (const auto& pair : conditional_bb_dep_map) {
    for (const auto& s : pair.second) {
      static_dependency_file << s << "\n";
    }
  }
  for (auto& pair1 : conditional_bb_pair_dep_map) {
    for (auto& variable : pair1.second) {
      for (auto& pair2 : variable.second) {
        for (const auto& s : pair2.second) {
          static_dependency_file << s << "\n";
        }
      }
    }
  }

  if (kDpHybridDebug) {
    errs() << "Done with function " << f.getName() << ":\n";
  }
  return true;
}

void HybridAnalysis::Finalize(Module& m) {
  Type* void_type = Type::getVoidTy(m.getContext());
  PointerType* char_ptr = PointerType::getUnqual(Type::getInt8Ty(m.getContext()));

  // Hand the dependencies of the instructions whose profiling was omitted over
  // to the runtime. Their __dp_read / __dp_write / __dp_alloca calls have been
  // erased (see runOnFunction), so this string is the only remaining record of
  // those dependencies.
  //
  // bbDepString covers the functions of THIS module only, and a module which
  // does not define main has no __dp_finalize call to attach the handover to.
  // Attaching it there therefore silently dropped the dependencies of every
  // translation unit but one, which turned e.g. a reduction variable in a
  // non-main file into an apparently private one. Registering from a module
  // constructor reaches every translation unit regardless of compilation order;
  // the runtime only records the string there and parses it during
  // __dp_finalize, once it knows which basic blocks were executed.
  if (!bb_dep_string_.empty()) {
    Function* registration = Function::Create(FunctionType::get(void_type, false), GlobalValue::InternalLinkage,
                                              "__dp_register_bb_deps." + m.getModuleIdentifier(), &m);
    IRBuilder<> builder(BasicBlock::Create(m.getContext(), "entry", registration));
    Value* v = builder.CreateGlobalStringPtr(StringRef(bb_dep_string_), ".dp_bb_deps");
    builder.CreateCall(m.getOrInsertFunction("__dp_add_bb_deps", void_type, char_ptr), {v});
    builder.CreateRetVoid();
    appendToGlobalCtors(m, registration, 0);
  }
  // write the current count of BBs to a file to avoid duplicate BBids
  profiler_files::WriteCounter("DP_BBDepCounter.txt", bb_dep_count);
  // write the next free static memory region id to avoid duplicate ids between modules
  profiler_files::WriteCounter("DP_StaticMemoryRegionIDCounter.txt", next_free_static_memory_region_id_);
}
// DPInstrumentationOmission end
