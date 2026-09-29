# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

import itertools
import logging
from typing import Dict, Iterator, List, Optional, Set, Tuple, TYPE_CHECKING

from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX

if TYPE_CHECKING:
    from discopop_explorer.classes.TaskGraph.TGNode import TGNode

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.TaskGraph.Aliases import LevelIndex, PETNode, PositionIndex

logger = logging.getLogger("Explorer")


class Context(object):
    contained_nodes: List[TGNode]
    contained_contexts: Set[Context]
    successor: Optional[Context]
    predecessor: Optional[Context]
    parent_context: Optional[Context]
    outgoing_dependencies: Set[Tuple[Context, Dependency]]
    incoming_dependencies: Set[Tuple[Context, Dependency]]
    state_ids: List[int]
    creation_index: int

    # contained_contexts is a set, so iterating it is not reproducible across runs. Contexts
    # are created in a deterministic order during TaskGraph construction, which makes this
    # counter a stable sort key wherever a deterministic context order is required.
    _creation_counter: Iterator[int] = itertools.count()

    def __init__(self) -> None:
        self.contained_nodes = []
        self.contained_contexts = set()
        self.parent_context = None
        self.successor = None
        self.predecessor = None
        self.outgoing_dependencies = set()
        # cache for get_code_scope(inclusive=False); only depends on self.contained_nodes,
        # which is mutated solely via add_node (where the cache is invalidated).
        self._code_scope_cache: Optional[List[LineID]] = None
        self._code_scope_set_cache: Optional[Set[LineID]] = None
        self.incoming_dependencies = set()
        self.state_ids = []
        self.creation_index = next(Context._creation_counter)

    def get_contained_nodes(self, inclusive: bool = False) -> List[TGNode]:
        """
        Returns the nodes contained in the current context.
        inclusive: If False, does not consider contexts contained in the current context. If true, included contexts are traversed recursively.
        """
        if not inclusive:
            return self.contained_nodes
        # iterative with a visited set: the containment relation is only supposed to form a
        # forest, but nothing enforces that at runtime (see __validate_context_structure),
        # and recursing into a cycle - or merely into a deeply nested structure - exceeds
        # Python's recursion limit
        nodes: List[TGNode] = []
        visited: Set[Context] = {self}
        stack: List[Context] = [self]
        while len(stack) > 0:
            current = stack.pop()
            nodes += current.contained_nodes
            for ctx in current.contained_contexts:
                if ctx not in visited:
                    visited.add(ctx)
                    stack.append(ctx)
        return nodes

    def get_contained_contexts(self, inclusive: bool = False) -> Set[Context]:
        """
        Returns the contexts contained in the current context.
        If inclusive is False, only the directly contained contexts will be returned. If inclusive is True, contexts will be collected recursively.
        """
        if not inclusive:
            return self.contained_contexts
        # iterative with a visited set, see get_contained_nodes
        result: Set[Context] = set()
        stack: List[Context] = [self]
        while len(stack) > 0:
            current = stack.pop()
            for ctx in current.contained_contexts:
                if ctx not in result and ctx != self:
                    result.add(ctx)
                    stack.append(ctx)
        return result

    def get_sequence_entry_contexts(self) -> List[Context]:
        """Returns the directly contained contexts which start a sequence, i.e. which have no
        predecessor, in a deterministic order."""
        return sorted(
            [ctx for ctx in self.contained_contexts if ctx.predecessor is None],
            key=lambda ctx: ctx.creation_index,
        )

    def get_contained_contexts_in_sequence(self, pet: PEGraphX, is_entry: bool = True) -> List[Context]:
        """enumerates contained contexts in their sequence of occurrence in the program.

        The enumeration is a pre-order walk: a context is reported before the contexts it
        contains, and those before its successor.

        Implemented iteratively and bounded to the region it was asked about on purpose. Both
        relations it follows are unbounded in size - the successor relation is a chain whose
        length grows with the amount of inlined code, and containment nesting grows with the
        inlining depth - so recursing along them exceeds Python's recursion limit even for a
        well-formed structure. Neither relation is guaranteed to be acyclic either (see
        __validate_context_structure), which would make a recursive walk diverge outright.

        The region bound additionally keeps the walk inside what the caller asked for: nothing
        stops a successor chain from leaving the enclosing context if the structure is
        malformed, in which case the result would contain contexts (and, via their nodes, CUs)
        from unrelated parts of the program."""
        region = self if is_entry else self.parent_context
        contexts_in_region: Optional[Set[Context]] = None
        if region is not None:
            contexts_in_region = region.get_contained_contexts(inclusive=True)
            contexts_in_region.add(region)

        result: List[Context] = []
        visited: Set[Context] = set()
        # LIFO: to report a context's contained contexts before its successor, the successor
        # is pushed first and the contained contexts are pushed in reverse order
        stack: List[Context] = [self] if not is_entry else list(reversed(self.get_sequence_entry_contexts()))
        while len(stack) > 0:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            result.append(current)

            successor = current.successor
            if successor is not None:
                if contexts_in_region is not None and successor not in contexts_in_region:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Successor of context %s leaves the enclosing region %s - not following it.",
                            current.get_label(),
                            region.get_label() if region is not None else "None",
                        )
                else:
                    stack.append(successor)
            stack += reversed(current.get_sequence_entry_contexts())
        return result

    def add_node(self, node: TGNode) -> None:
        self.contained_nodes.append(node)
        self._code_scope_cache = None  # invalidate cached code scope
        self._code_scope_set_cache = None

    def add_contained_context(self, context: Context) -> None:
        if context == self:
            # do not allow the creation of self-containing relations
            return
        if context in self.get_ancestor_contexts():
            # containment must form a forest: adding an ancestor as a contained context would
            # close a cycle, which makes every traversal of the containment relation diverge
            logger.warning(
                "Refused to register context %s as contained in %s: it is already an ancestor "
                "of it, which would make the containment relation cyclic.",
                context.get_label(),
                self.get_label(),
            )
            return
        self.contained_contexts.add(context)

    def register_parent_context(self, context: Context) -> None:
        if context == self:
            # do not allow the creation of self-parenting relations
            return
        if context is not None and self in context.get_ancestor_contexts():
            # see add_contained_context
            logger.warning(
                "Refused to register context %s as the parent of %s: it is already a descendant "
                "of it, which would make the containment relation cyclic.",
                context.get_label(),
                self.get_label(),
            )
            return
        self.parent_context = context

    def register_successor_context(self, context: Context) -> None:
        if context == self:
            # do not allow the creation of self-succession relations
            return
        if context.successor == self:
            # closing a two-element cycle in the successor relation. Longer cycles are not
            # rejected here - following the chain to look for one is linear in its length and
            # would make building the relation quadratic - they are reported (and broken) by
            # __validate_context_structure instead
            logger.warning(
                "Refused to register context %s as the successor of %s: it is already its "
                "predecessor, which would make the successor relation cyclic.",
                context.get_label(),
                self.get_label(),
            )
            return
        self.successor = context
        context.predecessor = self

    def get_preceeding_contexts(self) -> Set[Context]:
        preceeding_contexts: Set[Context] = set()
        parent_queue: List[Context] = [self.parent_context] if self.parent_context is not None else []
        predecessor_queue: List[Context] = [self.predecessor] if self.predecessor is not None else []
        visited: Set[Context] = set()
        while len(parent_queue) > 0 or len(predecessor_queue) > 0:
            while len(predecessor_queue) > 0:
                current_pred = predecessor_queue.pop()
                preceeding_contexts.add(current_pred)
                preceeding_contexts = preceeding_contexts.union(current_pred.get_contained_contexts(inclusive=True))
                if current_pred.predecessor is not None:
                    if current_pred.predecessor not in visited:
                        visited.add(current_pred.predecessor)
                        predecessor_queue.append(current_pred.predecessor)
            while len(parent_queue) > 0:
                current_parent = parent_queue.pop()
                if current_parent.predecessor is not None:
                    if current_parent.predecessor not in visited:
                        visited.add(current_parent.predecessor)
                        predecessor_queue.append(current_parent.predecessor)
                if current_parent.parent_context is not None:
                    if current_parent.parent_context not in visited:
                        visited.add(current_parent.parent_context)
                        parent_queue.append(current_parent.parent_context)
        return preceeding_contexts

    def get_successive_contexts(self) -> Set[Context]:
        successive_contexts: Set[Context] = set()
        parent_queue: List[Context] = [self.parent_context] if self.parent_context is not None else []
        successor_queue: List[Context] = [self.successor] if self.successor is not None else []
        visited: Set[Context] = set()
        while len(parent_queue) > 0 or len(successor_queue) > 0:
            while len(successor_queue) > 0:
                current_succ = successor_queue.pop()
                successive_contexts.add(current_succ)
                successive_contexts = successive_contexts.union(current_succ.get_contained_contexts(inclusive=True))
                if current_succ.successor is not None:
                    if current_succ.successor not in visited:
                        visited.add(current_succ.successor)
                        successor_queue.append(current_succ.successor)
            while len(parent_queue) > 0:
                current_parent = parent_queue.pop()
                if current_parent.successor is not None:
                    if current_parent.successor not in visited:
                        visited.add(current_parent.successor)
                        successor_queue.append(current_parent.successor)
                if current_parent.parent_context is not None:
                    if current_parent.parent_context not in visited:
                        visited.add(current_parent.parent_context)
                        parent_queue.append(current_parent.parent_context)
        return successive_contexts

    def is_function_context(self) -> bool:
        return False

    def get_ancestor_contexts(self) -> List[Context]:
        """return the ancestor contexts of the current context, starting with the direct parent context and ending with the root context."""
        ancestors: List[Context] = []
        visited: Set[Context] = {self}
        current_context = self.parent_context
        while current_context is not None:
            if current_context in visited:
                #                logger.warning(
                #                    "Cyclic parent_context chain detected while collecting ancestor contexts of "
                #                    + str(self)
                #                    + " (revisited "
                #                    + str(current_context)
                #                    + "). Truncating ancestor list to break the cycle."
                #                )
                break
            visited.add(current_context)
            ancestors.append(current_context)
            current_context = current_context.parent_context
        return ancestors

    def get_closest_function_ancestor(self) -> Optional[Context]:
        """return the closest ancestor function context."""
        if self.is_function_context():
            return self
        visited: Set[Context] = {self}
        current_context = self.parent_context
        while current_context is not None:
            if current_context.is_function_context():
                return current_context
            if current_context in visited:
                logger.warning(
                    "Cyclic parent_context chain detected while searching for the closest function ancestor of "
                    + str(self)
                    + " (revisited "
                    + str(current_context)
                    + "). Treating as if no function ancestor exists."
                )
                return None
            visited.add(current_context)
            current_context = current_context.parent_context
        return None

    def register_outgoing_dependency(self, target_context: Context, dependency: Dependency) -> None:
        # register dependency
        self.outgoing_dependencies.add((target_context, dependency))
        target_context.incoming_dependencies.add((self, dependency))
        # register affected contexts

    #        self_ancestors = self.get_ancestor_contexts()
    #        target_ancestors = target_context.get_ancestor_contexts()
    #        # -> ignore matching prefix ancestors
    #        while len(self_ancestors) > 0 and len(target_ancestors) > 0 and self_ancestors[-1] == target_ancestors[-1]:
    #            self_ancestors = self_ancestors[:-1]
    #            target_ancestors = target_ancestors[:-1]
    #        # -> register affected contexts
    #        self.affected_contexts_by_outgoing_dependency[dependency] = target_ancestors
    #        print("ln: ", len(target_ancestors))
    #        target_context.affecting_contexts_by_incoming_dependency[dependency] = self_ancestors

    def delete_outgoing_dependency(self, target_context: Context, dependency: Dependency) -> None:
        # register dependency
        self.outgoing_dependencies.remove((target_context, dependency))
        target_context.incoming_dependencies.remove((self, dependency))
        # delete affected contexts

    #        if dependency in self.affected_contexts_by_outgoing_dependency:
    #            del self.affected_contexts_by_outgoing_dependency[dependency]
    #        if dependency in target_context.affecting_contexts_by_incoming_dependency:
    #            del target_context.affecting_contexts_by_incoming_dependency[dependency]

    def get_outgoing_dependency_targets(self) -> Set[Context]:
        return set([outgoing_dependency[0] for outgoing_dependency in self.outgoing_dependencies])

    def get_plot_bounding_box(self) -> Tuple[int, LevelIndex, LevelIndex, PositionIndex, PositionIndex]:
        if len(self.contained_nodes) == 0:
            return 0, 0, 0, 0, 0
        levels = [n.level for n in self.contained_nodes]
        positions = [n.position for n in self.contained_nodes]
        return len(self.contained_nodes), min(levels), max(levels), min(positions), max(positions)

    def get_plot_border_color(self) -> str:
        return "b"

    def get_plot_face_color(self) -> str:
        return "red"

    def get_plot_face_alpha(self) -> float:
        return 0.2

    def get_label(self) -> str:
        return "CTX"

    def get_first_pet_node(self, pet: PEGraphX) -> Optional[PETNode]:
        for node in self.contained_nodes:
            pet_node = node.get_pet_node(pet)
            if pet_node is not None:
                return pet_node
        return None

    def get_code_scope(self, pet: PEGraphX, inclusive: bool = False) -> List[LineID]:
        """returns a list of code scopes contained in the context."""
        # The inclusive=False scope depends only on self.contained_nodes and is computed
        # repeatedly (once per dependency lookup), so cache it. The inclusive=True scope
        # also depends on descendant contexts and is left uncached.
        if not inclusive and self._code_scope_cache is not None:
            return self._code_scope_cache
        scope: List[LineID] = []
        for node in self.get_contained_nodes(inclusive=inclusive):
            pet_node = node.get_pet_node(pet)
            if pet_node is None:
                continue
            for i in range(pet_node.start_line, pet_node.end_line + 1):
                scope.append(LineID(str(pet_node.file_id) + ":" + str(i)))
        # remove duplicates
        result = list(dict.fromkeys(scope))
        if not inclusive:
            self._code_scope_cache = result
        return result

    def get_code_scope_set(self, pet: PEGraphX, inclusive: bool = False) -> Set[LineID]:
        """the code scope of the context as a set, for callers which only test membership.

        get_code_scope returns a list, and the do-all analysis tests line membership in it once
        per dependency, which is a linear scan each time. The inclusive=False variant is cached
        like the list it is derived from."""
        if inclusive:
            return set(self.get_code_scope(pet, inclusive=True))
        if self._code_scope_set_cache is None:
            self._code_scope_set_cache = set(self.get_code_scope(pet))
        return self._code_scope_set_cache

    def get_defined_variables(self, pet: PEGraphX) -> List[Tuple[str, LineID]]:
        """returns a list of defined variables in the context as tuples of (variable name, lineID)."""
        defined_vars: List[Tuple[str, LineID]] = []
        code_scope = set(self.get_code_scope(pet))
        for node in self.contained_nodes:
            pet_node = node.get_pet_node(pet)
            if pet_node is None:
                continue
            if isinstance(pet_node, CUNode):
                for var in pet_node.local_vars + pet_node.global_vars:
                    var_def_line = var.defLine
                    if var_def_line in code_scope:  # implicitly ignore definition line "LineNotFound"
                        # print("Definition of variable " + var.name + " at line " + var_def_line)
                        defined_vars.append((str(var.name), LineID(var_def_line)))

        # remove duplicates
        defined_vars = list(dict.fromkeys(defined_vars))
        return defined_vars

    def get_state_ids(self) -> List[int]:
        if len(self.state_ids) != 0:
            return self.state_ids
        for anc in self.get_ancestor_contexts():
            if len(anc.state_ids) != 0:
                return anc.state_ids
        return []
