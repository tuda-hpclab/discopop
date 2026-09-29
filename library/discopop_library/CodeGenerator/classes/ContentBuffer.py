# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import copy
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

from discopop_library.CodeGenerator.classes.Enums import PragmaPosition
from discopop_library.CodeGenerator.classes.Line import Line
from discopop_library.CodeGenerator.classes.Pragma import Pragma


class ContentBuffer(object):
    lines: List[Line]
    max_line_num: int  # used to determine width of padding
    file_id: int
    next_free_region_id = 0
    line_type: Any
    compile_result_buffer: str

    def __init__(self, file_id: int, source_code_path: Path, tab_width: int = 4, line_type: Any = Line) -> None:
        self.line_type = line_type
        self.file_id = file_id
        self.lines = []
        self.max_line_num = 0
        # load source code
        with open(source_code_path, "r") as f:
            lines = f.readlines()
            for idx, line in enumerate(lines):
                idx = idx + 1  # start with line number 1
                self.max_line_num = idx
                line_obj = self.line_type(idx, line_num=idx, content=line)
                self.lines.append(line_obj)
        self.compile_result_buffer = ""

    def print_lines(self) -> None:
        for line in self.lines:
            print(line)

    def __get_next_free_region_id(self) -> int:
        buffer = self.next_free_region_id
        self.next_free_region_id += 1
        return buffer

    def get_modified_source_code(self) -> str:
        result = ""
        for line in self.lines:
            if not line.content.endswith("\n"):
                line.content += "\n"
            result += line.content
        return result

    def append_line_before(self, parent_line_num: int, line: Line, match_indentation: bool = True) -> None:
        """Appends line before the specified parent_line_num"""
        for idx, potential_parent_line in enumerate(self.lines):
            if potential_parent_line.line_num == parent_line_num:
                if match_indentation:
                    line.content = potential_parent_line.get_indentation() + line.content
                self.lines.insert(idx, line)
                return

    def append_line_after(self, parent_line_num: int, line: Line, match_indentation: bool = True) -> None:
        """Appends line after the specified parent_line_num"""
        for idx, potential_parent_line in enumerate(self.lines):
            if potential_parent_line.line_num == parent_line_num:
                if idx + 1 < len(self.lines):
                    self.lines.insert(idx + 1, line)
                else:
                    self.lines.append(line)
                if match_indentation:
                    line.content = potential_parent_line.get_indentation() + line.content
                return

    def add_pragma(
        self,
        file_mapping: Dict[int, Path],
        pragma: Pragma,
        parent_regions: List[int],
        add_as_comment: bool = False,
        skip_compilation_check: bool = False,
        compile_check_command: Optional[str] = None,
        CC: str = "clang",
        CXX: str = "clang++",
        match_indentation: bool = True,
    ) -> bool:
        """insert pragma into the maintained list of source code lines.
        Returns True if the pragma resulted in a valid (resp. compilable) code transformation.
        Returns False if compilation of the modified code was not possible.
        In this case, no changes will be applied to the ContentBuffer Object."""
        if pragma.start_line is None or pragma.end_line is None:
            raise ValueError("Unsupported start or end line: ", pragma.start_line, "-", pragma.end_line)
        if pragma.file_id is None:
            raise ValueError("Unsupported file_id: ", pragma.file_id)
        if pragma.file_id != self.file_id:
            return True  # incorrect target file, ignore the pragma

        # Create a backup of the ContentBuffer so a failed insertion can be rolled back.
        # Both rollback paths below require a compilation check to have run: child pragmas are always
        # added with skip_compilation_check=True and can therefore never report failure, so a call
        # that skips the check cannot return False either. Deep-copying every Line of the file on
        # every single insertion dominated the patch generator (measured on LULESH with task
        # patterns: 22.9s of a 32.0s run), so the backup is only taken when it can be consumed.
        backup_lines = copy.deepcopy(self.lines) if not skip_compilation_check else None
        backup_max_line_num = self.max_line_num
        backup_file_id = self.file_id
        backup_next_free_region_id = self.next_free_region_id

        # construct line
        pragma_line = self.line_type(pragma.start_line)

        # adding as comment
        if add_as_comment:
            pragma_line.content = "//<DiscoPoP-IGNORED> "
        else:
            pragma_line.content = ""

        pragma_line.content += pragma.pragma_str
        pragma_line.belongs_to_regions = list(parent_regions)
        # create new region if necessary
        if len(pragma.children) > 0:
            region_id = self.__get_next_free_region_id()
            pragma_line.owns_region = region_id
            pragma_line.belongs_to_regions.append(region_id)

        if pragma.pragma_position == PragmaPosition.BEFORE_START:
            self.append_line_before(pragma.start_line, pragma_line)
        elif pragma.pragma_position == PragmaPosition.AFTER_START:
            self.append_line_after(pragma.start_line, pragma_line)
        elif pragma.pragma_position == PragmaPosition.BEFORE_END:
            self.append_line_before(pragma.end_line, pragma_line)
        elif pragma.pragma_position == PragmaPosition.AFTER_END:
            self.append_line_after(pragma.end_line, pragma_line)
        else:
            raise ValueError("Unsupported pragma position: ", pragma.pragma_position)

        # update belonging information of contained lines
        tmp_start_line = (
            pragma.start_line if pragma.pragma_position == PragmaPosition.BEFORE_START else pragma.start_line + 1
        )
        tmp_end_line = pragma.end_line + 1
        # A single pass over self.lines, instead of rescanning all of them once per line number in
        # the pragma's span. The nested variant was O(span * |lines|) - 33.8M iterations, ~7.4s, on
        # LULESH with task patterns, whose spans average 251 lines. Lines inserted for pragmas carry
        # line_num=None and were never matched by the previous equality check either, hence the guard.
        new_regions = pragma_line.belongs_to_regions
        for line in self.lines:
            if line.line_num is not None and tmp_start_line <= line.line_num < tmp_end_line:
                line.belongs_to_regions += [n for n in new_regions if n not in line.belongs_to_regions]

        # append children to lines (mark as contained in region)
        for child_pragma in pragma.children:
            # set skip_compilation_check to true since compiling children pragmas on their own might not be successful.
            # As an example for that, '#pragma omp declare target' can be mentioned
            successful = self.add_pragma(
                file_mapping,
                child_pragma,
                pragma_line.belongs_to_regions,
                add_as_comment=add_as_comment,
                skip_compilation_check=True,
                compile_check_command=compile_check_command,
                CC=CC,
                CXX=CXX,
            )

            if not successful:
                print(self.compile_result_buffer)
                assert backup_lines is not None, "rollback requested, but no backup was taken"
                self.lines = backup_lines
                self.next_free_region_id = backup_next_free_region_id
                self.file_id = backup_file_id
                self.max_line_num = backup_max_line_num
                return False

        if skip_compilation_check:
            return True

        # check if the applied changes resulted in a compilable source code
        # create a temporary file to store the modified file contents
        if str(file_mapping[self.file_id]).endswith(".c"):
            compiler = CC
            tmp_file_name = str(file_mapping[self.file_id]) + ".discopop_tmp.c"
        else:
            compiler = CXX
            tmp_file_name = str(file_mapping[self.file_id]) + ".discopop_tmp.cpp"
        tmp_file_out_name = str(file_mapping[self.file_id]) + ".discopop_tmp.o"

        with open(tmp_file_name, "w+") as f:
            f.write(self.get_modified_source_code())
            f.flush()
            f.close()

        if compile_check_command is None:
            result = subprocess.run(
                [compiler, "-c", "-fopenmp", tmp_file_name, "-o", tmp_file_out_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        else:
            saved_dir = os.getcwd()
            # prepare environment variables if requested
            pattern = re.compile(r"""((?:[^\s\"\']|\"[^\"]*\"|'[^']*')+)""")
            splitted_compile_check_command = pattern.split(compile_check_command)[
                1::2
            ]  # compile_check_command.split(" ")
            print("SPLITTED: ", splitted_compile_check_command)
            to_be_removed = []
            for idx, elem in enumerate(splitted_compile_check_command):
                if "=" in elem and not elem.startswith("-"):
                    # set environment variable
                    var_name = elem[: elem.index("=")]
                    var_value = elem[elem.index("=") + 1 :]
                    print("SET ENVIRONMENT VAR: ")
                    print("\t", var_name)
                    print("\t\t", var_value)
                    # unpack var_value
                    if var_value.startswith('"') and var_value.endswith('"') and len(var_value) > 1:
                        var_value = var_value[1:-1]
                    os.environ[var_name] = var_value

                    to_be_removed.append(idx)
            for idx in sorted(to_be_removed, reverse=True):
                splitted_compile_check_command.pop(idx)

            #            print("COMPILE COMMAND: ", splitted_compile_check_command)
            #           result = subprocess.run(
            #               splitted_compile_check_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            #           )

            print("COMPILE COMMAND: ", shlex.split(compile_check_command))
            result = subprocess.run(shlex.split(compile_check_command), shell=True)

            os.chdir(saved_dir)
        compilation_successful = result.returncode == 0

        if os.path.exists(tmp_file_name):
            os.remove(tmp_file_name)
        if compilation_successful:
            if os.path.exists(tmp_file_out_name):
                os.remove(tmp_file_out_name)

        # if not, reset ContentBuffer to the backup and return False
        if not compilation_successful:
            assert backup_lines is not None, "rollback requested, but no backup was taken"
            self.lines = backup_lines
            self.next_free_region_id = backup_next_free_region_id
            self.file_id = backup_file_id
            self.max_line_num = backup_max_line_num
            self.compile_result_buffer += result.stdout.decode("utf-8") + "\n"
            self.compile_result_buffer += result.stderr.decode("utf-8") + "\n"
            self.compile_result_buffer += "==> Skipped pragma insertion due to potential compilation errors!\n"
            print(self.compile_result_buffer)
            return False
        return True
