# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import logging
from typing import List, Tuple
from discopop_library.discopop_optimizer.OptimizerArguments import OptimizerArguments
from discopop_library.discopop_optimizer.classes.context.Update import Update
from discopop_library.result_classes.OptimizerOutputPattern import OptimizerOutputPattern


def remove_duplicated_updates(
    configuration: OptimizerOutputPattern, arguments: OptimizerArguments
) -> OptimizerOutputPattern:
    logger = logging.getLogger("Optimizer").getChild("RemoveDuplicatedUpdates")
    logger.setLevel(arguments.log_level)
    cleaned_updates: List[Update] = []
    buffer: List[str] = []

    def get_buffer_str(updt: Update, ignore_first_update: bool = False) -> str:
        if ignore_first_update:
            result_str = ""
        else:
            result_str = "F" if updt.is_first_data_occurrence else ""
        return (
            result_str
            + "U("
            + str(updt.source_node_id)
            + "@"
            + str(updt.source_device_id)
            + ","
            + str(updt.target_node_id)
            + "@"
            + str(updt.target_device_id)
            + ","
            + str(updt.write_data_access.var_name)
            + ")"
        )

    # remove general duplicates
    for update in configuration.data_movement:
        if get_buffer_str(update) not in buffer:
            cleaned_updates.append(update)
            buffer.append(get_buffer_str(update))
        else:
            # duplicate found. Ignore.
            pass
    configuration.data_movement = cleaned_updates

    # remove update <-> first update duplicates
    buffer = []
    cleaned_updates = []
    regular_updates = [u for u in configuration.data_movement if not u.is_first_data_occurrence]
    first_updates = [u for u in configuration.data_movement if u.is_first_data_occurrence]
    # add first updates to cleaned list
    for update in first_updates:
        if get_buffer_str(update, ignore_first_update=True) not in buffer:
            cleaned_updates.append(update)
            buffer.append(get_buffer_str(update, ignore_first_update=True))
        else:
            # duplicate found. Ignore
            pass
    # check for duplicates in regular updates
    for update in regular_updates:
        if get_buffer_str(update, ignore_first_update=True) not in buffer:
            cleaned_updates.append(update)
            buffer.append(get_buffer_str(update, ignore_first_update=True))
        else:
            # duplicate found. Ignore
            pass
    configuration.data_movement = cleaned_updates

    def get_delete_copy_from_buffer_str(updt: Update) -> Tuple[str, bool]:
        result_str = "C" if updt.copy_delete_data else ""
        return (
            result_str
            + "D("
            + str(updt.source_node_id)
            + "@"
            + str(updt.source_device_id)
            + ","
            + str(updt.target_node_id)
            + "@"
            + str(updt.target_device_id)
            + ","
            + str(updt.write_data_access.var_name)
            + ")",
            updt.copy_delete_data,
        )

    # check for duplicated delete / copy-from updates
    logger.debug("Checking for duplicated delete / copy-from updates")
    str_buffer: List[str] = []
    update_buffer: List[Update] = []
    cleaned_updates = []
    for update in configuration.data_movement:
        if not (update.delete_data or update.copy_delete_data):
            # no data is removed. keep the update
            cleaned_updates.append(update)
            continue
        #        if update.source_device_id == configuration.host_device_id and update.target_device_id == configuration.host_device_id:
        #            cleaned_updates.append(update)
        #            continue

        u_str, u_copies = get_delete_copy_from_buffer_str(update)
        logger.debug("current: " + u_str)
        if u_str in str_buffer:
            # duplicate found. ignore.
            logger.debug("---> DUPLICATE")
        else:
            # check if the complementing update is contained in the buffer
            if u_copies:
                # check for D(...) in buffer
                complement = u_str[1:]
                logger.debug("Complement: " + complement)
                if complement in str_buffer:
                    logger.debug("BUFFER HIT")
                    # remove the element from the buffer as copying has priority over deletion
                    buffer_idx = str_buffer.index(complement)
                    del str_buffer[buffer_idx]
                    del update_buffer[buffer_idx]
                    # add the current update to the buffer
                    str_buffer.append(u_str)
                    update_buffer.append(update)
                else:
                    logger.debug("BUFFER ADD")
                    # add update to the buffer
                    str_buffer.append(u_str)
                    update_buffer.append(update)
            else:
                # check for CD(...) in buffer
                complement = "C" + u_str
                logger.debug("Complement: " + complement)
                if complement in str_buffer:
                    logger.debug("BUFFER HIT")
                    # ignore the current update since data copying has priority over deletion
                    continue
                else:
                    logger.debug("BUFFER ADD")
                    # add update to the buffer
                    str_buffer.append(u_str)
                    update_buffer.append(update)

    for update in update_buffer:
        cleaned_updates.append(update)

    logger.debug("Cleanued updates")
    for update in cleaned_updates:
        logger.debug("# " + str(update))
    logger.debug("")

    logger.debug("")
    configuration.data_movement = cleaned_updates

    logger.debug("Removed duplicates from updates")
    for update in configuration.data_movement:
        logger.debug("# " + str(update))
    logger.debug("")

    return configuration
