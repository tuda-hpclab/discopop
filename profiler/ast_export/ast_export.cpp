// This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
//
// Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
//
// This software may be modified and distributed under the terms of
// the 3-Clause BSD License.  See the LICENSE file in the package base
// directory for details.

// Clang plugin that writes the JSON AST of the declarations the explorer queries.
//
// `clang -Xclang -ast-dump=json` writes every declaration reachable from the includes (libc, libstdc++, Boost, ...),
// which is tens of gigabytes for a single translation unit of a template heavy project, although the explorer only
// looks up nodes of the files in FileMapping.txt. The plugin writes only the declarations located in those files, in
// the format of the JSON dump (it uses clang's own JSONDumper), without ever producing the rest:
//
//   clang++ ... -fsyntax-only -Xclang -load -Xclang DiscoPoPASTExport-<llvm major>.so \
//       -Xclang -add-plugin -Xclang dp-ast-export \
//       -Xclang -plugin-arg-dp-ast-export -Xclang filemap=<FileMapping.txt> \
//       -Xclang -plugin-arg-dp-ast-export -Xclang root=<project directory> \
//       -Xclang -plugin-arg-dp-ast-export -Xclang out=<file the JSON is appended to>
//
// The output is a translation unit declaration holding the selected declarations. It is meant to be passed through
// scripts/filter_ast_dump.py, which removes the type nodes and makes the files of the locations explicit.
//
// Deviations from `-ast-dump=json` that the explorer does not notice: namespaces and linkage specifications are
// flattened into the translation unit (their declarations are written, they are not), typedefs and aliases (which
// carry nothing but type trees) are left out, and so is every implicit declaration (clang's builtin typedefs, the
// using directive of an unnamed namespace). The documentation comments of declarations are not written either.
//
// Without files in FileMapping.txt (not written yet), the declarations located below `root` are selected, which is
// the rule filter_ast_dump.py falls back to as well.

#include <cstddef>
#include <fstream>
#include <memory>
#include <set>
#include <string>
#include <system_error>
#include <unordered_map>
#include <utility>
#include <vector>

#include "clang/AST/ASTConsumer.h"
#include "clang/AST/ASTContext.h"
#include "clang/AST/DeclBase.h"
#include "clang/AST/DeclCXX.h"
#include "clang/AST/DeclTemplate.h"
#include "clang/AST/JSONNodeDumper.h"
#include "clang/Basic/Diagnostic.h"
#include "clang/Basic/SourceManager.h"
#include "clang/Frontend/CompilerInstance.h"
#include "clang/Frontend/FrontendPluginRegistry.h"
#include "llvm/ADT/SmallString.h"
#include "llvm/Support/FileSystem.h"
#include "llvm/Support/raw_ostream.h"

namespace {

// The paths of `FileMapping.txt` (lines "<id><TAB><path>") as written and with symbolic links resolved.
std::set<std::string> LoadFileMapping(const std::string& path) {
  std::set<std::string> files;
  std::ifstream in(path);
  std::string line;
  while (std::getline(in, line)) {
    const std::size_t tab = line.find('\t');
    if (tab == std::string::npos || tab + 1 >= line.size()) {
      continue;
    }
    const std::string name = line.substr(tab + 1);
    files.insert(name);
    llvm::SmallString<256> real;
    if (!llvm::sys::fs::real_path(name, real)) {
      files.insert(std::string(real));
    }
  }
  return files;
}

class ExportConsumer : public clang::ASTConsumer {
 public:
  ExportConsumer(std::set<std::string> mapped, std::string root, std::string out)
      : mapped_(std::move(mapped)), root_(std::move(root)), out_path_(std::move(out)) {
    if (!root_.empty() && root_.back() != '/') {
      root_ += '/';
    }
  }

  void HandleTranslationUnit(clang::ASTContext& ctx) override {
    std::error_code error;
    llvm::raw_fd_ostream out(out_path_, error, llvm::sys::fs::OF_Append);
    if (error) {
      // CreateASTConsumer checked this already; the file can only have vanished since
      llvm::errs() << "dp-ast-export: cannot open " << out_path_ << ": " << error.message() << "\n";
      return;
    }
    out << R"({"id": "0x1", "kind": "TranslationUnitDecl", "loc": {}, "range": {"begin": {}, "end": {}}, "inner": [)";
    first_ = true;
    Walk(ctx.getTranslationUnitDecl(), ctx, out);
    out << "]}\n";
  }

