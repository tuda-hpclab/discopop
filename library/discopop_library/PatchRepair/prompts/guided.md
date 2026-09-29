<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License. See the LICENSE file in the package base
directory for details.
-->

You are fixing a compiler error in an automatically generated patch.

DiscoPoP analysed a sequential program, found a parallelizable code region, and
generated the patch below to add OpenMP directives to it. The patch applies cleanly,
but the resulting code does not compile.

Your task: correct the patch so the code compiles, while keeping the parallelization
the patch was generated for.

{identity}

## What DiscoPoP determined about this code region

These are the variable classifications DiscoPoP's data dependence analysis produced.
They are the reason the directive has the clauses it has. A clause that names a
variable which does not exist at that point in the code, or that classifies one
incorrectly, is the usual cause of the error below -- so check the diagnostics against
this list first.

{pattern_metadata}

{patch_blocks}

## The code as it looks *after* the patch is applied

The compiler's line numbers below refer to this version of the code.

{patched_source}

## The code as it looks *before* the patch is applied

Your corrected patch must be a diff against this version.

{original_source}

## Compiler diagnostics

```
{diagnostics}
```

{output_contract}
