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

{justifications}

## Answer format

A JSON object in a ```json block:

```json
{"verdict": "agree | disagree", "reason": "why"}
```
