from typing import Dict, List
import os
import re


def _load_instruction_mapping(profiler_dir: str) -> Dict[int, str]:
    mapping: Dict[int, str] = {}
    path = os.path.join(profiler_dir, "instructionID_to_lineID_mapping.txt")
    if not os.path.exists(path):
        return mapping
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 2:
                continue
            try:
                instr_id = int(parts[0])
            except ValueError:
                continue
            loc = parts[1]
            if loc == "*":
                continue
            loc_parts = loc.split(":")
            if len(loc_parts) >= 2:
                mapping[instr_id] = f"{loc_parts[0]}:{loc_parts[1]}"
    return mapping


def _translate_loc(loc: str, mapping: Dict[int, str]) -> str:
    if loc == "*":
        return "*"
    if ":" in loc:
        return loc  # already file_id:line_id (old format — pass through)
    try:
        instr_id = int(loc.split("@")[0])
        return mapping.get(instr_id, "*")
    except ValueError:
        return "*"


def get_dependencies(path: str) -> List[str]:
    result: List[str] = []
    profiler_dir = os.path.dirname(path)
    mapping = _load_instruction_mapping(profiler_dir)
    pattern = re.compile(r"((RAW|WAR|WAW|INIT)\s((?:\d+(?:@\d+)?)|(?:\d+:\d+)|\*)\|\S+)")
    with open(path, "r") as f:
        for line in f.readlines():
            line = line.replace("\n", "")
            raw_sink = line.split(" ")[0]
            sink = _translate_loc(raw_sink, mapping)
            if ":" not in sink:
                continue
            for match in re.findall(pattern, line):
                full_match = match[0]  # e.g. "RAW 16@5|y(...)"
                dep_type = match[1]  # e.g. "RAW"
                raw_source = match[2]  # e.g. "16@5", "1:2", or "*"
                source = _translate_loc(raw_source, mapping)
                rest = full_match[len(dep_type) + 1 + len(raw_source) :]  # "|varname..."
                result.append(f"{sink} {dep_type} {source}{rest}")
    return result
