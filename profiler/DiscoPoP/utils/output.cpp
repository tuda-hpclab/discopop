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

#include "utils/output.hpp"

#include <algorithm>
#include <fstream>
#include <map>
#include <set>
#include <string>

#include "llvm/IR/Metadata.h"

#include "DPUtils.hpp"
#include "utils/profiler_files.hpp"

using cu_output::XmlEscape;
using llvm::cast;
using llvm::MDNode;
using llvm::MDString;
using llvm::StringRef;

namespace {

// writes the CU graph of one function into Data.xml
class CUGraphWriter {
 public:
  CUGraphWriter(std::ofstream& out_cus, const std::map<std::string, std::string>& loop_start_lines)
      : out_cus_(out_cus), loop_start_lines_(loop_start_lines) {}

  void PrintTree(Node* node, bool is_root);

 private:
  std::string GetLineNumbersString(const std::set<LID>& line_numbers);

  std::string GetChildrenNodesString(Node* node);

  void PrintNode(Node* node, bool is_root);

  std::ofstream& out_cus_;
  const std::map<std::string, std::string>& loop_start_lines_;
};

}  // namespace

/********** Output functions *********/
std::string cu_output::XmlEscape(std::string data) {
  std::string::size_type pos = 0;
  for (;;) {
    pos = data.find_first_of("\"&<>", pos);
    if (pos == std::string::npos) {
      break;
    }
    std::string replacement;
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
      default: {
      }
    }
    data.replace(pos, 1, replacement);
    pos += replacement.size();
  }
  return data;
}

void cu_output::WriteCuGraph(Node* root, const std::map<std::string, std::string>& loop_start_lines) {
  // OriginalVariables.txt stays empty, but is created as it always was
  std::ofstream out_original_variables = profiler_files::Open("OriginalVariables.txt");
  std::ofstream out_cus = profiler_files::Open("Data.xml");

  out_cus << "<Nodes>" << "\n" << "\n";

  CUGraphWriter(out_cus, loop_start_lines).PrintTree(root, true);

  out_cus << "</Nodes>" << "\n" << "\n" << "\n";

  // closing flushes
  out_cus.close();
  out_original_variables.close();
}

std::string CUGraphWriter::GetLineNumbersString(const std::set<LID>& line_numbers) {
  std::string line = "";
  for (auto li : line_numbers) {
    const std::string temp = ',' + dputil::DecodeLid(li);
    if (temp != ",*") {
      if (line == "") {
        line = dputil::DecodeLid(li);
      } else {
        line = line + temp;
      }
    }
  }
  return line;
}

std::string CUGraphWriter::GetChildrenNodesString(Node* root) {
  std::string children_ids = "";
  int i = 0;
  std::for_each(root->children_nodes.begin(), root->children_nodes.end(), [&](Node* node) {
    if (i == 0) {
      children_ids = node->id;
      i++;
    } else {
      children_ids += "," + node->id;
    }
  });
  return children_ids;
}

void CUGraphWriter::PrintTree(Node* root, bool is_root) {
  PrintNode(root, is_root);

  std::for_each(root->children_nodes.begin(), root->children_nodes.end(), [&](Node* node) {
    if (node->type == NodeTypes::kFunc) {
      is_root = false;
    }
    PrintTree(node, is_root);
  });
}

