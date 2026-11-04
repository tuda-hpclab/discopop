<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License. See the LICENSE file in the package base
directory for details.
-->

You are completing an automatically generated patch.

DiscoPoP analysed a sequential program, found a parallelizable code region, and
generated the patch below to add OpenMP directives to it. Some parts of the directives
cannot be derived from the profile, because they depend on what the code means. The
patch generator left a marker comment `/* DiscoPoP TODO: ... */` in their place. The
patch compiles with the markers.

Your task: replace every marker by what it asks for, so that the directives are
complete. Use the source code to decide, and keep the parallelization the patch was
generated for.

{identity}

## What has to be completed

{placeholders}

{patch_blocks}

## What DiscoPoP determined about the region

{pattern_metadata}

## The code as it looks *before* the patch is applied

Your completed patch must be a diff against exactly this text.

{original_source}

{output_contract}
