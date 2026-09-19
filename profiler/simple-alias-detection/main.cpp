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

#include "clang/Frontend/TextDiagnostic.h"
#include <clang/ASTMatchers/ASTMatchFinder.h>
#include <clang/ASTMatchers/ASTMatchers.h>
#include <clang/Frontend/FrontendActions.h>
#include <clang/Tooling/CommonOptionsParser.h>
#include <clang/Tooling/Tooling.h>

#include "BinCallBack.hpp"

using namespace llvm;
using namespace clang;
using namespace clang::tooling;
using namespace clang;
using namespace clang::ast_matchers;

static llvm::cl::OptionCategory SimpleStatement("simpleStatement");

int main(int argc, const char **argv) {
  /*
   * Create a list of all declaration statement and binary operators within the
   * source file. This information is used as the basis of the simple alias
   * detection.
   */
  CommonOptionsParser op(argc, argv, SimpleStatement);
  ClangTool Tool(op.getCompilations(), op.getSourcePathList());
  StatementMatcher bin_stmt =
      clang::ast_matchers::binaryOperator(anything(), isExpansionInMainFile()).bind("simpleStatement");
  StatementMatcher decl_stmt =
      clang::ast_matchers::declStmt(anything(), isExpansionInMainFile()).bind("simpleStatement");
  MatchFinder finder;
  BinCallBack bin_cb;
  finder.addMatcher(bin_stmt, &bin_cb);
  finder.addMatcher(decl_stmt, &bin_cb);
  auto action = newFrontendActionFactory(&finder);
  // run actions on AST
  return Tool.run(action.get());
}
