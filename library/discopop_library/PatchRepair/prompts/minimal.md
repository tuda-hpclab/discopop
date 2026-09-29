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

{patch_blocks}

## The code as it looks *before* the patch is applied

Your corrected patch must be a diff against exactly this text.

{original_source}

## Compiler diagnostics

```
{diagnostics}
```

{output_contract}
