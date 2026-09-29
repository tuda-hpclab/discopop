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

#include "DPUtils.hpp"
#include "hybrid_analysis/InstructionDG.hpp"
#include "static_analysis/StaticCalltree.hpp"
#include "static_analysis/StaticCallPathTree.hpp"

#include "Structs.hpp"

#include <algorithm>
#include <cstdlib>
#include <iomanip>
#include <map>
#include <set>
#include <string.h>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <boost/container_hash/hash.hpp>

#include <sys/stat.h>
#include <sys/types.h>

#include <stdlib.h>

#include "Globals.hpp"

#define DP_DEBUG false

#define ClCheckLoopPar true
#define DumpToDot false
#define DP_DEBUG false
#define DP_VERBOSE false // prints warning messages
#define DP_hybrid_DEBUG false

using namespace llvm;
using namespace std;
using namespace dputil;

/*
// Command line options
static cl::opt<bool> ClCheckLoopPar("dp-loop-par", cl::init(true), cl::desc("Check loop parallelism"), cl::Hidden);

static cl::opt<bool> DumpToDot("dp-omissions-dump-dot", cl::init(false),
                               cl::desc("Generate a .dot representation of the CFG and DG"), cl::Hidden);
*/

class DiscoPoP { // : public ModulePass, public PassInfoMixin<DiscoPoP> {
private:
  // CUGeneration

  ofstream *outCUs;
  ofstream *outOriginalVariables;
  ofstream *outCUIDCounter;
  ofstream *outBBDepCounter;
  ofstream *outInstructionIDCounter;
  ofstream *outCallpathStateIDCounter;
  // Mohammad 23.12.2020
  map<string, string> loopStartLines;

  // structures to get list of global variables
  set<string> programGlobalVariablesSet;
  // structures to get actual variable names from llvm replacements
  map<string, string> trueVarNamesFromMetadataMap;

  // CUGeneration end

  // DPInstrumentation
  // Initializations
  void setupDataTypes();

  void setupCallbacks();

  // Helper functions
  bool isaCallOrInvoke(Instruction *BI);

  bool sanityCheck(BasicBlock *BB);

  void collectDebugInfo();

  void processStructTypes(string const &fullStructName, MDNode *structNode);

  DIGlobalVariable *findDbgGlobalDeclare(GlobalVariable *V);

  Value *getOrInsertVarName_dynamic(string varName, IRBuilder<> &builder);

  string getOrInsertVarName_static(string varName, IRBuilder<> &builder);

  Value *findStructMemberName(MDNode *structNode, unsigned idx, IRBuilder<> &builder);

  Type *pointsToStruct(PointerType *PTy);

  Value *determineVariableName_dynamic(Instruction *const I, string prefix);

  string determineVariableName_static(Instruction *I, bool &isGlobalVariable /*=defaultIsGlobalVariableValue*/,
                                      bool disable_MetadataMap, string prefix);

  void getTrueVarNamesFromMetadata(Region *TopRegion, Node *root,
                                   std::map<string, string> *trueVarNamesFromMetadataMap);

  // Control flow analysis
  void CFA(Function &F, LoopInfo &LI);

  // Callback Inserters
  // void insertDpInit(const vector<Value*> &args, Instruction *before);
  // void insertDpFinalize(Instruction *before);
  void instrumentAlloca(AllocaInst *toInstrument);

  void instrumentNewOrMalloc(CallBase *toInstrument);
  void instrumentRealloc(CallBase *toInstrument);
  void instrumentCalloc(CallBase *toInstrument);
  void instrumentPosixMemalign(CallBase *toInstrument);

  void instrumentDeleteOrFree(CallBase *toInstrument);

  void instrumentStore(StoreInst *toInstrument, int32_t llvm_ir_instruction_id);

  void instrumentLoad(LoadInst *toInstrument, int32_t llvm_ir_instruction_id);

  void insertDpFinalize(Instruction *before);

  void instrumentFuncEntry(Function &F);

  void instrumentLoopEntry(BasicBlock *bb, int32_t id);

  void instrumentLoopExit(BasicBlock *bb, int32_t id);

  int64_t uniqueNum;

  // Callbacks to run-time library
  FunctionCallee DpInit, DpFinalize;
  FunctionCallee DpRead, DpWrite;
  FunctionCallee DpAlloca, DpNew, DpDelete; //, DpDecl;
  FunctionCallee DpCallOrInvoke;
  FunctionCallee DpFuncEntry, DpFuncExit;
  FunctionCallee DpLoopEntry, DpLoopExit;
  FunctionCallee DpTakenBranchCounterIncr;

  // Basic types
  Type *Void;
  IntegerType *Int8, *Int32, *Int64;
  PointerType *CharPtr;

