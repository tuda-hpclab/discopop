"""Tests for the instrumentation the LLVM pass inserts.

Each test class compiles one small program and asserts on the callbacks the pass put into the
resulting LLVM IR: which ones were inserted, where they sit, and which source line and variable
they report. Source lines are referred to by the ``// @<marker>`` comments in the programs rather
than by number, so the programs stay editable.
"""

from .utilities import Call, InstrumentationTestCase


class TestLoopOverArray(InstrumentationTestCase):
    """The canonical case: a loop writing an array, with scalars around it."""

    SOURCE = """
        int main() {                      // @main
          int a = 0;                      // @scalar_init
          int b[10];
          for (int i = 0; i < 10; ++i) {  // @loop
            b[i] = a + i;                 // @array_write
          }
          return b[3];                    // @array_read
        }
        """

    def test_main_is_entered_and_exited_like_any_other_function(self) -> None:
        self.assertCallbackCount("__dp_func_entry", 1)
        self.assertInstrumentsLine("__dp_func_entry", "main")
        # the second argument marks the entry point of the program
        self.assertEqual(1, self.program.calls("__dp_func_entry")[0].arg_int(1))

        self.assertCallbackCount("__dp_func_exit", 1)
        self.assertInstrumentsLine("__dp_func_exit", "array_read")

    def test_the_runtime_is_not_started_from_the_program(self) -> None:
        # The runtime brings itself up from a .init_array entry of priority 101, before the
        # constructors of the target's global objects, so that their accesses are profiled too.
        # The pass inserting __dp_init anywhere would start it a second time.
        self.assertCallbackCount("__dp_init", 0)

    def test_the_runtime_is_not_shut_down_from_the_program(self) -> None:
        # The runtime writes its results from a .fini_array entry, after the destructors of the
        # target's global objects have run -- those are instrumented too and their accesses would
        # otherwise be lost. Nothing in the instrumented code calls __dp_finalize any more; only a
        # function that never returns still gets an explicit call, see runOnBasicBlock.cpp.
        self.assertCallbackCount("__dp_finalize", 0)

    def test_function_entry_precedes_everything_else(self) -> None:
        first = self.program.functions["main"][0]
        self.assertEqual(
            "__dp_func_entry",
            getattr(first, "callee", None),
            f"the first instruction of main is '{first.text}', so accesses before it go unreported",
        )

    def test_array_accesses_are_instrumented_at_their_source_lines(self) -> None:
        self.assertInstrumentsLine("__dp_write", "array_write")
        self.assertInstrumentsLine("__dp_read", "array_read")

    def test_instrumented_accesses_carry_the_variable_name(self) -> None:
        # The last argument is the name the later phases report the dependency under. An access
        # through a getelementptr keeps the name of the underlying variable behind a GEPRESULT_
        # prefix, which the gold standard tests in test/profiler expect to see as well.
        for callee in ("__dp_write", "__dp_read"):
            call = self.program.calls(callee)[0]
            name = self.program.string_value(call.arg_pointer(len(call.args) - 1))
            self.assertEqual("GEPRESULT_b", name, f"{callee} reports variable '{name}'")

    def test_scalar_locals_are_left_to_the_static_analysis(self) -> None:
        # Scalars that the pass can resolve statically are not instrumented individually; their
        # dependencies are reconstructed from the reported basic blocks. Only the array accesses
        # remain, so a regression that starts instrumenting scalars again shows up as extra calls.
        self.assertCallbackCount("__dp_write", 1)
        self.assertCallbackCount("__dp_read", 1)
        self.assertDoesNotInstrumentLine("__dp_write", "scalar_init")

    def test_every_reported_basic_block_is_reported_once(self) -> None:
        reports = self.program.calls("__dp_report_bb", function="main")
        blocks = [call.block for call in reports]
        identifiers = [call.arg_int(0) for call in reports]
        self.assertEqual(len(blocks), len(set(blocks)), f"a basic block is reported twice: {blocks}")
        self.assertEqual(
            len(identifiers),
            len(set(identifiers)),
            f"two basic blocks share a reported id: {list(zip(blocks, identifiers))}",
        )

    def test_the_loop_is_bracketed_by_entry_and_exit(self) -> None:
        self.assertCallbackCount("__dp_loop_entry", 1)
        self.assertCallbackCount("__dp_loop_exit", 1)
        self.assertInstrumentsLine("__dp_loop_entry", "loop")

        entry = self.program.calls("__dp_loop_entry")[0]
        exit_ = self.program.calls("__dp_loop_exit")[0]
        self.assertEqual(entry.arg_int(1), exit_.arg_int(1), "loop entry and exit report different loop ids")

    def test_the_stack_array_is_registered(self) -> None:
        # __dp_alloca tells the runtime which address range belongs to a stack variable
        self.assertCallbackCount("__dp_alloca", 1)
        alloca = self.program.calls("__dp_alloca")[0]
        self.assertEqual("b", self.program.string_value(alloca.arg_pointer(1)))
        # ten elements of four bytes each
        self.assertEqual(40, alloca.arg_int(4))
        self.assertEqual(10, alloca.arg_int(5))


