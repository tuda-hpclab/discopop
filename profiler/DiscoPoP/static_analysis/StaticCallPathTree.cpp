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

#include "StaticCallPathTree.hpp"

StaticCallPathTreeNode* StaticCallPathTreeNode::get_or_register_successor(StaticCallPathTree* tree, StaticCalltreeNode* successor_node){
    std::lock_guard<std::mutex> lg(mtx);
    // search for successor
    for(auto succ: successors){
        if(succ->base_node == successor_node){
            return succ;
        }
    }
    // register successor
    StaticCallPathTreeNode* new_node = new StaticCallPathTreeNode(tree->get_next_free_path_id(), successor_node, this);
    successors.push_back(new_node);
    return new_node;
}

StaticCallPathTreeNode::~StaticCallPathTreeNode(){
    for(auto succ: successors){
        delete succ;
    }
}

std::string StaticCallPathTreeNode::to_dot_string(){
    std::string result = "";
    result += std::to_string(path_id) + ";\n";
    for(auto succ: successors){
        result += std::to_string(path_id) + " -> " + std::to_string(succ->path_id) + ";\n";
        result += succ->to_dot_string();
    }
    return result;
}

std::string StaticCallPathTreeNode::get_path_string(){
    if(this->base_node == nullptr){
        return "";
    }
    std::string path_str = this->base_node->get_label();
    auto current = this->prefix;
    while(current->base_node != nullptr){
        path_str = current->base_node->get_label() + "-->" + path_str;
        current = current->prefix;
    }
    return path_str;
}

void StaticCallPathTreeNode::register_transition(int32_t trigger_instruction_id, const std::uint32_t target_path_id){
    std::lock_guard<std::mutex> lg(mtx);
    state_transitions[trigger_instruction_id] = target_path_id;
}






StaticCallPathTree::StaticCallPathTree(){
    root = new StaticCallPathTreeNode(get_next_free_path_id(), nullptr);
    register_node_in_all_nodes(root);
}

StaticCallPathTree::StaticCallPathTree(std::uint32_t start_path_id){
    // start counting paths from start_path_id
    next_free_path_id = start_path_id;
    root = new StaticCallPathTreeNode(get_next_free_path_id(), nullptr);
    register_node_in_all_nodes(root);
}

StaticCallPathTree::~StaticCallPathTree(){
    delete root;
}

std::string StaticCallPathTree::to_dot_string(){
    std::string result = "";
    result += "diGraph G {\n";
    result += root->to_dot_string();
    result += "}\n";
    return result;
}


 std::uint32_t StaticCallPathTree::get_next_free_path_id(){
    /*std::uint32_t buffer;
    {
        //std::lock_guard<std::mutex> lg(next_free_path_id_mtx);
        buffer = next_free_path_id;
        ++next_free_path_id;
    }
    return buffer;
    */
    return next_free_path_id.fetch_add(1);
}

std::uint32_t StaticCallPathTree::get_current_free_path_id(){
    return next_free_path_id.load();
}

void StaticCallPathTree::register_node_in_all_nodes(StaticCallPathTreeNode* node_ptr){
    all_nodes.push_back(node_ptr);
}
