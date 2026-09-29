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

#include <clang/ASTMatchers/ASTMatchFinder.h>
#include <clang/ASTMatchers/ASTMatchersInternal.h>

using namespace clang::ast_matchers;
using namespace clang;

class BinCallBack : public MatchFinder::MatchCallback {
public:
  void run(const MatchFinder::MatchResult &r) override {
    const clang::Stmt *simpleStatement = r.Nodes.getNodeAs<Stmt>("simpleStatement");
    ASTContext *ctx = r.Context;
    simpleStatement->getSourceRange().getBegin().print(llvm::outs(), ctx->getSourceManager());
    llvm::outs() << ": ";
    simpleStatement->printPretty(llvm::outs(), nullptr, ctx->getPrintingPolicy());
    llvm::outs() << "\n\n";
  }
};
