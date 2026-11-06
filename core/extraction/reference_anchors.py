"""Classify signal reference anchors and parse supported addresses."""

import re

def classify_reference(device):
    """Classify the audited attribute structure; address errors never discard a reference."""
    attributes = device["attributes"]
    fields = {a["tag"].upper(): a for a in attributes}
    if len(device["pins"]) != 1 or len(fields) != len(attributes):
        return None
    pin = device["pins"][0]
    if not re.fullmatch(r"X[1248]TERM\d+", pin["anchor_tag"].upper()):
        return None
    if set(fields) != {"DESC1", "SIGCODE", "XREF", "WIRENO", pin["anchor_tag"].upper()}:
        return None  # Missing, duplicated or additional identity fields keep the existing path.
    raw = fields["XREF"]["text"]
    # R51: supported addresses use two page digits, one letter grid and digit grid.
    match = re.fullmatch(r"\s*(to|from)\s+(\d{2})([A-Za-z])(\d+)\s*", raw, re.I)
    prefix = re.match(r"\s*(to|from)\b", raw, re.I)
    return {**pin, "kind": "signal_reference_anchor", "name": None, "raw_name": device["raw_name"],
            "name_status": "not_applicable", "number": None, "number_status": "not_applicable",
            "ownership_status": "not_applicable", "name_reason": "signal_reference_anchor",
            "name_attributes": device["name_attributes"], "attributes": attributes, "source": device["source"],
            "name_source": {"status": "not_applicable", "rule": "R51", "header_insert": None,
                            "header_attributes": [], "warnings": []},
            "classification": {"rule": "R51", "status": "attribute_structure_candidate"},
            "fields": {tag: dict(fields[tag]) for tag in ("DESC1", "SIGCODE", "XREF", "WIRENO")},
            "field_status": {tag: "empty" if not fields[tag]["text"].strip() else "placeholder"
                             if tag == "WIRENO" and fields[tag]["text"].strip() == "???" else "raw"
                             for tag in ("DESC1", "SIGCODE", "XREF", "WIRENO")},
            "reference_address": {"status": "parsed" if match else "unparsed" if raw.strip() else "empty",
                "direction": prefix.group(1).lower() if prefix else None,
                "page": match.group(2) if match else None,
                "x_grid": match.group(3).upper() if match else None,
                "y_grid": match.group(4) if match else None,
                "reason": None if match else "unsupported_XREF_format" if raw.strip() else "empty_XREF"},
            "reference_pairing_status": "not_evaluated"}
