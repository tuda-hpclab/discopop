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
of them, running the iterations in parallel as they are would be incorrect, and the
patch below, which simply adds an OpenMP directive, is **not** a correct
parallelization.

Your task: decide whether the program, by what it is meant to do, allows this loop
to run in parallel. If it does, change the patch so that the parallel loop is
correct. If it does not, or if you cannot tell, say so.

## Rules

- **Rejection is the default.** Approve only if, for every blocker, you can show
  from the code below why the parallel loop is still correct. If you would have to
  write "probably", "likely" or "usually", reject.
- **Every blocker on its own.** For each blocker, state why it does not make the
  parallel loop wrong, and cite the lines (file:line) this rests on. One blocker
  without a justification means the answer is a rejection.
- **Only facts about the code.** Do not rely on typical inputs or on code that is
  not shown to you. If the answer depends on code you cannot see, for example on
  what the callers do with a result, answer "unsure".
- **Both mistakes are not equal.** A rejected loop only costs a missed speedup. A
  wrong approval makes the program compute wrong results. "unsure" is a valid
  answer and counts as a rejection.
- **Name the assumption.** An approval states the property of the program it relies
  on, so that a person can check it.
- Do not use any tools and do not modify any files. Answer with text only.

{identity}

## Blockers

{blockers}

## Code

{code}

## The plain patch (not correct as it is)

{patch}

## Answer format

First a JSON object in a ```json block:

```json
{
  "verdict": "approved | rejected | unsure",
  "reason": "why, for rejected or unsure",
  "blockers": [
    {"index": 1, "justification": "why blocker 1 does not make the parallel loop wrong", "evidence": ["file:line"]}
  ],
  "assumption": "the property of the program an approval relies on"
}
```

For "rejected" or "unsure", "reason" is enough. For "approved", give one entry in
"blockers" for every blocker, and after the JSON block the complete patch, one block
per changed file, each a unified diff against the **original** source (not against
the patched code). It replaces the plain patch, so it must keep the loop's OpenMP
directive:

===BEGIN PATCH <file_id>===
<unified diff>
===END PATCH <file_id>===

The file ids:

{files}