class TestFunctionCall(InstrumentationTestCase):
    """A second function, so that entry, exit and call instrumentation become visible."""

    SOURCE = """
        int helper(int x) {               // @helper
          return x * 2;                   // @helper_return
        }

        int main() {                      // @main
          int values[4];
          for (int i = 0; i < 4; ++i) {
            values[i] = helper(i);        // @call
          }
          return values[0];               // @main_return
        }
        """

    def helper_name(self) -> str:
        """The mangled name clang gave to ``helper``."""
        names = [name for name in self.program.user_functions() if name != "main"]
        self.assertEqual(1, len(names), f"expected exactly one function besides main, found {names}")
        return names[0]

    def test_both_functions_are_entered(self) -> None:
        self.assertCallbackCount("__dp_func_entry", 2)
        self.assertInstrumentsLine("__dp_func_entry", "main", function="main")
        self.assertInstrumentsLine("__dp_func_entry", "helper", function=self.helper_name())

    def test_only_main_is_marked_as_the_entry_point(self) -> None:
        starts = {call.function: call.arg_int(1) for call in self.program.calls("__dp_func_entry")}
        self.assertEqual(1, starts["main"])
        self.assertEqual(0, starts[self.helper_name()])

    def test_every_function_reports_its_exit(self) -> None:
        self.assertCallbackCount("__dp_func_exit", 1, function=self.helper_name())
        self.assertCallbackCount("__dp_func_exit", 1, function="main")
        self.assertCallbackCount("__dp_finalize", 0)

    def test_the_call_site_is_instrumented_as_project_code(self) -> None:
        self.assertInstrumentsLine("__dp_call", "call")
        call = [c for c in self.program.calls("__dp_call") if self.program.source_line(c) is not None][0]
        # the second argument flags calls into code the pass did not instrument
        self.assertEqual(0, call.arg_int(1), "the call to helper is reported as a library call")


class TestNestedLoops(InstrumentationTestCase):
    """Loop ids have to stay distinct and paired, or loop nesting is mis-reported."""

    SOURCE = """
        int main() {
          int matrix[4][4];
          for (int i = 0; i < 4; ++i) {       // @outer
            for (int j = 0; j < 4; ++j) {     // @inner
              matrix[i][j] = i + j;           // @write
            }
          }
          return matrix[0][0];
        }
        """

    def test_both_loops_are_instrumented(self) -> None:
        self.assertCallbackCount("__dp_loop_entry", 2)
        self.assertCallbackCount("__dp_loop_exit", 2)
        self.assertInstrumentsLine("__dp_loop_entry", "outer")
        self.assertInstrumentsLine("__dp_loop_entry", "inner")

    def test_the_loops_get_distinct_ids(self) -> None:
        identifiers = [call.arg_int(1) for call in self.program.calls("__dp_loop_entry")]
        self.assertEqual(len(identifiers), len(set(identifiers)), f"the nested loops share a loop id: {identifiers}")

    def test_every_loop_entry_has_a_matching_exit(self) -> None:
        entered = sorted(call.required_arg_int(1) for call in self.program.calls("__dp_loop_entry"))
        exited = sorted(call.required_arg_int(1) for call in self.program.calls("__dp_loop_exit"))
        self.assertEqual(entered, exited)

    def test_the_innermost_write_is_instrumented_once(self) -> None:
        # the pass instruments the store, not the iterations, so one call covers all 16 writes
        self.assertCallbackCount("__dp_write", 1)
        self.assertInstrumentsLine("__dp_write", "write")