void CUGraphWriter::PrintNode(Node* root, bool /*is_root*/) {
  if (root->name.find("llvm")) {
    std::string start = "";
    if (root->type == NodeTypes::kLoop) {
      auto loop_start = loop_start_lines_.find(root->id);
      start = loop_start != loop_start_lines_.end() ? loop_start->second : "";
    } else {
      start = dputil::DecodeLid(root->start_line);
    }
    out_cus_ << "\t<Node"
             << " id=\"" << XmlEscape(root->id) << "\""
             << " type=\"" << root->type << "\""
             << " name=\"" << XmlEscape(root->name) << "\""
             << " startsAtLine = \"" << start << "\""
             << " endsAtLine = \"" << dputil::DecodeLid(root->end_line) << "\""
             << ">" << "\n";
    out_cus_ << "\t\t<childrenNodes>" << GetChildrenNodesString(root) << "</childrenNodes>" << "\n";
    if (root->type == NodeTypes::kFunc || root->type == NodeTypes::kDummy) {
      out_cus_ << "\t\t<funcArguments>" << "\n";
      for (const auto& ai : root->arguments_list) {
        out_cus_ << "\t\t\t<arg type=\"" << XmlEscape(ai.type) << "\""
                 << " defLine=\"" << XmlEscape(ai.def_line) << "\""
                 << " accessMode=\"" << (ai.read_access ? "R" : "") << (ai.write_access ? "W" : "") << "\">"
                 << XmlEscape(ai.name) << "</arg>" << "\n";
      }
      out_cus_ << "\t\t</funcArguments>" << "\n";

      std::string rl_vals = "";
      for (auto rl : root->return_lines) {
        rl_vals += dputil::DecodeLid(rl) + ", ";
      }
      out_cus_ << "\t\t<funcReturnLines>" << rl_vals << "</funcReturnLines>" << "\n";
    }

    if (root->type == NodeTypes::kCu) {
      CU* cu = static_cast<CU*>(root);
      out_cus_ << "\t\t<BasicBlockID>" << cu->bb_id << "</BasicBlockID>" << "\n";
      out_cus_ << "\t\t<readDataSize>" << cu->read_data_size << "</readDataSize>" << "\n";
      out_cus_ << "\t\t<writeDataSize>" << cu->write_data_size << "</writeDataSize>" << "\n";
      out_cus_ << "\t\t<performsFileIO>" << cu->performs_file_io << "</performsFileIO>" << "\n";

      out_cus_ << "\t\t<instructionsCount>" << cu->instructions_count << "</instructionsCount>" << "\n";
      out_cus_ << "\t\t<instructionLines count=\"" << (cu->instructions_line_numbers).size() << "\">"
               << GetLineNumbersString(cu->instructions_line_numbers) << "</instructionLines>" << "\n";
      out_cus_ << "\t\t<readPhaseLines count=\"" << (cu->read_phase_line_numbers).size() << "\">"
               << GetLineNumbersString(cu->read_phase_line_numbers) << "</readPhaseLines>" << "\n";
      out_cus_ << "\t\t<writePhaseLines count=\"" << (cu->write_phase_line_numbers).size() << "\">"
               << GetLineNumbersString(cu->write_phase_line_numbers) << "</writePhaseLines>" << "\n";
      out_cus_ << "\t\t<returnInstructions count=\"" << (cu->return_instructions).size() << "\">"
               << GetLineNumbersString(cu->return_instructions) << "</returnInstructions>" << "\n";
      out_cus_ << "\t\t<successors>" << "\n";
      for (const auto& suc_cu_i : cu->successor_cus) {
        out_cus_ << "\t\t\t<CU>" << suc_cu_i << "</CU>" << "\n";
      }
      out_cus_ << "\t\t</successors>" << "\n";

      out_cus_ << "\t\t<localVariables>" << "\n";
      for (const auto& lvi : cu->local_variable_names) {
        out_cus_ << "\t\t\t<local type=\"" << XmlEscape(lvi.type) << "\""
                 << " defLine=\"" << XmlEscape(lvi.def_line) << "\""
                 << " accessMode=\"" << (lvi.read_access ? "R" : "") << (lvi.write_access ? "W" : "") << "\">"
                 << XmlEscape(lvi.name) << "</local>" << "\n";
      }
      out_cus_ << "\t\t</localVariables>" << "\n";

      out_cus_ << "\t\t<globalVariables>" << "\n";
      for (const auto& gvi : cu->global_variable_names) {
        out_cus_ << "\t\t\t<global type=\"" << XmlEscape(gvi.type) << "\""
                 << " defLine=\"" << XmlEscape(gvi.def_line) << "\""
                 << " accessMode=\"" << (gvi.read_access ? "R" : "") << (gvi.write_access ? "W" : "") << "\">"
                 << XmlEscape(gvi.name) << "</global>" << "\n";
      }
      out_cus_ << "\t\t</globalVariables>" << "\n";

      out_cus_ << "\t\t<callsNode>" << "\n";
      for (const auto& i : (cu->call_line_to_function_map)) {
        int idx = 0;  // for correctly accessing callLineToCallInstructionMap's value
        for (auto ii : i.second) {
          // get call instruction id
          MDNode* md = cu->call_line_to_call_instruction_map[i.first][idx]->getMetadata("dp.md.instr.id");
          std::string call_inst_id = "UNKNOWN";
          if (md && md->getNumOperands() > 0) {
            StringRef instruction_id_str = cast<MDString>(md->getOperand(0))->getString();
            call_inst_id = instruction_id_str.split(':').second.str();
          }
          // append to XML file
          out_cus_ << "\t\t\t<nodeCalled atLine=\"" << dputil::DecodeLid(i.first) << "\" callInstId=\"" << call_inst_id
                   << "\">" << ii->id << "</nodeCalled>" << std::endl;
          // specifica for recursive fucntions inside loops. (Mo 5.11.2019)
          out_cus_ << "\t\t\t\t<recursiveFunctionCall>" << ii->recursive_function_call << "</recursiveFunctionCall>"
                   << std::endl;
          idx++;
        }
      }
      out_cus_ << "\t\t</callsNode>" << "\n";
    }

    out_cus_ << "\t</Node>" << "\n" << "\n";
  }
}
/************** End of output functions *******************/