 private:
  bool Selected(clang::SourceLocation location, const clang::SourceManager& source_manager) {
    location = source_manager.getExpansionLoc(location);
    if (location.isInvalid()) {
      return false;
    }
    const clang::FileID file_id = source_manager.getFileID(location);
    const auto cached = cache_.find(file_id.getHashValue());
    if (cached != cache_.end()) {
      return cached->second;
    }
    bool selected = false;
    if (const auto file = source_manager.getFileEntryRefForID(file_id)) {
      const std::string name(file->getName());
      llvm::SmallString<256> real;
      const bool resolved = !llvm::sys::fs::real_path(name, real);
      if (mapped_.empty()) {
        selected = resolved && std::string(real).rfind(root_, 0) == 0;
      } else {
        selected = (resolved && mapped_.count(std::string(real)) > 0) || mapped_.count(name) > 0;
      }
    }
    cache_[file_id.getHashValue()] = selected;
    return selected;
  }

  void Walk(clang::DeclContext* context, clang::ASTContext& ctx, llvm::raw_ostream& out) {
    const clang::SourceManager& source_manager = ctx.getSourceManager();
    for (clang::Decl* decl : context->decls()) {
      if (decl->isImplicit()) {
        continue;
      }
      // namespaces and linkage specifications only group declarations, the explorer never asks for them
      if (auto* group = llvm::dyn_cast<clang::NamespaceDecl>(decl)) {
        Walk(group, ctx, out);
        continue;
      }
      if (auto* group = llvm::dyn_cast<clang::LinkageSpecDecl>(decl)) {
        Walk(group, ctx, out);
        continue;
      }
      // aliases only carry type trees, which are gigabytes for template metaprogramming
      if (llvm::isa<clang::TypedefNameDecl>(decl) || llvm::isa<clang::TypeAliasTemplateDecl>(decl)) {
        continue;
      }
      if (!Selected(decl->getLocation(), source_manager)) {
        continue;
      }
      std::string text;
      {
        llvm::raw_string_ostream stream(text);
        clang::JSONDumper dumper(stream, source_manager, ctx, ctx.getPrintingPolicy(), &ctx.getCommentCommandTraits());
        dumper.Visit(decl);
      }
      if (!first_) {
        out << ", ";
      }
      first_ = false;
      out << text;
    }
  }

  std::set<std::string> mapped_;
  std::string root_;
  std::string out_path_;
  // the selection per file, by the hash of its FileID (the files of a translation unit are few, its locations many)
  std::unordered_map<unsigned, bool> cache_;
  bool first_ = true;
};

class ExportAction : public clang::PluginASTAction {
 protected:
  std::unique_ptr<clang::ASTConsumer> CreateASTConsumer(clang::CompilerInstance& compiler,
                                                        llvm::StringRef /*file*/) override {
    // an error of the compilation, so that clang's exit code tells the caller that there is no output
    std::error_code error;
    llvm::raw_fd_ostream probe(out_, error, llvm::sys::fs::OF_Append);
    if (error) {
      clang::DiagnosticsEngine& diagnostics = compiler.getDiagnostics();
      diagnostics.Report(diagnostics.getCustomDiagID(clang::DiagnosticsEngine::Error,
                                                     "dp-ast-export: cannot open the output file '%0': %1"))
          << out_ << error.message();
      return nullptr;
    }
    return std::make_unique<ExportConsumer>(LoadFileMapping(file_mapping_), root_, out_);
  }

  bool ParseArgs(const clang::CompilerInstance& /*compiler*/, const std::vector<std::string>& args) override {
    for (const std::string& arg : args) {
      if (arg.rfind("filemap=", 0) == 0) {
        file_mapping_ = arg.substr(8);
      } else if (arg.rfind("root=", 0) == 0) {
        root_ = arg.substr(5);
      } else if (arg.rfind("out=", 0) == 0) {
        out_ = arg.substr(4);
      } else {
        llvm::errs() << "dp-ast-export: unknown argument " << arg << "\n";
        return false;
      }
    }
    if (out_.empty()) {
      llvm::errs() << "dp-ast-export: the argument out=<file> is required\n";
      return false;
    }
    return true;
  }

  ActionType getActionType() override { return AddAfterMainAction; }

 private:
  std::string file_mapping_;
  std::string root_;
  std::string out_;
};

}  // namespace

static clang::FrontendPluginRegistry::Add<ExportAction> dp_ast_export("dp-ast-export",
                                                                      "write the AST of the files of a FileMapping");