class TestHeapAllocation(InstrumentationTestCase):
    """Allocations have to be registered and unregistered, or addresses are reused silently.

    The three deallocations below reach clang as three different mangled names -- ``free``,
    ``_ZdaPv`` for ``delete[]`` and, since C++14, the sized ``_ZdlPvm`` for a plain ``delete`` --
    and the pass has to recognise all of them.
    """

    SOURCE = """
        #include <stdlib.h>

        int main() {
          int *m = (int *)malloc(4 * sizeof(int));  // @malloc
          m[0] = 1;                                 // @malloc_write
          int first = m[0];
          free(m);                                  // @free

          int *a = new int[4];                      // @new_array
          a[0] = 2;
          int second = a[0];
          delete[] a;                               // @delete_array

          int *s = new int;                         // @new_scalar
          *s = 3;
          int third = *s;
          delete s;                                 // @delete_scalar

          return first + second + third;
        }
        """

    def test_malloc_and_free_are_both_instrumented(self) -> None:
        self.assertInstrumentsLine("__dp_new", "malloc")
        self.assertInstrumentsLine("__dp_delete", "free")

    def test_new_and_delete_are_both_instrumented(self) -> None:
        self.assertInstrumentsLine("__dp_new", "new_array")
        self.assertInstrumentsLine("__dp_delete", "delete_array")
        self.assertInstrumentsLine("__dp_new", "new_scalar")
        self.assertInstrumentsLine("__dp_delete", "delete_scalar")

    def test_every_allocation_is_released_again(self) -> None:
        # a deallocation the pass does not recognise leaves the address range registered, so a
        # later allocation reusing the address inherits the accesses of the old object
        self.assertCallbackCount("__dp_new", 3)
        self.assertCallbackCount("__dp_delete", 3)

    def test_the_allocated_size_is_reported(self) -> None:
        allocation = [call for call in self.program.calls("__dp_new") if self.program.source_line(call) is not None]
        sizes = [call.arg_int(3) for call in allocation]
        self.assertIn(16, sizes, f"no allocation of 4 * sizeof(int) bytes was reported; sizes: {sizes}")

    def test_heap_accesses_are_instrumented(self) -> None:
        self.assertInstrumentsLine("__dp_write", "malloc_write")


