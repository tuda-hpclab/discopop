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

#include "llvm/ADT/APInt.h"
#include "llvm/ADT/SmallVector.h"
#include "llvm/ADT/Statistic.h"
#include "llvm/ADT/StringRef.h"
#include "llvm/Analysis/CallGraph.h"
#include "llvm/Analysis/DependenceAnalysis.h"
#include "llvm/Analysis/LoopInfo.h"
#include "llvm/IR/CFG.h"
#include "llvm/IR/DebugInfo.h"
#include "llvm/IR/DebugInfoMetadata.h"
#include "llvm/IR/DebugLoc.h"
#include "llvm/IR/DerivedTypes.h"
#include "llvm/IR/Dominators.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/GlobalVariable.h"
#include "llvm/IR/IRBuilder.h"
#include "llvm/IR/InstIterator.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/IntrinsicInst.h"
#include "llvm/IR/LegacyPassManager.h"
#include "llvm/IR/Metadata.h"
#include "llvm/IR/Module.h"
#include "llvm/IR/PassManager.h"
#include "llvm/IR/Type.h"
#include "llvm/IR/Value.h"
#include "llvm/InitializePasses.h"
#include "llvm/Pass.h"
#include "llvm/PassRegistry.h"
#include "llvm/Support/CommandLine.h"
#include "llvm/Support/Debug.h"
#include "llvm/Support/FileSystem.h"
#include "llvm/Support/raw_ostream.h"

#if __has_include(<llvm/Transforms/IPO/PassManagerBuilder.h>)
#include <llvm/Transforms/IPO/PassManagerBuilder.h>
#endif

#if __has_include(<llvm/Transforms/Instrumentation.h>)
#include <llvm/Transforms/Instrumentation.h>
#endif

#if __has_include(<llvm/Passes/PassBuilder.h>)
#include <llvm/Passes/PassBuilder.h>
#endif

#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

#include <algorithm>
#include <cstdlib>
#include <iomanip>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "DPUtils.hpp"
#include "Structs.hpp"
#include "dp_reduction/ReductionInstrumenter.hpp"
#include "dp_reduction/dp_reduction.hpp"
#include "hybrid_analysis/HybridAnalysis.hpp"
#include "hybrid_analysis/InstructionDG.hpp"
#include "static_analysis/StaticCallPathTree.hpp"
#include "static_analysis/StaticCalltree.hpp"
#include "static_analysis/static_callpaths.hpp"
#include "utils/output.hpp"
#include "utils/profiler_files.hpp"

// The function called by the call or invoke I, looking through pointer casts and aliases, or
// nullptr for an indirect call. Clang emits the complete-object constructor (C1) of a class without
// virtual bases as an alias of the base-object constructor (C2), so `new T(...)` and `T t(...)` call
// an alias, for which CallBase::getCalledFunction returns nullptr.
inline llvm::Function* GetCalledFunctionThroughAliases(llvm::Instruction* i) {
  auto* cb = llvm::dyn_cast<llvm::CallBase>(i);
  if (cb == nullptr || cb->getCalledOperand() == nullptr) {
    return nullptr;
  }
  return llvm::dyn_cast<llvm::Function>(cb->getCalledOperand()->stripPointerCastsAndAliases());
}

// the unique instruction id assigned to I (metadata "dp.md.instr.id"), or 0 if it has none
inline int32_t GetDpInstructionId(llvm::Instruction* i) {
  const llvm::MDNode* md = i->getMetadata("dp.md.instr.id");
  if (md == nullptr) {
    return 0;
  }
  std::string id_str = llvm::cast<llvm::MDString>(md->getOperand(0))->getString().str();
  id_str.erase(0, 15);  // "dp.md.instr.id:"
  return std::stoi(id_str);
}

#include "Globals.hpp"

constexpr bool kDpDebug = false;

constexpr bool kClCheckLoopPar = true;
constexpr bool kDpVerbose = false;  // prints warning messages

/*
// Command line options
static cl::opt<bool> ClCheckLoopPar("dp-loop-par", cl::init(true), cl::desc("Check loop parallelism"), cl::Hidden);

static cl::opt<bool> DumpToDot("dp-omissions-dump-dot", cl::init(false),
                               cl::desc("Generate a .dot representation of the CFG and DG"), cl::Hidden);
*/

class DiscoPoP {  // : public ModulePass, public PassInfoMixin<DiscoPoP> {
 private:
  // CUGeneration

  // Mohammad 23.12.2020
  std::map<std::string, std::string> loop_start_lines_;

