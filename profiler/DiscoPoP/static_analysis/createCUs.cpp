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

void DiscoPoP::createCUs(Region *TopRegion, set<string> &globalVariablesSet, vector<CU *> &CUVector,
                         map<string, vector<CU *>> &BBIDToCUIDsMap, Node *root, LoopInfo &LI, ModuleAnalysisManager &MAM) {
  const DataLayout *DL = &ThisModule->getDataLayout(); // used to get data size of variables,
  // pointers, structs etc.
  Node *currentNode = root;
  CU *cu;
  int lid;
  string varName;
  bool isGlobalVar = false;
  string varType;
  set<string> suspiciousVariables;
  string basicBlockName;

  map<Loop *, Node *> loopToNodeMap;

  for (Region::block_iterator bb = TopRegion->block_begin(); bb != TopRegion->block_end(); ++bb) {

    // Get the closest loop where bb lives in.
    // (loop == NULL) if bb is not in any loop.
    Loop *loop = LI.getLoopFor(*bb);
    if (loop) {
      // if bb is in a loop and if we have already created a node for that loop,
      // assign it to currentNode.
      if (loopToNodeMap.find(loop) != loopToNodeMap.end()) {
        currentNode = loopToNodeMap[loop];
      }
      // else, create a new Node for the loop, add it as children of currentNode
      // and add it to the map.
      else {
        Node *n = new Node;
        n->type = nodeTypes::loop;
        n->parentNode = currentNode;
        currentNode->childrenNodes.push_back(n);

        loopToNodeMap[loop] = n;
        currentNode = n;
      }
    } else {
      // end of loops. go to the parent of the loop. may have to jump several
      // nodes in case of nested loops
      for (map<Loop *, Node *>::iterator it = loopToNodeMap.begin(); it != loopToNodeMap.end(); it++)
        if (it->second == currentNode) // current node found in loop map jump to its parent.
        {
          currentNode = currentNode->parentNode;
          it = loopToNodeMap.begin();    // search the whole map again for current node
          if (it->second == currentNode) // due to it++ we need to check first
            // element of map ourself
            currentNode = currentNode->parentNode;
        }
    }

    cu = new CU;

    if (bb->getName().size() == 0)
      bb->setName(cu->ID);

    cu->BBID = bb->getName().str();
    cu->BB = *bb;
    currentNode->childrenNodes.push_back(cu);
    vector<CU *> basicBlockCUVector;
    basicBlockCUVector.push_back(cu);
    BBIDToCUIDsMap.insert(pair<string, vector<CU *>>(bb->getName(), basicBlockCUVector));
    DILocalScope *scopeBuffer = NULL;

    for (BasicBlock::iterator instruction = (*bb)->begin(); instruction != (*bb)->end(); ++instruction) {
      // NOTE: 'instruction' --> '&*instruction'
      lid = getLID(&*instruction, fileID);
      basicBlockName = bb->getName().str();

      // Do not allow to combine Instructions from different scopes in the
      // source code.
      if ((&*instruction)->getDebugLoc()) {
        if ((&*instruction)->getDebugLoc()->getScope() != scopeBuffer) {
          // scopes are not equal

          int scopeIsParentOfBuffer = 0;
          if (scopeBuffer) {
            scopeIsParentOfBuffer = (&*instruction)->getDebugLoc()->getScope() == scopeBuffer->getScope();
          }

          if (scopeIsParentOfBuffer) {
            // allow a combination of two CU's if the second scope is the parent
            // of the first scope
          } else {
            // create a new CU. Do not allow to combine Instructions from
            // different scopes in the source code.

            // create new CU if the old one contains any instruction
            if ((!cu->readPhaseLineNumbers.empty()) || (!cu->writePhaseLineNumbers.empty()) ||
                (!cu->returnInstructions.empty())) {
              cu->startLine = *(cu->instructionsLineNumbers.begin());
              cu->endLine = *(cu->instructionsLineNumbers.rbegin());

              cu->basicBlockName = basicBlockName;
              CUVector.push_back(cu);
              suspiciousVariables.clear();
              CU *temp = cu; // keep current CU to make a reference to the successor CU
              cu = new CU;

              cu->BBID = bb->getName().str();
              cu->BB = *bb;

              currentNode->childrenNodes.push_back(cu);
              temp->successorCUs.push_back(cu->ID);
              BBIDToCUIDsMap[bb->getName().str()].push_back(cu);
            }
          }
          // update scopeBuffer
          scopeBuffer = (&*instruction)->getDebugLoc()->getScope();
        }
      }

      if (lid > 0) {
        cu->instructionsLineNumbers.insert(lid);
        cu->instructionsCount++;
        // find return instructions
        if (isa<ReturnInst>(instruction)) {
          cu->returnInstructions.insert(lid);
        }
        // find branches to return instructions, i.e. return statements
        else if (isa<BranchInst>(instruction)) {
          if ((cast<BranchInst>(instruction))->isUnconditional()) {
            if ((cast<BranchInst>(instruction))->getNumSuccessors() == 1) {
              BasicBlock *successorBB = (cast<BranchInst>(instruction))->getSuccessor(0);
              for (BasicBlock::iterator innerInstruction = successorBB->begin(); innerInstruction != successorBB->end();
                   ++innerInstruction) {
                if (isa<ReturnInst>(innerInstruction)) {
                  cu->returnInstructions.insert(lid);
                  break;
                }
              }
            }
          }
        }
        if (isa<StoreInst>(instruction)) {
          // get size of data written into memory by this store instruction
          Value *operand = instruction->getOperand(1);
          Type *Ty = operand->getType();
          unsigned u = DL->getTypeSizeInBits(Ty);
          cu->writeDataSize += u;
          varName = determineVariableName_static(&*instruction, isGlobalVar, false, "");
          varType = determineVariableType(&*instruction);
          suspiciousVariables.insert(varName);
          if (lid > 0)
            cu->writePhaseLineNumbers.insert(lid);
        } else if (isa<LoadInst>(instruction)) {
          // get size of data read from memory by this load instruction
          Type *Ty = instruction->getType();
          unsigned u = DL->getTypeSizeInBits(Ty);
          cu->readDataSize += u;
          varName = determineVariableName_static(&*instruction, isGlobalVar, false, "");
          if (suspiciousVariables.count(varName)) {
            // VIOLATION OF CAUTIOUS PROPERTY
            // it is a load instruction which read the value of a global
            // variable.
            // This global variable has already been stored previously.
            // A new CU should be created here.
            cu->readPhaseLineNumbers.erase(lid);
            cu->writePhaseLineNumbers.erase(lid);
            cu->instructionsLineNumbers.erase(lid);
            cu->instructionsCount--;
            if (cu->instructionsLineNumbers.empty()) {
              // cu->removeCU();
              cu->startLine = -1;
              cu->endLine = -1;
            } else {
              cu->startLine = *(cu->instructionsLineNumbers.begin());
              cu->endLine = *(cu->instructionsLineNumbers.rbegin());
            }
            cu->basicBlockName = basicBlockName;
            CUVector.push_back(cu);
            suspiciousVariables.clear();
            CU *temp = cu; // keep current CU to make a reference to the successor CU
            cu = new CU;

            cu->BBID = bb->getName().str();
            cu->BB = *bb;

            currentNode->childrenNodes.push_back(cu);
            temp->successorCUs.push_back(cu->ID);
            BBIDToCUIDsMap[bb->getName().str()].push_back(cu);
            if (lid > 0) {
              cu->readPhaseLineNumbers.insert(lid);
              cu->instructionsLineNumbers.insert(lid);
            }
          } else {
            if (globalVariablesSet.count(varName) || programGlobalVariablesSet.count(varName)) {
              if (lid > 0)
                cu->readPhaseLineNumbers.insert(lid);
            }
          }
        } else if (isa<CallInst>(instruction) || isa<InvokeInst>(instruction)) {
          // allow only a single function call per CU
          // create new CU if the old one contains any instruction
          if ((!cu->readPhaseLineNumbers.empty()) || (!cu->writePhaseLineNumbers.empty()) ||
              (!cu->returnInstructions.empty())) {
            cu->startLine = *(cu->instructionsLineNumbers.begin());
            cu->endLine = *(cu->instructionsLineNumbers.rbegin());

            cu->basicBlockName = basicBlockName;
            CUVector.push_back(cu);
            suspiciousVariables.clear();
            CU *temp = cu; // keep current CU to make a reference to the successor CU
            cu = new CU;

            cu->BBID = bb->getName().str();
            cu->BB = *bb;

            currentNode->childrenNodes.push_back(cu);
            temp->successorCUs.push_back(cu->ID);
            BBIDToCUIDsMap[bb->getName().str()].push_back(cu);
          }

          // get the name of the called function and check if a FileIO function
          // is called
          set<string> IOFunctions{
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

          CallBase *ci = cast<CallBase>(instruction);
          if (ci) {
            if (ci->getCalledFunction()) {
              if (ci->getCalledFunction()->hasName()) {
                if (find(IOFunctions.begin(), IOFunctions.end(), ci->getCalledFunction()->getName().str()) !=
                    IOFunctions.end()) {
                  // Called function performs FileIO
                  cu->performsFileIO = true;
                }
              }
            }
          }
        }
      }
    }
    if (cu->instructionsLineNumbers.empty()) {
      // cu->removeCU();
      cu->startLine = -1;
      cu->endLine = -1;
    } else {
      cu->startLine = *(cu->instructionsLineNumbers.begin());
      cu->endLine = *(cu->instructionsLineNumbers.rbegin());
    }

    cu->basicBlockName = basicBlockName;
    CUVector.push_back(cu);
    suspiciousVariables.clear();

    // check for call instructions in current basic block
    for (BasicBlock::iterator instruction = (*bb)->begin(); instruction != (*bb)->end(); ++instruction) {
      // Note: Don't create nodes for library functions (c++/llvm).
      LID lid = getLID(&*instruction, fileID);
      if (lid > 0) {
        if (isa<CallInst>(instruction) || isa<InvokeInst>(instruction)) {
          Function *f = nullptr;

          if(isa<CallInst>(instruction)){
            CallInst *ci = cast<CallInst>(instruction);
            f = ci->getCalledFunction();
          }
          else if(isa<InvokeInst>(instruction)){
            InvokeInst *ci = cast<InvokeInst>(instruction);
            f = ci->getCalledFunction();
          }

          string lid;
          if (f) {
            bool externalFunction = true;
            for (Function::iterator FI = f->begin(), FE = f->end(); FI != FE; ++FI) {
              externalFunction = false;
              auto tempBI = FI->begin();
              if (DebugLoc dl = tempBI->getDebugLoc()) {
                lid = to_string(dl->getLine());
              } else {
                if (tempBI->getFunction()->getSubprogram())
                  lid = to_string(tempBI->getFunction()->getSubprogram()->getLine());
                else {
                  lid = "LineNotFound";
                }
              }
              break;
            }
            if (externalFunction)
              continue;
          } else {
            lid = "LineNotFound";
          }

          Node *n = new Node;
          n->type = nodeTypes::dummy;
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
              string type_str;
              raw_string_ostream rso(type_str);
              (it->getType())->print(rso);
              Variable v(string(it->getName()), rso.str(), lid, true, true);
              n->argumentsList.push_back(v);
            }
          } else // get name of the indirect function which is called
          {
            Value* v = (cast<CallBase>(instruction))->getCalledOperand();
            Value *sv = v->stripPointerCasts();
            n->name = sv->getName().str();
          }

          // Recursive functions
          //CallGraphWrapperPass *CGWP = &(getAnalysis<CallGraphWrapperPass>());

          llvm::CallGraph &CG = MAM.getResult<llvm::CallGraphAnalysis>(*module_);

          //if (isRecursive(*f, CGWP->getCallGraph())) {
          if (isRecursive(*f, CG)) {
            int lid = getLID(&*instruction, fileID);
            n->recursiveFunctionCall = n->name + " " + dputil::decodeLID(lid) + ",";
          }

          vector<CU *> BBCUsVector = BBIDToCUIDsMap[bb->getName().str()];
          // locate the CU where this function call belongs
          for (auto i : BBCUsVector) {
            int lid = getLID(&*instruction, fileID);
            if (lid >= i->startLine && lid <= i->endLine) {
              i->instructionsLineNumbers.insert(lid);
              i->childrenNodes.push_back(n);
              i->callLineTofunctionMap[lid].push_back(n);
              i->callLineToCallInstructionMap[lid].push_back(&(*instruction));
              break;
            }
          }
        }
      }
    }
  }
}
