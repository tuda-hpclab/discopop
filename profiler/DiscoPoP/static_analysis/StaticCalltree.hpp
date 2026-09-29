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
#include <iostream>
#include <string>
#include <unordered_map>
#include <stdint.h>
#include <vector>
#include <algorithm>

class StaticCalltreeNode {
    private:
        uint32_t node_id;
        bool type; // 0: Function; 1: Call instruction
//        TODO: other types for loop iterations might be a good idea!
        std::string functionName;
        int32_t instructionID;
        std::string label;  // precomputed once in the constructor; see get_label()

    public:
        std::unordered_map<int32_t, std::vector<StaticCalltreeNode*>> successors;  // first element of the pairs is the trigger instructionID for the transition
        std::vector<StaticCalltreeNode*> predecessors;
        StaticCalltreeNode(uint32_t node_id_arg, bool type_arg, std::string functionName_arg, int32_t instructionID_arg):node_id(node_id_arg),type(type_arg),functionName(functionName_arg),instructionID(instructionID_arg){
            // type 0: function -> functionName; type 1: call instruction -> "call_<instructionID>"
            label = type ? ("call_" + std::to_string(instructionID)) : functionName;
        };
        void print();
        const std::string& get_label();
        bool get_type();
        void register_successor(StaticCalltreeNode* succ, int32_t trigger_instructionID);
};

class StaticCalltree {
    private:
        uint32_t node_count = 0;

    public:

        std::unordered_map<std::string, StaticCalltreeNode*> function_map;
        std::unordered_map<int32_t, StaticCalltreeNode*> instruction_map;
        StaticCalltree();
        ~StaticCalltree();
        StaticCalltreeNode* get_or_insert_function_node(std::string function_name);
        StaticCalltreeNode* get_or_insert_function_node(std::string function_nam, std::string loop_iteration_instance);
        StaticCalltreeNode* get_or_insert_instruction_node(int32_t instructionID);
        void print();
        std::string to_dot_string();
        void addEdge(StaticCalltreeNode* source, StaticCalltreeNode* target, int32_t trigger_instructionID);
};