class TestReallocation(InstrumentationTestCase):
    """The allocators besides ``malloc`` and ``new``, each with its own instrumentation routine.

    ``calloc`` computes the allocated size from two arguments, ``realloc`` both releases a block
    and registers one, and ``posix_memalign`` hands the block back through an out parameter. Each
    of them therefore reports its size from a different argument than ``malloc`` does, and a block
    registered with the wrong length makes the runtime attribute accesses to the wrong object.
    """

    SOURCE = """
        #include <stdlib.h>

        int main() {
          int *c = (int *)calloc(4, sizeof(int));        // @calloc
          c[0] = 1;                                      // @calloc_write
          int first = c[0];

          int *r = (int *)realloc(c, 8 * sizeof(int));   // @realloc
          r[1] = 2;                                      // @realloc_write
          int second = r[1];
          free(r);                                       // @free

          void *aligned = 0;
          posix_memalign(&aligned, 64, 256);             // @memalign
          int *p = (int *)aligned;
          p[0] = 3;                                      // @aligned_write
          int third = p[0];
          free(aligned);                                 // @free_aligned

          return first + second + third;
        }
        """

    def allocation_at(self, line: int) -> Call:
        calls = [call for call in self.program.calls("__dp_new") if self.program.source_line(call) == line]
        self.assertEqual(1, len(calls), f"expected exactly one registration for line {line}")
        return calls[0]

    def release_at(self, line: int) -> Call:
        calls = [call for call in self.program.calls("__dp_delete") if self.program.source_line(call) == line]
        self.assertEqual(1, len(calls), f"expected exactly one release for line {line}")
        return calls[0]

    def test_every_allocator_is_instrumented(self) -> None:
        self.assertCallbackCount("__dp_new", 3)
        self.assertInstrumentsLine("__dp_new", "calloc")
        self.assertInstrumentsLine("__dp_new", "realloc")
        self.assertInstrumentsLine("__dp_new", "memalign")

    def test_the_allocated_sizes_are_reported(self) -> None:
        # calloc multiplies its two arguments, realloc takes its second one and posix_memalign its
        # third; the sizes below are 4 * sizeof(int), 8 * sizeof(int) and the explicit 256
        sizes = sorted(call.required_arg_int(3) for call in self.program.calls("__dp_new"))
        self.assertEqual([16, 32, 256], sizes)

    def test_realloc_releases_the_old_block_before_registering_the_new_one(self) -> None:
        line = self.program.line_of_marker("realloc")
        self.assertLess(
            self.release_at(line).index,
            self.allocation_at(line).index,
            "realloc registers the new block before releasing the old one, which undoes the registration",
        )

    def test_realloc_registers_the_block_it_returned(self) -> None:
        # realloc is free to move the allocation, so only the returned pointer describes the new
        # block; registering the argument again would leave the runtime tracking a range the
        # program has stopped using, and the freshly allocated one unwatched.
        line = self.program.line_of_marker("realloc")
        registered = self.program.address_origin(self.allocation_at(line))
        released = self.program.address_origin(self.release_at(line))
        self.assertIsNotNone(registered)
        self.assertIsNotNone(released)
        assert registered is not None and released is not None
        self.assertIn("@realloc", registered.text, f"realloc registers '{registered.text}', not its result")
        self.assertNotIn("@realloc", released.text, f"realloc releases '{released.text}', not the old block")

    def test_posix_memalign_registers_the_block_and_not_the_out_parameter(self) -> None:
        # posix_memalign returns the block through a void** out parameter, so its first argument is
        # the address of the caller's pointer variable. Registering that address would put the
        # accesses of the block onto a stack slot of a few bytes.
        origin = self.program.address_origin(self.allocation_at(self.program.line_of_marker("memalign")))
        self.assertIsNotNone(origin)
        assert origin is not None
        self.assertNotIn("alloca", origin.text, f"posix_memalign registers the out parameter itself: '{origin.text}'")
        self.assertIn("load", origin.text, f"posix_memalign registers '{origin.text}' instead of the loaded block")
        # that load is instrumentation, not a source level access -- the program writes the out
        # parameter on this line, it does not read it
        self.assertDoesNotInstrumentLine("__dp_read", "memalign")

    def test_the_allocators_are_not_reported_as_ordinary_calls(self) -> None:
        # Every allocation and release in this program has its own instrumentation, so none of them
        # is additionally reported through __dp_call -- which is what the allocators that fall
        # through to the generic call handling would end up doing.
        self.assertCallbackCount("__dp_call", 0)

    def test_every_block_is_released_again(self) -> None:
        # one release per free, plus the implicit one realloc performs
        self.assertCallbackCount("__dp_delete", 3)
        self.assertInstrumentsLine("__dp_delete", "free")
        self.assertInstrumentsLine("__dp_delete", "free_aligned")

    def test_accesses_to_the_allocated_blocks_are_instrumented(self) -> None:
        self.assertInstrumentsLine("__dp_write", "calloc_write")
        self.assertInstrumentsLine("__dp_write", "realloc_write")
        self.assertInstrumentsLine("__dp_write", "aligned_write")