  // Control flow analysis
  int32_t loopID;

  // Output streams
  ofstream ocfg;

  // Export Module M from runOnModule() to the whole structure space
  Module *ThisModule;
  LLVMContext *ThisModuleContext;

  map<string, Value *> VarNames;
  set<DIGlobalVariable *> GlobalVars;
  map<string, MDNode *> Structs;
  // DPInstrumentation end

  // DPInstrumentationOmission
  string bbDepString;
  string fileName;
  int32_t fid;
  FunctionCallee ReportBB, ReportBBPair;
  dputil::VariableNameFinder *VNF;
  std::ofstream *staticDependencyFile;
  int nextFreeStaticMemoryRegionID;

  // DPInstrumentationOmission end

  // InstructionID assignment
  uint32_t unique_llvm_ir_instruction_id;
  uint32_t unique_callpath_state_id;

public:
  DiscoPoP() : uniqueNum(1){}; // : ModulePass(ID), uniqueNum(1){};

  ~DiscoPoP();

  StringRef getPassName() const;

  bool runOnModule(Module &M, ModuleAnalysisManager &MAM);

  bool runOnFunction(Function &F, ModuleAnalysisManager &MAM);

  void runOnBasicBlock(BasicBlock &BB);

  bool doInitialization(Module &M);

  bool doFinalization(Module &M);

  void getAnalysisUsage(AnalysisUsage &Info) const;

  static char ID; // Pass identification, replacement for typeid

  // CUGeneration

  // DiscoPoP Functions
  string determineVariableType(Instruction *I);

  string determineVariableDefLine(Instruction *I);

  void getFunctionReturnLines(Region *TopRegion, Node *root);

  int32_t get_or_register_loop_id(llvm::Loop* L);

  // functions to get list of global variables
  void collectGlobalVariables();

  // functions to get recursive functions (Mo 5.11.2019)
  bool isRecursive(Function &F, CallGraph &CG);

  // Populate variable sets global to BB
  void populateGlobalVariablesSet(Region *TopRegion, set<string> &globalVariablesSet);

  void createCUs(Region *TopRegion, set<string> &globalVariablesSet, vector<CU *> &CUVector,
                 map<string, vector<CU *>> &BBIDToCUIDsMap, Node *root, LoopInfo &LI, ModuleAnalysisManager &MAM);

  void createTakenBranchInstrumentation(Region *TopRegion, map<string, vector<CU *>> &BBIDToCUIDsMap);

  StaticCalltree buildStaticCalltree(Module &M);
  //std::pair<std::unordered_map<int32_t, std::vector<StaticCalltreeNode*>>, std::unordered_map<int32_t, std::unordered_map<int32_t, int32_t>>> enumerate_paths(StaticCalltree& calltree);
  StaticCallPathTree* enumerate_paths(StaticCalltree& calltree, std::unordered_map<int32_t, std::unordered_map<int32_t, int32_t>> *state_transitions,
  std::unordered_map<int32_t, std::unordered_map<int32_t, int32_t>> *inverse_state_transitions, std::uint32_t start_path_id);
  //void save_initial_path(std::unordered_map<int32_t, std::vector<StaticCalltreeNode*>> paths);
  void save_initial_path(StaticCallPathTree* call_path_tree_ptr);
  //void save_enumerated_paths(std::unordered_map<int32_t, std::vector<StaticCalltreeNode*>> paths);
  void save_enumerated_paths(StaticCallPathTree* call_path_tree_ptr);
  // void save_path_state_transitions(std::unordered_map<int32_t, std::unordered_map<int32_t, int32_t>> *transitions);
  void save_path_state_transitions(StaticCallPathTree* call_path_tree_ptr);
  void save_static_calltree_to_dot(StaticCalltree* calltree);
  void assign_instruction_ids_to_dp_reduction_functions(Module &M);
  void update_argument_instruction_ids(Module &M);
// hasher used for std::vector<StaticCalltreeNode*>
template <typename Container>
struct container_hash {
    std::size_t operator()(Container const& c) const {
        return boost::hash_range(c.begin(), c.end());
    }
};
  // void add_function_exit_edges_to_transitions(std::unordered_map<int32_t, std::unordered_map<int32_t, int32_t>>& state_transitions, std::unordered_map<int32_t, std::vector<StaticCalltreeNode*>> paths, std::unordered_map<std::vector<StaticCalltreeNode*>, int32_t, container_hash<std::vector<StaticCalltreeNode*>>> path_to_id_map);
  //void add_function_exit_edges_to_transitions(std::unordered_map<int32_t, std::unordered_map<int32_t, int32_t>>& state_transitions, StaticCallPathTree* call_path_tree_ptr);
  void add_function_exit_edges_to_transitions(StaticCallPathTree* call_path_tree_ptr);

