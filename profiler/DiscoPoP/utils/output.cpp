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

/********** Output functions *********/
string DiscoPoP::xmlEscape(string data) {
  string::size_type pos = 0;
  for (;;) {
    pos = data.find_first_of("\"&<>", pos);
    if (pos == string::npos)
      break;
    string replacement;
    switch (data[pos]) {
    case '\"':
      replacement = "&quot;";
      break;
    case '&':
      replacement = "&amp;";
      break;
    case '<':
      replacement = "&lt;";
      break;
    case '>':
      replacement = "&gt;";
      break;
    default:;
    }
    data.replace(pos, 1, replacement);
    pos += replacement.size();
  };
  return data;
}

void DiscoPoP::secureStream() {
  outOriginalVariables = new std::ofstream();
  std::string tmp(getenv("DOT_DISCOPOP_PROFILER"));
  tmp += "/OriginalVariables.txt";
  outOriginalVariables->open(tmp.data(), std::ios_base::app);

  outCUs = new std::ofstream();
  std::string tmp2(getenv("DOT_DISCOPOP_PROFILER"));
  tmp2 += "/Data.xml";
  outCUs->open(tmp2.data(), std::ios_base::app);
}

string DiscoPoP::getLineNumbersString(set<int> LineNumbers) {
  string line = "";
  for (auto li : LineNumbers) {
    std::string temp = ',' + dputil::decodeLID(li);
    if (temp != ",*") {
      if (line == "") {
        line = dputil::decodeLID(li);
      } else {
        line = line + temp;
      }
    }
  }
  return line;
}

string DiscoPoP::getChildrenNodesString(Node *root) {
  string childrenIDs = "";
  int i = 0;
  std::for_each(root->childrenNodes.begin(), root->childrenNodes.end(), [&](Node *node) {
    if (i == 0) {
      childrenIDs = node->ID;
      i++;
    } else {
      childrenIDs += "," + node->ID;
    }
  });
  return childrenIDs;
}

void DiscoPoP::printData(Node *root) {
  *outCUs << "<Nodes>" << "\n" << "\n";

  printTree(root, true);

  *outCUs << "</Nodes>" << "\n" << "\n" << "\n";

  closeOutputFiles();
}

void DiscoPoP::printTree(Node *root, bool isRoot) {
  printNode(root, isRoot);

  std::for_each(root->childrenNodes.begin(), root->childrenNodes.end(), [&](Node *node) {
    if (node->type == nodeTypes::func) {
      isRoot = false;
    }
    printTree(node, isRoot);
  });
}

