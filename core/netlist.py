"""Prepare extracted candidates for the complete wire-chain query."""
from copy import deepcopy

from core.extraction.device_semantics import read_device_semantics
from core.extraction.review_wire_notes import collect_review_wire_notes
from core.extraction.saved_relations import load_saved_relations


def normalize_netlist(raw):
    """Attach query fields without upgrading automatic candidates to confirmations."""
    result = deepcopy(raw)
    notes = collect_review_wire_notes(result)["wires"]
    load_saved_relations(result)
    for device in result["devices"].values():
        semantics = read_device_semantics(device)
        device["review"] = {"type": semantics["type"], "function": semantics["function"], "confirmed": False}
    for edge in result["connections"]:
        if edge["kind"] != "wire":
            continue
        note = notes[edge["id"]]
        if not isinstance(note["note"], str) or note["status"] not in {"candidate", "unresolved"}:
            raise ValueError("Invalid saved wire-text candidate")
        edge["review"] = {"a": edge["ends"][0], "b": edge["ends"][1], "note": note["note"], "confirmed": False}
        edge["note_evidence"] = deepcopy(note)
    return result
