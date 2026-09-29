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

#include "../DiscoPoP.hpp"

bool DiscoPoP::runOnFunction(Function &F, ModuleAnalysisManager &MAM) {
  if (DP_DEBUG) {
    errs() << "pass DiscoPoP: run pass on function " << F.getName().str() << "\n";
  }

  // avoid instrumenting functions which are defined outside the scope of the
  // project

  std::string dp_project_dir(getenv("DP_PROJECT_ROOT_DIR"));

  SmallVector<std::pair<unsigned, MDNode *>, 4> MDs;
  F.getAllMetadata(MDs);
  bool funcDefinedInProject = false;
  for (auto &MD : MDs) {
    if (MDNode *N = MD.second) {
      if (auto *subProgram = dyn_cast<DISubprogram>(N)) {
        std::string fullFileName = "";
        if (subProgram->getDirectory().str().length() > 0) {
          fullFileName += subProgram->getDirectory().str();
          fullFileName += "/";
        }
        fullFileName += subProgram->getFilename().str();
        if (fullFileName.find(dp_project_dir) != string::npos) // function defined inside project
        {
          funcDefinedInProject = true;
        }
      }
    }
  }
  if (!funcDefinedInProject) {
    return false;
  }

  StringRef funcName = F.getName();
  // Avoid functions we don't want to instrument
  if (funcName.find("llvm.") != string::npos) // llvm debug calls
  {
    return false;
  }
  if (funcName.find("__dp_") != string::npos) // instrumentation calls
  {
    return false;
  }
  if (funcName.find("__cx") != string::npos) // c++ init calls
  {
    return false;
  }
  if (funcName.find("__clang") != string::npos) // clang helper calls
  {
    return false;
  }
  if (funcName.find("_GLOBAL_") != string::npos) // global init calls (c++)
  {
    return false;
  }
  if (funcName.find("pthread_") != string::npos) {
    return false;
  }



  vector<CU *> CUVector;
  Node *root = new Node;
  set<string> globalVariablesSet; // list of variables which appear in more than
  // one basic block
  map<string, vector<CU *>> BBIDToCUIDsMap;

  determineFileID(F, fileID);

  // only instrument functions belonging to project source files
  if (!fileID)
    return false;

  // CUGenerationgetAna
  {
    /********************* Initialize root values ***************************/
    root->name = F.getName().str();
    root->type = nodeTypes::func;

    // Get list of arguments for this function and store them in root.
    // NOTE: changed the way we get the arguments
    BasicBlock *BB = &F.getEntryBlock();
    auto BI = BB->begin();
    string lid;
    if (DebugLoc dl = BI->getDebugLoc()) {
      lid = to_string(dl->getLine());
    } else {
      lid = to_string(BI->getFunction()->getSubprogram()->getLine());
    }

    for (Function::arg_iterator it = F.arg_begin(); it != F.arg_end(); it++) {
      string type_str;
      raw_string_ostream rso(type_str);
      (it->getType())->print(rso);
      Variable v(it->getName().str(), rso.str(), to_string(fileID) + ":" + lid, true, true);
      root->argumentsList.push_back(v);
    }
    /********************* End of initialize root values
     * ***************************/

    llvm::FunctionAnalysisManager &fam = MAM.getResult<FunctionAnalysisManagerModuleProxy>(*module_).getManager();
    llvm::LoopInfo &LI = fam.getResult<llvm::LoopAnalysis>(F);
    //LoopInfo &LI = getAnalysis<LoopInfoWrapperPass>(F).getLoopInfo();


    // get the top level region

    //RIpass = &getAnalysis<RegionInfoPass>(F);
    //RI = &(RIpass->getRegionInfo());
    //RegionInfoPass *RIpass;
    llvm::RegionInfo &RI = fam.getResult<llvm::RegionInfoAnalysis>(F);

    Region *TopRegion = RI.getTopLevelRegion();

    getTrueVarNamesFromMetadata(TopRegion, root, &trueVarNamesFromMetadataMap);

    getFunctionReturnLines(TopRegion, root);

    populateGlobalVariablesSet(TopRegion, globalVariablesSet);

    createCUs(TopRegion, globalVariablesSet, CUVector, BBIDToCUIDsMap, root, LI, MAM);

    if (DP_BRANCH_TRACKING) {
      createTakenBranchInstrumentation(TopRegion, BBIDToCUIDsMap);
    }

    fillCUVariables(TopRegion, globalVariablesSet, CUVector, BBIDToCUIDsMap);

    fillStartEndLineNumbers(root, LI);

    secureStream();

    // printOriginalVariables(originalVariablesSet);

    /*printData(root);

    for (auto i : CUVector) {
      delete (i);
    }*/
  }
  // CUGeneration end

  // DPInstrumentation
  {
    // Check loop parallelism?
    if (ClCheckLoopPar) {
      llvm::FunctionAnalysisManager &fam = MAM.getResult<FunctionAnalysisManagerModuleProxy>(*module_).getManager();
      llvm::LoopInfo &LI = fam.getResult<llvm::LoopAnalysis>(F);
      //LoopInfo &LI = getAnalysis<LoopInfoWrapperPass>(F).getLoopInfo();
      CFA(F, LI);
    }

    // Instrument the entry of the function.
    // Each function entry is instrumented, and the first
    // executed function will initialize shadow memory.
    // See the definition of __dp_func_entry() for detail.
    instrumentFuncEntry(F);

    // Traverse all instructions, collect loads/stores/returns, check for calls.
    for (Function::iterator FI = F.begin(), FE = F.end(); FI != FE; ++FI) {
      BasicBlock &BB = *FI;
      runOnBasicBlock(BB);
    }

    if (DP_DEBUG) {
      errs() << "pass DiscoPoP: finished function\n";
    }
  }
  // DPInstrumentation end

  // Print CU Graph
  {
    printData(root);

    for (auto i : CUVector) {
      delete (i);
    }
  }
  // Print CU Graph end

  // DPInstrumentationOmission
  {
    if (F.getInstructionCount() == 0)
      return false;

// Enable / Disable hybrid profiling
#ifndef DP_HYBRID_PROFILING
#define DP_HYBRID_PROFILING 1
#endif

#if DP_HYBRID_PROFILING == 0
    return true;
#endif
    /////

    if (DP_hybrid_DEBUG)
      errs() << "\n---------- Omission Analysis on " << F.getName() << " ----------\n";

    DebugLoc dl;
    Value *V;

    set<Instruction *> omittableInstructions;

    set<Value *> staticallyPredictableValues;
    // Get local values (variables)
    for (Instruction &I : F.getEntryBlock()) {
      if (AllocaInst *AI = dyn_cast<AllocaInst>(&I)) {
        staticallyPredictableValues.insert(AI);
      }
    }
    for (BasicBlock &BB : F) {
      for (Instruction &I : BB) {
        // Remove from staticallyPredictableValues those which are passed to
        // other functions (by ref/ptr)
        if (CallInst *call_inst = dyn_cast<CallInst>(&I)) {
          if (call_inst->getCalledFunction()) {
            for (uint i = 0; i < call_inst->getNumOperands() - 1; ++i) {
              V = call_inst->getArgOperand(i);
              std::set<Value *>::iterator it = staticallyPredictableValues.find(V);
              if (it != staticallyPredictableValues.end()) {
                staticallyPredictableValues.erase(V);
                if (DP_hybrid_DEBUG)
                  errs() << VNF->getVarName(V) << "\n";
              }
            }
          }
        }
        // Remove values from locals if dereferenced
        if (isa<StoreInst>(I)) {
          V = I.getOperand(0);
          std::set < Value*> to_be_removed;
          for (Value *w : staticallyPredictableValues) {
            if (w == V) {
              to_be_removed.insert(V);
            }
          }
          for(Value* w: to_be_removed){
            staticallyPredictableValues.erase(V);
          }
        }
      }
    }

    // assign static memory region IDs to statically predictable values and thus
    // dependencies
    unordered_map<string, pair<string, string>> staticValueNameToMemRegIDMap; // <SSA variable name>: (original variable
                                                                              // name, statically assigned MemReg ID)
    long next_id;
    string llvmIRVarName;
    string originalVarName;
    string staticMemoryRegionID;
    for (auto V : staticallyPredictableValues) {
      next_id = nextFreeStaticMemoryRegionID++;
      llvmIRVarName = VNF->getVarName(V);
      // Note: Using variables names as keys is only possible at this point,
      // since the map is created for each function individually. Thus, we can
      // rely on the SSA properties of LLVM IR and can assume that e.g. scoping
      // is handled by LLVM and destinct variable names are introduced.
      originalVarName = trueVarNamesFromMetadataMap[llvmIRVarName];
      if (originalVarName.size() == 0) {
        // no original variable name could be identified using the available
        // metadata. Fall back to the LLVM IR name of the value.
        originalVarName = llvmIRVarName;
      }
      staticMemoryRegionID = "S" + to_string(next_id);
      staticValueNameToMemRegIDMap[llvmIRVarName] = pair<string, string>(originalVarName, staticMemoryRegionID);
    }

    if (DP_hybrid_DEBUG) {
      errs() << "--- Local Values ---\n";
      for (auto V : staticallyPredictableValues) {
        errs() << VNF->getVarName(V) << "\n";
      }
    }

    // Perform the SPA dependence analysis
    int32_t fid;
    determineFileID(F, fid);
    map<BasicBlock *, set<string>> conditionalBBDepMap;
    map<BasicBlock *, map<BasicBlock *, set<string>>> conditionalBBPairDepMap;

    //auto &DT = getAnalysis<DominatorTreeWrapperPass>(F).getDomTree();
    llvm::FunctionAnalysisManager &fam = MAM.getResult<FunctionAnalysisManagerModuleProxy>(*module_).getManager();
    //llvm::LoopInfo &LI = fam.getResult<llvm::LoopAnalysis>(F);
    llvm::DominatorTree &DT= fam.getResult<llvm::DominatorTreeAnalysis>(F);

    InstructionCFG CFG(VNF, F);
    InstructionDG DG(VNF, &CFG, fid);

    // collect init instruction to prevent false-positive WAW Dependences due to allocations in loops,
    // which will be moved to the function entry
    map<string, set<string>> lineToInitializedVarsMap;
    for (auto edge : DG.getEdges()){
      if(DG.edgeIsINIT(edge)){
        string initLine = DG.getInitEdgeInstructionLine(edge);
        string varIdentifier = DG.getValueNameAndMemRegIDFromEdge(edge, staticValueNameToMemRegIDMap);

        if(lineToInitializedVarsMap.find(initLine) == lineToInitializedVarsMap.end()){
          set<string> tmp;
          lineToInitializedVarsMap[initLine] = tmp;
        }
        lineToInitializedVarsMap[initLine].insert(varIdentifier);
      }
    }

    for (auto edge : DG.getEdges()) {
      Instruction *Src = edge->getSrc()->getItem();
      Instruction *Dst = edge->getDst()->getItem();

      V = Src->getOperand(isa<StoreInst>(Src) ? 1 : 0);
      if (isa<AllocaInst>(Dst))
        V = dyn_cast<Value>(Dst);

      if (staticallyPredictableValues.find(V) == staticallyPredictableValues.end())
        continue;

      if (Src != Dst && DT.dominates(Dst, Src)) {
        if (!conditionalBBDepMap.count(Src->getParent())) {
          set<string> tmp;
          conditionalBBDepMap[Src->getParent()] = tmp;
        }
        conditionalBBDepMap[Src->getParent()].insert(DG.edgeToInstructionBasedDPDep(edge, staticValueNameToMemRegIDMap));
      } else {
        if (!conditionalBBPairDepMap.count(Dst->getParent())) {
          map<BasicBlock *, set<string>> tmp;
          conditionalBBPairDepMap[Dst->getParent()] = tmp;
        }
        if (!conditionalBBPairDepMap[Dst->getParent()].count(Src->getParent())) {
          set<string> tmp;
          conditionalBBPairDepMap[Dst->getParent()][Src->getParent()] = tmp;
        }
        // Prevent reporting of false-positive WAW Dependencies due to alloca movement from e.g. loops to function entry
        bool insertDep = true;
        if(Dst == Src){ // check if instruciton are the same
          // check if initialization exists in the instruction line
          if(lineToInitializedVarsMap.find(DG.getInstructionLine(Dst)) != lineToInitializedVarsMap.end()){
            // check if the accessed variable is initialed here
            string varIdentifier = DG.getValueNameAndMemRegIDFromEdge(edge, staticValueNameToMemRegIDMap);
            if(lineToInitializedVarsMap[DG.getInstructionLine(Dst)].find(varIdentifier) != lineToInitializedVarsMap[DG.getInstructionLine(Dst)].end()){
              // ignore this access as the initialized variable is accessed
              insertDep = false;
            }
          }
        }

        if(insertDep){
          conditionalBBPairDepMap[Dst->getParent()][Src->getParent()].insert(
            DG.edgeToInstructionBasedDPDep(edge, staticValueNameToMemRegIDMap));
        }
      }
      omittableInstructions.insert(Src);
      omittableInstructions.insert(Dst);
    }

    // Omit SPA instructions with no dependences
    for (auto node : DG.getInstructionNodes()) {
      if (!isa<StoreInst>(node->getItem()) && !!isa<LoadInst>(node->getItem()))
        continue;
      V = node->getItem()->getOperand(isa<StoreInst>(node->getItem()) ? 1 : 0);
      if (!DG.getInEdges(node).size() && !DG.getOutEdges(node).size() &&
          staticallyPredictableValues.find(V) != staticallyPredictableValues.end())
        omittableInstructions.insert(node->getItem());
    }

    // Add observation of execution of single basic blocks
    for (auto pair : conditionalBBDepMap) {
      // Insert call to reportbb
      Instruction *insertionPoint = pair.first->getTerminator();
      if (isa<ReturnInst>(pair.first->getTerminator())) {
#if LLVM_VERSION_MAJOR >= 22
        insertionPoint = insertionPoint->getPrevNode();
#else
        insertionPoint = insertionPoint->getPrevNonDebugInstruction();
#endif
      }
#if LLVM_VERSION_MAJOR >= 22
      CallInst::Create(ReportBB, ConstantInt::get(Int32, bbDepCount), "", insertionPoint->getIterator());
#else
      CallInst::Create(ReportBB, ConstantInt::get(Int32, bbDepCount), "", insertionPoint);
#endif

      // ---- Insert deps into string ----
      if (bbDepCount)
        bbDepString += "/";
      bool first = true;
      bbDepString += to_string(bbDepCount) + "=";
      for (auto dep : pair.second) {
        if (!first)
          bbDepString += ",";
        bbDepString += dep;
        first = false;
      }
      // ---------------------------------
      ++bbDepCount;
    }

    // Add observation of in-order execution of pairs of basic blocks
    for (auto pair1 : conditionalBBPairDepMap) {
      // Alloca and init semaphore var for BB
#if LLVM_VERSION_MAJOR >= 22
      auto AI = new AllocaInst(Int32, 0, "__dp_bb", F.getEntryBlock().getFirstNonPHI()->getNextNode()->getIterator());
      new StoreInst(ConstantInt::get(Int32, 0), AI, false, AI->getNextNode()->getIterator());
#else
      auto AI = new AllocaInst(Int32, 0, "__dp_bb", F.getEntryBlock().getFirstNonPHI()->getNextNonDebugInstruction());
      new StoreInst(ConstantInt::get(Int32, 0), AI, false, AI->getNextNonDebugInstruction());
#endif

      for (auto pair2 : pair1.second) {
        // Insert check for semaphore
        Instruction *insertionPoint = pair2.first->getTerminator();
        if (isa<ReturnInst>(pair2.first->getTerminator())) {
#if LLVM_VERSION_MAJOR >= 22
          insertionPoint = insertionPoint->getPrevNode();
#else
          insertionPoint = insertionPoint->getPrevNonDebugInstruction();
#endif
        }

#if LLVM_VERSION_MAJOR >= 22
        auto LI = new LoadInst(Int32, AI, Twine(""), false, insertionPoint->getIterator());
        CallInst::Create(ReportBBPair, ArrayRef<Value *>({LI, ConstantInt::get(Int32, bbDepCount)}), "", insertionPoint->getIterator());
#else
        auto LI = new LoadInst(Int32, AI, Twine(""), false, insertionPoint);
        CallInst::Create(ReportBBPair, ArrayRef<Value *>({LI, ConstantInt::get(Int32, bbDepCount)}), "", insertionPoint);
#endif

        // ---- Insert deps into string ----
        if (bbDepCount)
          bbDepString += "/";
        bbDepString += to_string(bbDepCount);
        bbDepString += "=";
        bool first = true;
        for (auto dep : pair2.second) {
          if (!first)
            bbDepString += ",";
          bbDepString += dep;
          first = false;
        }
        // ----------------------------------
        ++bbDepCount;
      }
      // Insert semaphore update to true
#if LLVM_VERSION_MAJOR >= 22
      new StoreInst(ConstantInt::get(Int32, 1), AI, false, pair1.first->getTerminator()->getIterator());
#else
      new StoreInst(ConstantInt::get(Int32, 1), AI, false, pair1.first->getTerminator());
#endif
    }

    if (DumpToDot) {
      CFG.dumpToDot(fileName + "_" + string(F.getName()) + ".CFG.dot");
      DG.dumpToDot(fileName + "_" + string(F.getName()) + ".DG.dot");
    }

    if (DP_hybrid_DEBUG) {
      errs() << "--- Conditional BB Dependences:\n";
      for (auto pair : conditionalBBDepMap) {
        errs() << pair.first->getName() << ":\n";
        for (auto s : pair.second) {
          errs() << "\t" << s << "\n";
        }
      }

      errs() << "--- Conditional BB-Pair Dependences:\n";
      for (auto pair1 : conditionalBBPairDepMap) {
        for (auto pair2 : pair1.second) {
          errs() << pair1.first->getName() << "-";
          errs() << pair2.first->getName() << ":\n";
          for (auto s : pair2.second)
            errs() << "\t" << s << "\n";
        }
      }
    }

    if (DP_hybrid_DEBUG) {
      errs() << "--- Program Instructions:\n";
      for (BasicBlock &BB : F) {
        for (Instruction &I : BB) {
          if (!isa<StoreInst>(I) && !isa<LoadInst>(I) && !isa<AllocaInst>(I))
            continue;
          errs() << "\t" << (isa<StoreInst>(I) ? "Write " : (isa<AllocaInst>(I) ? "Alloca " : "Read ")) << " | ";
          if ((dl = I.getDebugLoc())) {
            errs() << dl.getLine() << "," << dl.getCol();
          } else {
            errs() << F.getSubprogram()->getLine() << ",*";
          }
          errs() << " | ";
          V = I.getOperand(isa<StoreInst>(I) ? 1 : 0);
          if (isa<AllocaInst>(I)) {
            V = dyn_cast<Value>(&I);
          }
          errs() << VNF->getVarName(V);

          if (omittableInstructions.find(&I) != omittableInstructions.end()) {
            errs() << " | OMITTED";
          }
          errs() << "\n";
        }
      }
    }

    // Remove omittable instructions from profiling
    Instruction *DP_Instrumentation;
    for (Instruction *I : omittableInstructions) {
      if (isa<AllocaInst>(I)) {
        DP_Instrumentation = I->getNextNode()->getNextNode();
      } else {
        DP_Instrumentation = I->getPrevNode();
      }

      if (!DP_Instrumentation)
        continue;
      if (CallInst *call_inst = dyn_cast<CallInst>(DP_Instrumentation)) {
        if (Function *Fun = call_inst->getCalledFunction()) {
          string fn = Fun->getName().str();
          if (fn == "__dp_write" || fn == "__dp_read" || fn == "__dp_alloca") {
            DP_Instrumentation->eraseFromParent();
          }
        }
      }
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

    staticDependencyFile = new std::ofstream();
    std::string tmp(getenv("DOT_DISCOPOP_PROFILER"));
    tmp += "/static_dependencies.txt";
    staticDependencyFile->open(tmp.data(), std::ios_base::app);

    for (auto pair : conditionalBBDepMap) {
      for (auto s : pair.second) {
        *staticDependencyFile << s << "\n";
      }
    }
    for (auto pair1 : conditionalBBPairDepMap) {
      for (auto pair2 : pair1.second) {
        for (auto s : pair2.second) {
          *staticDependencyFile << s << "\n";
        }
      }
    }
    staticDependencyFile->flush();
    staticDependencyFile->close();

    if (DP_hybrid_DEBUG)
      errs() << "Done with function " << F.getName() << ":\n";
  }
  // DPInstrumentationOmission end
  return true;
}
