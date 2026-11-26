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

Your task: decide whether the program, by what it is meant to do, allows this loop
to run in parallel. If it does, change the code so that the loop runs in parallel
correctly. If it does not, or if you cannot tell, say so.

## Rules

- **Rejection is the default.** Approve only if, for every blocker, you can show
  from the code why the parallel loop is still correct. If you would have to
  write "probably", "likely" or "usually", reject.
- **Every blocker on its own.** For each blocker, state why it does not make the
  parallel loop wrong, and cite the lines (path:line) this rests on. One blocker
  without a justification means the answer is a rejection.
- **Only facts about the code.** Do not rely on typical inputs. Read the code you
  need, e.g. declarations and what the callers do with a result. If the answer
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
- The suggested directive below is a starting point, not a requirement: its
  clauses may be wrong once the blockers are taken into account.
- For a rejection, or if you are unsure, change nothing.

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
  "assumption": "the property of the program an approval relies on"
}
```

For "rejected" or "unsure", "reason" is enough. For "approved", give one entry in
"blockers" for every blocker.
