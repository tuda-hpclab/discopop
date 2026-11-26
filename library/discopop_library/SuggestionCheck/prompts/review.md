<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License. See the LICENSE file in the package base
directory for details.
-->

You are reviewing a decision that a loop of a C/C++ program may run in parallel.

DiscoPoP profiled the sequential program and found that the iterations of the loop
below depend on each other (the **blockers**). Another reviewer approved running
the loop in parallel with the patch below, and justified every blocker.

Your task: check that approval. Agree only if every justification holds for the
code shown, and the patch makes the parallel loop correct under the stated
assumption.

## Rules

- **Disagreement is the default.** If any justification is not backed by the code
  shown, relies on typical inputs or on code that is not shown, or if the patch
  does not do what the justification says, disagree.
- A wrong approval makes the program compute wrong results; a disagreement only
  costs a missed speedup.
- Do not use any tools and do not modify any files. Answer with text only.

{identity}

## Blockers

{blockers}

## Code

{code}

## The approved patch

{patch}

## The approval

Assumption: {assumption}

{justifications}

## Answer format

A JSON object in a ```json block:

```json
{"verdict": "agree | disagree", "reason": "why"}
```
