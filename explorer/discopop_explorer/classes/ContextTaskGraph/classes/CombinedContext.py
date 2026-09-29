# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Optional

from discopop_explorer.classes.TaskGraph.Contexts.Context import Context


class CombinedContext(Context):
    outermost_context: Optional[Context] = None

    def get_label(self) -> str:
        return (
            "CombinedCTX\ntype: "
            + type(self.outermost_context).__name__
            + "\nsize: "
            + str(len(self.contained_contexts))
        )

    def register_outermost_context(self, ctx: Context) -> None:
        if isinstance(ctx, CombinedContext):
            self.outermost_context = ctx.outermost_context
        else:
            self.outermost_context = ctx