void DiscoPoP::printNode(Node *root, bool isRoot) {
  if (root->name.find("llvm")) {
    string start = "";
    if (root->type == nodeTypes::loop) {
      start = loopStartLines[root->ID];
    } else {
      start = dputil::decodeLID(root->startLine);
    }
    *outCUs << "\t<Node"
            << " id=\"" << xmlEscape(root->ID) << "\""
            << " type=\"" << root->type << "\""
            << " name=\"" << xmlEscape(root->name) << "\""
            << " startsAtLine = \"" << start << "\""
            << " endsAtLine = \"" << dputil::decodeLID(root->endLine) << "\""
            << ">" << "\n";
    *outCUs << "\t\t<childrenNodes>" << getChildrenNodesString(root) << "</childrenNodes>" << "\n";
    if (root->type == nodeTypes::func || root->type == nodeTypes::dummy) {
      *outCUs << "\t\t<funcArguments>" << "\n";
      for (auto ai : root->argumentsList) {
        *outCUs << "\t\t\t<arg type=\"" << xmlEscape(ai.type) << "\""
                << " defLine=\"" << xmlEscape(ai.defLine) << "\""
                << " accessMode=\"" << (ai.readAccess ? "R" : "") << (ai.writeAccess ? "W" : "") << "\">"
                << xmlEscape(ai.name) << "</arg>" << "\n";
      }
      *outCUs << "\t\t</funcArguments>" << "\n";

      string rlVals = "";
      for (auto rl : root->returnLines) {
        rlVals += dputil::decodeLID(rl) + ", ";
      }
      *outCUs << "\t\t<funcReturnLines>" << rlVals << "</funcReturnLines>" << "\n";
    }

    if (root->type == nodeTypes::cu) {
      CU *cu = static_cast<CU *>(root);
      *outCUs << "\t\t<BasicBlockID>" << cu->BBID << "</BasicBlockID>" << "\n";
      *outCUs << "\t\t<readDataSize>" << cu->readDataSize << "</readDataSize>" << "\n";
      *outCUs << "\t\t<writeDataSize>" << cu->writeDataSize << "</writeDataSize>" << "\n";
      *outCUs << "\t\t<performsFileIO>" << cu->performsFileIO << "</performsFileIO>" << "\n";

      *outCUs << "\t\t<instructionsCount>" << cu->instructionsCount << "</instructionsCount>" << "\n";
      *outCUs << "\t\t<instructionLines count=\"" << (cu->instructionsLineNumbers).size() << "\">"
              << getLineNumbersString(cu->instructionsLineNumbers) << "</instructionLines>" << "\n";
      *outCUs << "\t\t<readPhaseLines count=\"" << (cu->readPhaseLineNumbers).size() << "\">"
              << getLineNumbersString(cu->readPhaseLineNumbers) << "</readPhaseLines>" << "\n";
      *outCUs << "\t\t<writePhaseLines count=\"" << (cu->writePhaseLineNumbers).size() << "\">"
              << getLineNumbersString(cu->writePhaseLineNumbers) << "</writePhaseLines>" << "\n";
      *outCUs << "\t\t<returnInstructions count=\"" << (cu->returnInstructions).size() << "\">"
              << getLineNumbersString(cu->returnInstructions) << "</returnInstructions>" << "\n";
      *outCUs << "\t\t<successors>" << "\n";
      for (auto sucCUi : cu->successorCUs) {
        *outCUs << "\t\t\t<CU>" << sucCUi << "</CU>" << "\n";
      }
      *outCUs << "\t\t</successors>" << "\n";

      *outCUs << "\t\t<localVariables>" << "\n";
      for (auto lvi : cu->localVariableNames) {
        *outCUs << "\t\t\t<local type=\"" << xmlEscape(lvi.type) << "\""
                << " defLine=\"" << xmlEscape(lvi.defLine) << "\""
                << " accessMode=\"" << (lvi.readAccess ? "R" : "") << (lvi.writeAccess ? "W" : "") << "\">"
                << xmlEscape(lvi.name) << "</local>" << "\n";
      }
      *outCUs << "\t\t</localVariables>" << "\n";

      *outCUs << "\t\t<globalVariables>" << "\n";
      for (auto gvi : cu->globalVariableNames) {
        *outCUs << "\t\t\t<global type=\"" << xmlEscape(gvi.type) << "\""
                << " defLine=\"" << xmlEscape(gvi.defLine) << "\""
                << " accessMode=\"" << (gvi.readAccess ? "R" : "") << (gvi.writeAccess ? "W" : "") << "\">"
                << xmlEscape(gvi.name) << "</global>" << "\n";
      }
      *outCUs << "\t\t</globalVariables>" << "\n";

      *outCUs << "\t\t<callsNode>" << "\n";
      for (auto i : (cu->callLineTofunctionMap)) {
        int idx = 0;  // for correctly accessing callLineToCallInstructionMap's value
        for (auto ii : i.second) {
          // get call instruction id
          MDNode *md = cu->callLineToCallInstructionMap[i.first][idx]->getMetadata("dp.md.instr.id");
          string callInstId = "UNKNOWN";
          if(md && md->getNumOperands() > 0){
            StringRef instruction_id_str = cast<MDString>(md->getOperand(0))->getString();
            callInstId = instruction_id_str.split(':').second.str();
          }
          // append to XML file
          *outCUs << "\t\t\t<nodeCalled atLine=\"" << dputil::decodeLID(i.first) << "\" callInstId=\"" << callInstId << "\">" << ii->ID << "</nodeCalled>"
                  << endl;
          // specifica for recursive fucntions inside loops. (Mo 5.11.2019)
          *outCUs << "\t\t\t\t<recursiveFunctionCall>" << ii->recursiveFunctionCall << "</recursiveFunctionCall>"
                  << endl;
          idx++;
        }
      }
      *outCUs << "\t\t</callsNode>" << "\n";
    }

    *outCUs << "\t</Node>" << "\n" << "\n";
  }
}

void DiscoPoP::closeOutputFiles() {

  if (outCUs != NULL && outCUs->is_open()) {
    outCUs->flush();
    outCUs->close();
  }

  if (outOriginalVariables != NULL && outOriginalVariables->is_open()) {
    outOriginalVariables->flush();
    outOriginalVariables->close();
  }

  // delete outCUs;
}
/************** End of output functions *******************/
