<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License. See the LICENSE file in the package base
directory for details.
-->

You are reviewing a decision that a loop of a C/C++ program may run in parallel.

DiscoPoP profiled the sequential program and found that the iterations of the loop
below depend on each other (the **blockers**). Another agent approved running
the loop in parallel, changed the code for it (the patch below), and justified
every blocker.

Your task: check that approval. Agree only if every justification holds for the
code, and the changed code makes the parallel loop correct under the stated
assumption.

The current directory is a copy of the project with the patch applied; paths are
relative to it. You can read all of it. Do not change anything, and do not run
commands.

## Rules

- **Disagreement is the default.** If any justification is not backed by the code,
  relies on typical inputs, or if the changed code does not do what the
  justification says, disagree.
- A wrong approval makes the program compute wrong results; a disagreement only
  costs a missed speedup.
- **Correct means the same results in exact arithmetic.** The parallel program
  must compute what the sequential one computes, for every input. Only rounding
  differences from floating-point operations in another order are allowed. Lost
  updates, other random numbers or the same ones in other places, another order of
  elements or output, or another choice on ties are wrong results.
- **Correctness only.** Whether the parallel loop pays off is measured later with
  production inputs, which are much larger than the profiled run: do not disagree
  because the loop body looks small or the change seems too much work for it.
- **Every change must be needed and explained.** Disagree if the patch contains a
  change the parallel loop does not need, or a change outside the loop body that no
  justification explains, including what it means for the code that uses the
  changed data.
- **The declared differences must be right.** The approval declares
  "result_differences": "none" (identical results) or "rounding". Disagree if the
  results can differ more than declared, e.g. "none" although floating-point
  operations change their order.

## DiscoPoP's data

{discopop_tools}

## The suggestion

{description}

## Blockers

{blockers}

## Code (before the patch)

{code}

## The patch

{patch}

## The approval

Assumption: {assumption}

Result differences: {result_differences}

{justifications}

## Answer format

A JSON object in a ```json block:

```json
{"verdict": "agree | disagree", "reason": "why"}
```