class TestExceptionalControlFlow(InstrumentationTestCase):
    """An allocation that may throw is an ``invoke``, which terminates its basic block.

    Instrumentation that has to run after such a call cannot be appended to it. The pass puts it
    at the start of the block the call returns to instead, and every allocation routine carries a
    separate code path for that -- one that the other test programs never reach, because outside a
    try block clang emits a plain call.
    """

    SOURCE = """
        int main() {
          int result = 0;
          try {
            int *a = new int[4];        // @new_in_try
            a[0] = 1;                   // @write_in_try
            result = a[0];
            delete[] a;                 // @delete_in_try
            if (result != 1) {
              throw result;             // @throw
            }
          } catch (int) {               // @catch
            return 1;
          }
          return result;                // @return
        }
        """

    def allocation(self) -> Call:
        """The call to ``operator new[]``, whatever form clang gave it."""
        allocations = self.program.calls("_Znam")
        self.assertEqual(1, len(allocations), "expected exactly one call to operator new[]")
        return allocations[0]

    def test_the_allocation_is_an_invoke(self) -> None:
        # If clang ever stops emitting an invoke here, the remaining tests of this class quietly
        # fall back to the ordinary call path, which the other classes already cover -- so the
        # premise of the class is checked explicitly.
        self.assertIsNotNone(
            self.program.invoke_normal_destination(self.allocation()),
            f"'new int[4]' inside a try block did not become an invoke: {self.allocation().text}",
        )

    def test_the_allocation_is_registered_where_the_invoke_returns_to(self) -> None:
        allocation = self.allocation()
        self.assertCallbackCount("__dp_new", 1)
        registration = self.program.calls("__dp_new")[0]
        self.assertNotEqual(
            allocation.block,
            registration.block,
            "__dp_new was placed in the block of the invoke, which ends with that invoke",
        )
        self.assertEqual(self.program.invoke_normal_destination(allocation), registration.block)
        self.assertInstrumentsLine("__dp_new", "new_in_try")

    def test_the_matching_delete_is_instrumented(self) -> None:
        self.assertCallbackCount("__dp_delete", 1)
        self.assertInstrumentsLine("__dp_delete", "delete_in_try")

    def test_accesses_inside_the_try_block_are_instrumented(self) -> None:
        self.assertInstrumentsLine("__dp_write", "write_in_try")

    def test_the_function_is_entered_and_left_exactly_once(self) -> None:
        # both returns share one exit block at -O0, so the unwinding paths must not add exits of
        # their own
        self.assertCallbackCount("__dp_func_entry", 1)
        self.assertCallbackCount("__dp_func_exit", 1)
        self.assertCallbackCount("__dp_finalize", 0)


class TestAbnormalTermination(InstrumentationTestCase):
    """A call that never returns bypasses the ordinary shutdown, so the pass has to force one.

    The runtime is otherwise brought down from a ``.fini_array`` entry, after the destructors of
    the program's global objects. ``abort()`` and ``_exit()`` never run those, so everything
    profiled up to that point would be lost without an explicit ``__dp_finalize`` in front of the
    call. ``exit()`` and ``quick_exit()`` do run them and are deliberately left alone, see
    runOnBasicBlock.cpp.
    """

    SOURCE = """
        #include <stdlib.h>

        int main() {
          int values[2];
          values[0] = 1;              // @write
          if (values[0] != 1) {
            abort();                  // @abort
          }
          return values[0];           // @return
        }
        """

    def abort_call(self) -> Call:
        calls = self.program.calls("abort")
        self.assertEqual(1, len(calls), "expected exactly one call to abort")
        return calls[0]

    def test_the_runtime_is_shut_down_before_the_program_is_aborted(self) -> None:
        self.assertCallbackCount("__dp_finalize", 1)
        self.assertInstrumentsLine("__dp_finalize", "abort")

    def test_the_shutdown_precedes_the_call_that_never_returns(self) -> None:
        shutdown = self.program.calls("__dp_finalize")[0]
        abort = self.abort_call()
        self.assertEqual(abort.block, shutdown.block, "the shutdown sits on a different path than abort")
        self.assertLess(shutdown.index, abort.index, "the runtime is shut down only after abort was called")

    def test_the_ordinary_return_keeps_its_function_exit(self) -> None:
        # the abnormal path must neither cost the normal one its exit nor gain it a second shutdown
        self.assertCallbackCount("__dp_func_exit", 1)
        self.assertInstrumentsLine("__dp_func_exit", "return")
        self.assertNotEqual(self.abort_call().block, self.program.calls("__dp_func_exit")[0].block)
