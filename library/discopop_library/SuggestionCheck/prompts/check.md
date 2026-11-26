<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License. See the LICENSE file in the package base
directory for details.
-->

You are checking whether a loop of a C/C++ program can safely run in parallel.

DiscoPoP profiled the sequential program and found that the iterations of the loop
below depend on each other. These dependencies are listed as **blockers**. Because
of them, simply adding an OpenMP directive to the loop would make the program
incorrect.

Your task: decide whether this loop can run in parallel with correct results. If it
can, change the code so that the loop runs in parallel correctly. If it cannot, or
if you cannot tell, say so.

## What counts as correct

The parallel program must compute the same results as the sequential one, for every
input: output, written files, returned values and the state visible after the loop.
"The same" means the same in exact arithmetic. The only differences allowed are
rounding differences that come from performing floating-point operations in another
order, for example a sum that each thread accumulates on its own and that is
combined afterwards.

Anything else is a different result, even if it might seem acceptable:

- lost or duplicated updates;
- other random numbers, or the same random numbers in other places;
- elements of a container, or lines of output, in another order;
- another choice among equally good candidates, e.g. on ties.

Comments in the code are hints about intent, not facts: decide by what the code
does.

## Correctness only

Decide only whether the loop can run in parallel with correct results. Whether
parallelizing it pays off is not your question: that is measured later with
production inputs, which are much larger than the profiled run (more iterations,
more steps, larger data). Assume the loop runs long enough for parallelization to
be effective. Never reject or simplify a solution because the loop body looks small
or because a correct parallel version needs more work.

## Rules

- **Rejection is the default.** Approve only if, for every blocker, you can show
  from the code why the parallel loop is still correct. If you would have to
  write "probably", "likely" or "usually", reject.
- **Every blocker on its own.** For each blocker, state why it does not make the
  parallel loop wrong, and cite the lines (path:line) this rests on. One blocker
  without a justification means the answer is a rejection.
- **Read before you decide.** The code excerpts below are incomplete. Before you
  answer, open for every blocker:
  - the declarations of the data it involves, with their storage class and type;
  - the definitions of the functions called on its lines;
  - the code after the loop that uses this data.

  DiscoPoP records which files you open; an approval without the files of the
  blockers is sent back.
- **Only facts about the code.** Do not rely on typical inputs. If the answer
  depends on code you cannot find, answer "unsure".
- **Both mistakes are not equal.** A rejected loop only costs a missed speedup. A
  wrong approval makes the program compute wrong results. "unsure" is a valid
  answer and counts as a rejection.
- **Name the assumption.** An approval states the property of the program it relies
  on, so that a person can check it.

## Where you work

The current directory is a copy of the project; paths below are relative to it.
You can read all of it and change files in it. Do not run commands.

- For an approval, change the code in this copy so that the loop runs in parallel
  correctly. You are not limited to the directive: change the loop body, the data
  it uses or other code of the project as far as needed. Two things must hold
  afterwards: the loop is directly preceded by its OpenMP directive
  (`#pragma omp parallel for ...`), and its header line stays exactly as it is, so
  that DiscoPoP finds the loop. Change only source files of the project. DiscoPoP
  computes the patch from your changes.
- Change only what the parallel loop needs: nothing else, not even small
  improvements. Every change outside the loop body belongs to the justification of
  the blocker it resolves, with the lines it affects in "evidence". A changed file
  that holds neither the loop nor a blocker's line, and that no evidence names, is
  sent back.
- The suggested directive below is a starting point, not a requirement: its
  clauses may be wrong once the blockers are taken into account.
- For a rejection, or if you are unsure, change nothing.

## DiscoPoP's data

{discopop_tools}

## The suggestion

{description}

## Blockers

{blockers}

## Code

{code}

## Answer format

When you are done, answer with a JSON object in a ```json block:

```json
{
  "verdict": "approved | rejected | unsure",
  "reason": "why, for rejected or unsure",
  "blockers": [
    {"index": 1, "justification": "why blocker 1 does not make the parallel loop wrong", "evidence": ["path:line"]}
  ],
  "assumption": "the property of the program an approval relies on",
  "result_differences": "none | rounding"
}
```

For "rejected" or "unsure", "reason" is enough. For "approved", give one entry in
"blockers" for every blocker, and declare in "result_differences" how the results
can differ from the sequential program: "none" if they are identical, "rounding" if
floating-point operations can happen in another order. For "rounding", name in the
assumption which operations change their order, and whether their results decide
comparisons or branches later on: there, small differences can grow into large
ones.