  // structures to get list of global variables
  std::set<std::string> program_global_variables_set_;
  // structures to get actual variable names from llvm replacements
  std::map<std::string, std::string> true_var_names_from_metadata_map_;

  // CUGeneration end

  // DPInstrumentation
  // Initializations
  void SetupDataTypes();

  void SetupCallbacks();

  // Helper functions
  bool IsaCallOrInvoke(llvm::Instruction* bi) const;

  bool SanityCheck(llvm::BasicBlock* bb);

  // the LID as the first argument of a callback: a 64 bit constant (the runtime's LID type) holding the
  // 32 bit packed location, i.e. the value the pass has always passed, zero extended
  llvm::Constant* LidConstant(LID lid) { return llvm::ConstantInt::get(int64_, static_cast<uint32_t>(lid)); }

  // LID to report for leaving the loop L through the exit block BB (see CFA)
  LID GetLoopExitLid(llvm::BasicBlock* bb, llvm::Loop* l);

  void CollectDebugInfo();

  void ProcessStructTypes(const std::string& full_struct_name, llvm::MDNode* struct_node);

  llvm::DIGlobalVariable* FindDbgGlobalDeclare(llvm::GlobalVariable* v);

  llvm::Value* GetOrInsertVarNameDynamic(std::string var_name, llvm::IRBuilder<>& builder);

  std::string GetOrInsertVarNameStatic(std::string var_name, llvm::IRBuilder<>& builder);

  llvm::Value* FindStructMemberName(llvm::MDNode* struct_node, unsigned idx, llvm::IRBuilder<>& builder);

  llvm::Type* PointsToStruct(llvm::PointerType* p_ty);

  llvm::Value* DetermineVariableNameDynamic(llvm::Instruction* i, const std::string& prefix);

  std::string DetermineVariableNameStatic(llvm::Instruction* i,
                                          bool& is_global_variable /*=defaultIsGlobalVariableValue*/,
                                          bool disable_metadata_map, const std::string& prefix);

  void GetTrueVarNamesFromMetadata(llvm::Region* top_region, Node* root,
                                   std::map<std::string, std::string>* true_var_names_from_metadata_map);

  // Control flow analysis
  void CFA(llvm::Function& f, llvm::LoopInfo& li, const std::map<llvm::Loop*, std::string>& loop_to_pet_node_id);

  // Callback Inserters
  // void insertDpFinalize(Instruction *before);
  void InstrumentAlloca(llvm::AllocaInst* to_instrument);

  void InstrumentNewOrMalloc(llvm::CallBase* to_instrument);
  void InstrumentRealloc(llvm::CallBase* to_instrument);
  void InstrumentCalloc(llvm::CallBase* to_instrument);
  void InstrumentPosixMemalign(llvm::CallBase* to_instrument);

  void InstrumentDeleteOrFree(llvm::CallBase* to_instrument);

  void InstrumentStore(llvm::StoreInst* to_instrument, int32_t llvm_ir_instruction_id);

  void InstrumentLoad(llvm::LoadInst* to_instrument, int32_t llvm_ir_instruction_id);

  void InsertDpFinalize(llvm::Instruction* before);

  void InstrumentFuncEntry(llvm::Function& f);

  void InstrumentLoopEntry(llvm::BasicBlock* bb, int32_t id);

  void InstrumentLoopExit(llvm::BasicBlock* bb, int32_t id, llvm::Loop* l);

  int64_t unique_num_{1};

  // Callbacks to run-time library
  llvm::FunctionCallee dp_finalize_;
  llvm::FunctionCallee dp_read_, dp_write_;
  llvm::FunctionCallee dp_alloca_, dp_new_, dp_delete_;  //, DpDecl;
  llvm::FunctionCallee dp_call_or_invoke_;
  llvm::FunctionCallee dp_func_entry_, dp_func_exit_;
  llvm::FunctionCallee dp_loop_entry_, dp_loop_exit_;
  llvm::FunctionCallee dp_taken_branch_counter_incr_;

  // Basic types
  llvm::Type* void_type_;
  llvm::IntegerType *int32_, *int64_;
  llvm::PointerType* char_ptr_;

  // Control flow analysis
  int32_t loop_id_;

  // Export Module M from runOnModule() to the whole structure space
  llvm::Module* this_module_;
  llvm::LLVMContext* this_module_context_;

  // The __dp_read / __dp_write / __dp_alloca call inserted for a load, store or alloca. The
  // omission analysis erases the ones whose instruction it can predict statically, and it
  // used to find them as the neighbour of that instruction -- which stops being true as soon
  // as anything moves the two apart, and then silently left the call in place. Filled while
  // instrumenting one function, cleared when the next one starts.
  std::map<llvm::Instruction*, llvm::CallInst*> inserted_access_callbacks_;

