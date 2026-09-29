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
#include "StaticCalltree.hpp"
#include <mutex>
#include <atomic>


class StaticCallPathTree; // forward declaration

class StaticCallPathTreeNode {
    public:
        StaticCalltreeNode* base_node;
        const std::uint32_t path_id;
        std::mutex mtx;
        std::unordered_map<int32_t, std::uint32_t> state_transitions;

        std::vector<StaticCallPathTreeNode*> successors;  // use vectors due to the assumption, that a single path generally has only a small number of successors. Save time and space for creating and managing a hashset or similar.
        StaticCallPathTreeNode* prefix;

        StaticCallPathTreeNode(std::uint32_t path_id, StaticCalltreeNode* base_node):base_node(base_node), path_id(path_id), prefix(nullptr){};

        StaticCallPathTreeNode(std::uint32_t path_id, StaticCalltreeNode* base_node, StaticCallPathTreeNode* prefix):base_node(base_node), path_id(path_id), prefix(prefix){};

        ~StaticCallPathTreeNode();

        StaticCallPathTreeNode* get_or_register_successor(StaticCallPathTree* tree, StaticCalltreeNode* successor_node);

        void register_transition(int32_t trigger_instruction_id, std::uint32_t target_path_id);

        [[nodiscard]] std::string to_dot_string();
        [[nodiscard]] std::string get_path_string();
};


class StaticCallPathTree {
    private:

        std::atomic<std::uint32_t> next_free_path_id{0};
        //std::mutex next_free_path_id_mtx;




    public:
        StaticCallPathTreeNode* root = nullptr;
        std::vector<StaticCallPathTreeNode*> all_nodes;
        std::mutex all_nodes_mtx;

        StaticCallPathTree();
        StaticCallPathTree(std::uint32_t start_path_id); // so that ids don't overlap between modules
        ~StaticCallPathTree();
        std::string to_dot_string();

        [[nodiscard]] std::uint32_t get_next_free_path_id();
        std::uint32_t get_current_free_path_id(); // returns next free path id
        void register_node_in_all_nodes(StaticCallPathTreeNode* node_ptr);
};