  std::unordered_map<StaticCalltreeNode*, std::unordered_set<int32_t>> get_contained_in_map(std::unordered_map<int32_t, std::vector<StaticCalltreeNode*>>& paths);
  std::unordered_map<std::vector<StaticCalltreeNode*>, int32_t, container_hash<std::vector<StaticCalltreeNode*>>> get_path_to_id_map(std::unordered_map<int32_t, std::vector<StaticCalltreeNode*>>& paths);

  void fillCUVariables(Region *TopRegion, set<string> &globalVariablesSet, vector<CU *> &CUVector,
                       map<string, vector<CU *>> &BBIDToCUIDsMap);

  void fillStartEndLineNumbers(Node *root, LoopInfo &LI);

  void findStartEndLineNumbers(Node *root, int &start, int &end);

  // Output function
  void initializeCUIDCounter();
  void initializeBBDepCounter();
  void initializeInstructionIDCounter();
  void initializeCallpathStateIDCounter();

  string xmlEscape(string data);

  void secureStream();

  string getLineNumbersString(set<int> LineNumbers);

  string getChildrenNodesString(Node *node);

  // void printOriginalVariables(set<string> &originalVariablesSet);
  void printData(Node *node);

  void printTree(Node *node, bool isRoot);

  void printNode(Node *node, bool isRoot);

  void closeOutputFiles();
  // CUGeneration end

  // DPReduction

  void instrument_module(llvm::Module *module, map<string, string> *trueVarNamesFromMetadataMap, llvm::ModuleAnalysisManager &mam);
  bool inlinedFunction(Function *F);
  void instrument_function(llvm::Function *function, map<string, string> *trueVarNamesFromMetadataMap, llvm::LoopInfo &loop_info);
  void instrument_loop(Function &F, int file_id, llvm::Loop *loop, LoopInfo &LI,
                       map<string, string> *trueVarNamesFromMetadataMap);
  std::string dp_reduction_CFA(Function &F, llvm::Loop *loop, int file_id);
  string dp_reduction_determineVariableName(Instruction *I, map<string, string> *trueVarNamesFromMetadataMap);
  string dp_reduction_determineVariableType(Instruction *I);
  llvm::Instruction *dp_reduction_get_reduction_instr(llvm::Instruction *store_instr, llvm::Instruction **load_instr);
  llvm::Instruction *dp_reduction_find_reduction_instr(llvm::Value *val);
  llvm::Instruction *dp_reduction_get_load_instr(llvm::Value *load_val, llvm::Instruction *cur_instr,
                                                 std::vector<char> &reduction_operations);
  llvm::Value *dp_reduction_points_to_var(llvm::GetElementPtrInst *instr);
  llvm::Value *dp_reduction_get_var(llvm::Instruction *instr);
  llvm::Value *dp_reduction_get_var_rec(llvm::Value *val);
  llvm::Instruction *dp_reduction_get_prev_use(llvm::Instruction *instr, llvm::Value *val);
  inline bool dp_reduction_loc_exists(llvm::DebugLoc const &loc) { return static_cast<bool>(loc); }
  unsigned dp_reduction_get_file_id(llvm::Function *func);
  bool dp_reduction_init_util(std::string fmap_path);
  char dp_reduction_get_char_for_opcode(llvm::Instruction *instr); //} // namespace
  bool dp_reduction_is_operand(llvm::Instruction *instr, llvm::Value *operand);
  int dp_reduction_get_op_order(char c);
  Type *dp_reduction_pointsToStruct(PointerType *PTy);
  string findStructMemberName_static(MDNode *structNode, unsigned idx, IRBuilder<> &builder);
  bool dp_reduction_sanityCheck(BasicBlock *BB, int file_id);
  LID dp_reduction_getLID(Instruction *BI, int32_t &fileID);
  void dp_reduction_insert_functions();
  bool check_value_usage(llvm::Value *parentValue, llvm::Value *searchedValue);
  llvm::LLVMContext *ctx_;
  llvm::Module *module_;
  std::ofstream *reduction_file;
  std::ofstream *loop_counter_file;
  std::ofstream *instructionID_to_lineID_file;
  std::ofstream *stateID_to_callpath_file;
  std::ofstream *callpath_state_transitions_file;
  std::vector<loop_info_t> loops_;
  std::vector<instr_info_t> instructions_;
  std::map<std::string, int> path_to_id_;
  std::map<llvm::Loop*, int> loop_to_id;

  // DPReduction end

}; // end of class DiscoPoP