  std::map<std::string, llvm::Value*> var_names_;
  std::set<llvm::DIGlobalVariable*> global_vars_;
  std::map<std::string, llvm::MDNode*> structs_;
  // DPInstrumentation end

  // DPInstrumentationOmission
  // created by doInitialization, where it declares its callbacks
  std::optional<hybrid_analysis::HybridAnalysis> hybrid_analysis_;

  // DPInstrumentationOmission end

  // InstructionID assignment
  uint32_t unique_llvm_ir_instruction_id_;
  uint32_t unique_callpath_state_id_;

 public:
  DiscoPoP() {}  // : ModulePass(ID), uniqueNum(1){};

  bool RunOnModule(llvm::Module& m, llvm::ModuleAnalysisManager& mam);

  bool RunOnFunction(llvm::Function& f, llvm::ModuleAnalysisManager& mam);

  // the stages of runOnFunction, see there for why they run in this order
  void BuildCuGraph(llvm::Function& f, llvm::ModuleAnalysisManager& mam, FunctionCUGraph& graph);
  void InstrumentFunction(llvm::Function& f, llvm::ModuleAnalysisManager& mam, const FunctionCUGraph& graph);
  void WriteCuGraph(FunctionCUGraph& graph);

  void RunOnBasicBlock(llvm::BasicBlock& bb);

  bool DoInitialization(llvm::Module& m);

  bool DoFinalization(llvm::Module& m);

  static char id;  // Pass identification, replacement for typeid

  // CUGeneration

  // DiscoPoP Functions
  std::string DetermineVariableType(llvm::Instruction* i);

  std::string DetermineVariableDefLine(llvm::Instruction* i);

  void GetFunctionReturnLines(llvm::Region* top_region, Node* root);

  int32_t GetOrRegisterLoopId(llvm::Loop* l);

  // functions to get list of global variables

  // functions to get recursive functions (Mo 5.11.2019)
  bool IsRecursive(llvm::Function& f, llvm::CallGraph& cg);

  // Populate variable sets global to BB
  void PopulateGlobalVariablesSet(llvm::Region* top_region, std::set<std::string>& global_variables_set);

  void CreateCus(llvm::Region* top_region, std::set<std::string>& global_variables_set, std::vector<CU*>& cu_vector,
                 std::map<std::string, std::vector<CU*>>& bb_id_to_cu_ids_map, Node* root, llvm::LoopInfo& li,
                 llvm::ModuleAnalysisManager& mam);

  void CreateTakenBranchInstrumentation(llvm::Region* top_region,
                                        std::map<std::string, std::vector<CU*>>& bb_id_to_cu_ids_map);

  bool IsInstrumentedFunction(llvm::Function& f);
  // determineFileID, cached per function of the current module (the lookup walks the function and
  // resolves its file path)
  int32_t GetCachedFileId(llvm::Function& f);
  std::unordered_map<const llvm::Function*, int32_t> file_id_cache;
  void AssignInstructionIdsToDpReductionFunctions(llvm::Module& m);
  void UpdateArgumentInstructionIds(llvm::Module& m);
  void InstrumentLandingPads(llvm::Module& m);

  void FillCuVariables(llvm::Region* top_region, std::set<std::string>& global_variables_set,
                       std::vector<CU*>& cu_vector, std::map<std::string, std::vector<CU*>>& bb_id_to_cu_ids_map);

  void FillStartEndLineNumbers(Node* root, llvm::LoopInfo& li, std::map<llvm::Loop*, std::string>& loop_to_pet_node_id);

  void FindStartEndLineNumbers(Node* root, LID& start, LID& end);

  // Output function
  void InitializeCuIdCounter();
  void InitializeInstructionIdCounter();
  void InitializeCallpathStateIdCounter();

  // void printOriginalVariables(set<string> &originalVariablesSet);
  // CUGeneration end

  // DPReduction

  std::string DpReductionDetermineVariableName(llvm::Instruction* i,
                                               std::map<std::string, std::string>* true_var_names_from_metadata_map);
  std::string FindStructMemberNameStatic(llvm::MDNode* struct_node, unsigned idx, llvm::IRBuilder<>& builder);
  std::ofstream instruction_id_to_line_id_file;
  std::map<llvm::Loop*, int> loop_to_id;
  // per loop id of the current module: id of its loop node in Data.xml and its start
  // location (file_id:line), as written to loopstate_positions.txt
  std::map<int32_t, LoopIdentity> loop_id_to_identity;

  // DPReduction end
};  // end of class DiscoPoP
