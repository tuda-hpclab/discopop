# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Result of a side effect query (``analysis.SideEffectIndex.compute``).

Unranked and uncut: ordering, truncation and wording for a reader are the
caller's job (the MCP tool ``get_side_effects``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional, Tuple

Access = Literal["read", "write", "unknown"]
Kind = Literal["global", "parameter", "other"]
Source = Literal["observed", "static"]
Coverage = Literal["executed", "partial", "untracked", "not_executed"]


@dataclass(frozen=True)
class FunctionInfo:
    # PET function node id
    id: str
    # name as in the PET (usually mangled)
    name: str
    # demangled name with signature
    display_name: str
    # absolute path, None if the file id is unknown
    file: Optional[str]
    file_id: int
    start_line: int
    end_line: int


@dataclass(frozen=True)
class EffectSite:
    file_id: int
    line: int
    # function chain from the queried function to the function containing the access
    # (outermost first, display names); empty if the access lies in the queried function itself
    via: Tuple[str, ...] = ()


@dataclass
class Effect:
    # name at the accessing instruction, without the GEPRESULT_ prefix; for a member access the member name
    name: str
    kind: Kind
    access: Access
    source: Source
    # the access goes through a pointer, reference or array (GEPRESULT_ prefix, pointer-typed base, member access)
    through_pointer: bool = False
    # for a member access: the base it was accessed through (e.g. "s" for s->second)
    member_of: Optional[str] = None
    # all sites, sorted by (file_id, line, via); the caller decides how many to show
    sites: List[EffectSite] = field(default_factory=list)
    # names under which the other end of crossing records refers to the same data
    outside_names: List[str] = field(default_factory=list)

    @property
    def is_own(self) -> bool:
        """At least one site lies in the queried function itself."""
        return any(len(site.via) == 0 for site in self.sites)

    @property
    def min_via_depth(self) -> int:
        return min((len(site.via) for site in self.sites), default=0)


@dataclass
class SideEffects:
    function: FunctionInfo
    coverage: Coverage
    # True / False / None (unknown), see DESIGN_get_side_effects.md, section 1.3
    pure_on_observed_inputs: Optional[bool]
    performs_file_io: bool
    # demangled names of called functions without a definition in the project, minus the allowlist
    unprofiled_calls: List[str]
    effects: List[Effect]
    # record ends located in the function that matched no work context
    unmapped_records: int
    # display names of the functions whose accesses contribute effects (excluding the queried one)
    contributing_callees: List[str]
    # the AST has facts for the queried function and all contributing callees
    ast_facts: bool
    # short explanations for the reader, e.g. why the result is partial
    notes: List[str] = field(default_factory=list)
