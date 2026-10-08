"""Helpers for the instrumentation tests.

The tests in this package compile a small program with the DiscoPoP compiler wrapper, stop clang
right after the pass has run (``-S -emit-llvm``) and inspect the resulting LLVM IR. That is the
earliest point at which the work of the pass is visible: everything below it -- the profiling run,
the dependency files, the pattern detection -- only ever sees the already instrumented program, so
a mistake made here shows up much later and only indirectly.

The IR is parsed textually rather than through a binding, so the tests need nothing beyond the
toolchain that has to be installed anyway.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

# A source location is packed into a single integer as (fileID << LIDSIZE) + lineNumber,
# see LIDSIZE / decodeLID in profiler/share/include/DPUtils.hpp.
LIDSIZE = 14
MAXLNO = 1 << LIDSIZE

#: Callbacks whose first argument is such a packed location.
LOCATION_CALLBACKS = frozenset(
    {
        "__dp_init",
        "__dp_finalize",
        "__dp_func_entry",
        "__dp_func_exit",
        "__dp_loop_entry",
        "__dp_loop_exit",
        "__dp_alloca",
        "__dp_new",
        "__dp_delete",
    }
)

#: Callbacks whose first argument is an instruction id instead. The pass writes the mapping from
#: those ids to source locations to .discopop/profiler/instructionID_to_lineID_mapping.txt, which
#: is where the later phases resolve them, and so do these tests.
INSTRUCTION_ID_CALLBACKS = frozenset({"__dp_read", "__dp_write", "__dp_call"})


def decode_lid(lid: int) -> Tuple[int, int]:
    """Split a packed DiscoPoP location into ``(file id, line number)``."""
    return lid >> LIDSIZE, lid % MAXLNO


def encode_lid(line: int, file_id: int = 1) -> int:
    """Pack ``line`` of file ``file_id`` the way the pass does."""
    return (file_id << LIDSIZE) + line


@dataclass(frozen=True)
class SourceLocation:
    file_id: int
    line: int
    column: int

    def __str__(self) -> str:
        return f"{self.file_id}:{self.line}:{self.column}"

    @classmethod
    def parse(cls, text: str) -> Optional["SourceLocation"]:
        """Parse ``file:line:column``. The pass writes ``*`` for instructions without a location."""
        parts = text.split(":")
        if len(parts) != 3:
            return None
        try:
            return cls(int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError:
            return None


@dataclass(frozen=True)
class Instruction:
    """One instruction of the instrumented module."""

    text: str
    function: str
    block: str
    #: index within the enclosing function, so that tests can talk about ordering
    index: int
    #: the id the pass assigned to this instruction through its !dp.md.instr.id metadata, if any
    instruction_id: Optional[int]


@dataclass(frozen=True)
class Call(Instruction):
    callee: str
    args: Tuple[str, ...]

    def arg_int(self, index: int) -> Optional[int]:
        """The ``index``-th argument as an integer, or ``None`` if it is not a literal."""
        if index >= len(self.args):
            return None
        # arguments look like "i32 16385" or "ptr @.str.4"
        value = self.args[index].split()[-1]
        try:
            return int(value)
        except ValueError:
            return None

    def required_arg_int(self, index: int) -> int:
        """Like :meth:`arg_int`, but for arguments the pass always emits as a literal."""
        value = self.arg_int(index)
        if value is None:
            raise AssertionError(f"argument {index} of {self.callee} is not a literal: {self.args}")
        return value

    def arg_pointer(self, index: int) -> Optional[str]:
        """The name of the global the ``index``-th argument points to, e.g. ``@.str.4``."""
        if index >= len(self.args):
            return None
        value = self.args[index].split()[-1]
        return value if value.startswith("@") else None


_DEFINE_RE = re.compile(r"^define\b.*?@(\"[^\"]+\"|[\w.$\-]+)\s*\(")
_LABEL_RE = re.compile(r"^([\w.$\-]+):")
_INSTR_ID_USE_RE = re.compile(r"!dp\.md\.instr\.id (![0-9]+)")
_INSTR_ID_DEF_RE = re.compile(r"^(![0-9]+) = !\{!\"dp\.md\.instr\.id:([0-9]+)\"\}")
_CALL_RE = re.compile(r"\b(?:call|invoke)\b[^@]*?@(\"[^\"]+\"|[\w.$\-]+)\s*\(")
_STRING_GLOBAL_RE = re.compile(r"^(@[\w.$\-]+) = .*?\bc\"((?:[^\"\\]|\\.)*)\"")


def _split_arguments(text: str, open_paren: int) -> Tuple[Tuple[str, ...], int]:
    """Split the argument list starting at ``open_paren`` into its top level arguments.

    Returns the arguments and the index just past the closing parenthesis. Nesting is tracked
    because an argument type can itself contain brackets, e.g. a function pointer or a struct type.
    """
    depth = 0
    args: List[str] = []
    current = ""
    for position in range(open_paren, len(text)):
        char = text[position]
        if char in "([{":
            depth += 1
            if depth == 1:
                continue
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                if current.strip():
                    args.append(current.strip())
                return tuple(args), position + 1
        if depth == 1 and char == ",":
            args.append(current.strip())
            current = ""
        else:
            current += char
    return tuple(args), len(text)


class InstrumentedProgram:
    """The instrumented LLVM IR of a compiled program, plus the side files the pass wrote."""

    def __init__(self, source: str, ir: str, directory: str) -> None:
        self.source = source
        self.source_lines = source.splitlines()
        self.ir = ir
        self.directory = directory
        self.instruction_locations = _read_instruction_locations(directory)
        self.file_mapping = _read_file_mapping(directory)
        self.functions, self.instructions, self.strings = _parse_ir(ir)

    # -- queries over the IR -------------------------------------------------------------------

    def calls(self, callee: Optional[str] = None, *, function: Optional[str] = None) -> List[Call]:
        """Every call to ``callee`` (all calls if omitted), optionally restricted to one function."""
        result = [instruction for instruction in self.instructions if isinstance(instruction, Call)]
        if callee is not None:
            result = [call for call in result if call.callee == callee]
        if function is not None:
            result = [call for call in result if call.function == function]
        return result

    def callback_counts(self, *, function: Optional[str] = None) -> Dict[str, int]:
        """How often each DiscoPoP callback is called, as ``{name: count}``."""
        counts: Dict[str, int] = {}
        for call in self.calls(function=function):
            if call.callee.startswith("__dp_"):
                counts[call.callee] = counts.get(call.callee, 0) + 1
        return counts

    def user_functions(self) -> List[str]:
        """The functions of the compiled program, without the helpers the pass itself added."""
        return [name for name in self.functions if not name.startswith("__dp_")]

    def blocks_of(self, function: str) -> List[str]:
        """The basic block labels of ``function``, in the order they appear."""
        blocks: List[str] = []
        for instruction in self.functions[function]:
            if instruction.block not in blocks:
                blocks.append(instruction.block)
        return blocks

    def string_value(self, name: Optional[str]) -> Optional[str]:
        """The content of the string constant ``name``, e.g. ``@.str.4`` -> ``"b"``."""
        if name is None:
            return None
        return self.strings.get(name)

    def result_register(self, instruction: Instruction) -> Optional[str]:
        """The register ``instruction`` assigns to, e.g. ``%call2``, if it assigns to one."""
        match = re.match(r"(%[\w.$\-]+) = ", instruction.text)
        return match.group(1) if match else None

    def operand_registers(self, instruction: Instruction) -> List[str]:
        """The registers ``instruction`` reads, i.e. every ``%name`` in it but its own result."""
        result = self.result_register(instruction)
        # everything from the first metadata marker on is !dbg and friends, not operands
        names = re.findall(r"%[\w.$\-]+", instruction.text.split("!", 1)[0])
        return [name for name in names if name != result]

    def definition_of(self, register: str, *, before: Instruction) -> Optional[Instruction]:
        """The instruction assigning ``register``, looked up in the function of ``before``."""
        for instruction in self.functions[before.function]:
            if instruction.index >= before.index:
                break
            if self.result_register(instruction) == register:
                return instruction
        return None

    def address_origin(self, call: Call, index: int = 1) -> Optional[Instruction]:
        """What produced the address ``call`` reports as its ``index``-th argument.

        The pass passes addresses as integers, so the argument is a ``ptrtoint`` of the pointer it
        actually means. This follows that chain back to the instruction the pointer came from --
        the allocation call, a ``load``, an ``alloca`` -- which is what a test wants to talk about.
        """
        if index >= len(call.args):
            return None
        instruction = self.definition_of(call.args[index].split()[-1], before=call)
        for _ in range(8):
            if instruction is None:
                return None
            body = instruction.text.split(" = ", 1)[-1].strip()
            if not body.startswith(("ptrtoint", "bitcast", "addrspacecast", "getelementptr")):
                return instruction
            operands = self.operand_registers(instruction)
            if not operands:
                return instruction
            instruction = self.definition_of(operands[0], before=instruction)
        return instruction

    def invoke_normal_destination(self, call: Call) -> Optional[str]:
        """The block an ``invoke`` continues in when its callee returns normally.

        ``None`` for an ordinary call. An ``invoke`` terminates its basic block, so instrumentation
        that has to run after the call cannot be appended to it; it belongs at the start of this
        block instead.

        LLVM prints the destinations of an ``invoke`` on a continuation line, which this parser
        sees as an instruction of its own, so the successor is searched as well.
        """
        pattern = re.compile(r"\bto label %([\w.$\-]+)\s+unwind label\b")
        candidates = [call, self.next_instruction(call)]
        for candidate in candidates:
            if candidate is None:
                continue
            match = pattern.search(candidate.text)
            if match:
                return match.group(1)
        return None

    def next_instruction(self, instruction: Instruction) -> Optional[Instruction]:
        """The instruction following ``instruction`` in its function, if there is one."""
        siblings = self.functions[instruction.function]
        position = instruction.index + 1
        return siblings[position] if position < len(siblings) else None

    def global_constructors(self) -> List[str]:
        """The functions registered in ``@llvm.global_ctors``, i.e. run before ``main``."""
        for line in self.ir.splitlines():
            if line.startswith("@llvm.global_ctors"):
                return re.findall(r"ptr @([\w.$\-]+)", line)
        return []

    def basic_block_dependencies(self) -> Dict[int, str]:
        """The table the pass hands to the runtime through ``__dp_add_bb_deps``.

        ``doFinalization`` collects the dependencies of the accesses whose instrumentation was
        omitted into one string, ``<id>=<deps>/<id>=<deps>/...``, where the ids are the ones
        reported by ``__dp_report_bb`` and ``__dp_report_bb_pair``. Since the individual
        ``__dp_read`` / ``__dp_write`` calls are gone, this string is the only remaining record of
        those dependencies.
        """
        table: Dict[int, str] = {}
        encoded = self.strings.get("@.dp_bb_deps")
        if encoded is None:
            return table
        for entry in encoded.split("/"):
            identifier, _, dependencies = entry.partition("=")
            if identifier.isdigit():
                table[int(identifier)] = dependencies
        return table

    def loop_metadata(self) -> List[Tuple[int, int, int]]:
        """``(file id, loop id, line)`` for every loop, from ``.discopop/profiler/loop_meta.txt``."""
        path = os.path.join(self.directory, ".discopop", "profiler", "loop_meta.txt")
        entries: List[Tuple[int, int, int]] = []
        if not os.path.exists(path):
            return entries
        with open(path) as metadata_file:
            for line in metadata_file:
                parts = line.split()
                if len(parts) == 3:
                    entries.append((int(parts[0]), int(parts[1]), int(parts[2])))
        return entries

    # -- locations -----------------------------------------------------------------------------

    def source_line(self, call: Call) -> Optional[int]:
        """The source line ``call`` reports, for both of the conventions the pass uses."""
        if call.callee in LOCATION_CALLBACKS:
            lid = call.arg_int(0)
            return None if lid is None else decode_lid(lid)[1]
        if call.callee in INSTRUCTION_ID_CALLBACKS:
            instruction_id = call.arg_int(0)
            if instruction_id is None:
                return None
            location = self.instruction_locations.get(instruction_id)
            return None if location is None else location.line
        return None

    def source_lines_of(self, callee: str, *, function: Optional[str] = None) -> List[int]:
        """The source lines reported by every call to ``callee``."""
        lines = [self.source_line(call) for call in self.calls(callee, function=function)]
        return [line for line in lines if line is not None]

    def line_of_marker(self, marker: str) -> int:
        """The 1-based number of the source line carrying ``// @<marker>``.

        Tests refer to source lines by name, so that editing a test program does not silently move
        the expectations of every test along with it.
        """
        # the lookahead keeps '@call' from also matching '@call_site'
        pattern = re.compile(rf"//\s*@{re.escape(marker)}(?!\w)")
        matches = [number for number, line in enumerate(self.source_lines, start=1) if pattern.search(line)]
        if len(matches) != 1:
            raise AssertionError(f"expected exactly one line marked '// @{marker}', found {len(matches)}")
        return matches[0]

    def describe(self) -> str:
        """A readable dump of the inserted callbacks, for failure messages."""
        lines = []
        for call in self.calls():
            if not call.callee.startswith("__dp_"):
                continue
            reported = self.source_line(call)
            suffix = "" if reported is None else f"  -> line {reported}"
            lines.append(f"  {call.function}/{call.block}: {call.callee}({', '.join(call.args)}){suffix}")
        return "\n".join(lines)


def _parse_ir(ir: str) -> Tuple[Dict[str, List[Instruction]], List[Instruction], Dict[str, str]]:
    metadata: Dict[str, int] = {}
    strings: Dict[str, str] = {}
    for line in ir.splitlines():
        match = _INSTR_ID_DEF_RE.match(line)
        if match:
            metadata[match.group(1)] = int(match.group(2))
            continue
        string_match = _STRING_GLOBAL_RE.match(line)
        if string_match:
            # IR escapes bytes as \xx; only the terminating \00 matters here
            strings[string_match.group(1)] = string_match.group(2).replace("\\00", "")

    functions: Dict[str, List[Instruction]] = {}
    instructions: List[Instruction] = []
    current_function: Optional[str] = None
    current_block = ""
    index = 0

    for raw_line in ir.splitlines():
        line = raw_line.strip()
        if current_function is None:
            match = _DEFINE_RE.match(line)
            if match:
                current_function = match.group(1).strip('"')
                current_block = ""
                index = 0
                functions[current_function] = []
            continue
        if line == "}":
            current_function = None
            continue
        if not line or line.startswith(";"):
            continue
        label = _LABEL_RE.match(line)
        if label:
            current_block = label.group(1)
            continue

        instruction_id = None
        id_use = _INSTR_ID_USE_RE.search(line)
        if id_use:
            instruction_id = metadata.get(id_use.group(1))

        call = _CALL_RE.search(line)
        if call:
            arguments, _ = _split_arguments(line, call.end() - 1)
            instruction: Instruction = Call(
                text=line,
                function=current_function,
                block=current_block,
                index=index,
                instruction_id=instruction_id,
                callee=call.group(1).strip('"'),
                args=arguments,
            )
        else:
            instruction = Instruction(
                text=line,
                function=current_function,
                block=current_block,
                index=index,
                instruction_id=instruction_id,
            )
        functions[current_function].append(instruction)
        instructions.append(instruction)
        index += 1

    return functions, instructions, strings


def _read_instruction_locations(directory: str) -> Dict[int, SourceLocation]:
    path = os.path.join(directory, ".discopop", "profiler", "instructionID_to_lineID_mapping.txt")
    locations: Dict[int, SourceLocation] = {}
    if not os.path.exists(path):
        return locations
    with open(path) as mapping_file:
        for line in mapping_file:
            parts = line.split()
            if len(parts) < 2:
                continue
            location = SourceLocation.parse(parts[1])
            if location is not None:
                locations[int(parts[0])] = location
    return locations


def _read_file_mapping(directory: str) -> Dict[int, str]:
    path = os.path.join(directory, ".discopop", "FileMapping.txt")
    mapping: Dict[int, str] = {}
    if not os.path.exists(path):
        return mapping
    with open(path) as mapping_file:
        for line in mapping_file:
            parts = line.split()
            if len(parts) >= 2:
                mapping[int(parts[0])] = parts[1]
    return mapping


def compile_to_ir(
    source: str,
    *,
    directory: str,
    name: str = "test.cpp",
    extra_arguments: Sequence[str] = (),
) -> InstrumentedProgram:
    """Compile ``source`` with the instrumentation pass and return the resulting IR.

    ``directory`` becomes the project root, so that the pass treats the program as project code
    rather than as a library, and it holds the ``.discopop`` directory the pass writes to.
    """
    wrapper = shutil.which("discopop_cxx")
    if wrapper is None:
        raise AssertionError(
            "discopop_cxx not found on PATH. Activate the venv and install the profiler "
            "('pip install ./profiler', without -e) before running these tests."
        )

    source_path = os.path.join(directory, name)
    with open(source_path, "w") as source_file:
        source_file.write(source)

    environment = dict(os.environ)
    environment["DOT_DISCOPOP"] = os.path.join(directory, ".discopop")
    environment["DP_PROJECT_ROOT_DIR"] = directory

    output = "instrumented.ll"
    result = subprocess.run(
        [wrapper, "-S", "-emit-llvm", name, "-o", output, *extra_arguments],
        cwd=directory,
        env=environment,
        capture_output=True,
        text=True,
    )
    output_path = os.path.join(directory, output)
    if result.returncode != 0 or not os.path.exists(output_path):
        raise AssertionError(
            f"instrumented compilation of {name} failed (exit {result.returncode})\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )

    with open(output_path) as ir_file:
        ir = ir_file.read()
    return InstrumentedProgram(source, ir, directory)


class InstrumentationTestCase(unittest.TestCase):
    """Compiles ``SOURCE`` once for the whole class and exposes it as ``self.program``.

    Compiling is the expensive part of these tests, so every assertion about one program shares a
    single compilation. Set ``DP_TEST_KEEP_ARTIFACTS=y`` to keep the build directory around; its
    path is printed when the class is torn down.
    """

    SOURCE: str = ""
    program: InstrumentedProgram

    _temporary_directory: str

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.mkdtemp(prefix="dp_instrumentation_")
        source = textwrap.dedent(cls.SOURCE).strip("\n") + "\n"
        cls.program = compile_to_ir(source, directory=cls._temporary_directory)

    @classmethod
    def tearDownClass(cls) -> None:
        if os.environ.get("DP_TEST_KEEP_ARTIFACTS", "").lower() in ("y", "yes", "1"):
            print(f"\nkept instrumentation test artifacts in {cls._temporary_directory}")
            return
        shutil.rmtree(cls._temporary_directory, ignore_errors=True)

    # -- assertions shared by the test cases ---------------------------------------------------

    def assertInstrumentsLine(self, callee: str, marker: str, *, function: Optional[str] = None) -> None:
        """Assert that some call to ``callee`` reports the line marked with ``// @<marker>``."""
        expected = self.program.line_of_marker(marker)
        reported = self.program.source_lines_of(callee, function=function)
        self.assertIn(
            expected,
            reported,
            f"{callee} does not report line {expected} ('{marker}'); "
            f"reported lines: {reported}\n{self.program.describe()}",
        )

    def assertDoesNotInstrumentLine(self, callee: str, marker: str, *, function: Optional[str] = None) -> None:
        """Assert that no call to ``callee`` reports the line marked with ``// @<marker>``."""
        unexpected = self.program.line_of_marker(marker)
        reported = self.program.source_lines_of(callee, function=function)
        self.assertNotIn(
            unexpected,
            reported,
            f"{callee} unexpectedly reports line {unexpected} ('{marker}')\n{self.program.describe()}",
        )

    def assertCallbackCount(self, callee: str, expected: int, *, function: Optional[str] = None) -> None:
        calls = self.program.calls(callee, function=function)
        self.assertEqual(
            expected,
            len(calls),
            f"expected {expected} call(s) to {callee}, found {len(calls)}\n{self.program.describe()}",
        )
