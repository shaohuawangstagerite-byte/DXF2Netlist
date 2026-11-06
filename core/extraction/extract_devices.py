"""Read device attributes, drawing grids and location references."""

import math

def attributes(insert):
    records = [{"tag": item.dxf.tag, "handle": item.dxf.handle, "text": item.dxf.text}
               for item in insert.attribs]
    mapped = {item["tag"].upper(): item for item in records}
    if len(mapped) != len(records):
        raise ValueError(f"Duplicate attribute tags on INSERT {insert.dxf.handle}")
    return mapped

def grid_configuration(layout):
    required = {"SHEET", "DATUMX", "DATUMY", "DISTH", "DISTV", "CHAR_H",
                "CHAR_V", "HORIZ_FIRST", "XY_DELIM", "XREFFMT", "REFNUMS"}
    candidates = []
    for insert in layout.query("INSERT"):
        mapped = attributes(insert)
        if required <= mapped.keys():
            candidates.append((insert, {key: item["text"] for key, item in mapped.items()}))
    if len(candidates) != 1:
        raise ValueError("Exactly one drawing grid configuration is required")
    insert, values = candidates[0]
    if any(values[key] != expected for key, expected in
           {"HORIZ_FIRST": "0", "XY_DELIM": "", "XREFFMT": "%S%N", "REFNUMS": "4"}.items()):
        raise ValueError("Unsupported cross-reference grid format")
    if len(values["CHAR_V"]) != 1 or not "A" <= values["CHAR_V"] <= "Z":
        raise ValueError("Unsupported vertical grid labels")
    numbers = [float(values[key]) for key in ("DATUMX", "DATUMY", "DISTH", "DISTV")]
    if not all(math.isfinite(value) for value in numbers) or min(numbers[2:]) <= 0:
        raise ValueError("Grid intervals must be finite and positive")
    if not values["SHEET"] or int(values["CHAR_H"]) < 1:
        raise ValueError("Invalid sheet or horizontal grid labels")
    return {"source_handle": insert.dxf.handle, "values": values}

def grid_reference(point, configuration):
    values = configuration["values"]
    column = math.floor((point.x - float(values["DATUMX"])) / float(values["DISTH"]))
    row = math.floor((float(values["DATUMY"]) - point.y) / float(values["DISTV"]))
    vertical = ord(values["CHAR_V"]) + row
    if column < 0 or not ord("A") <= vertical <= ord("Z"):
        raise ValueError("Position is outside the supported drawing grid")
    return f'{values["SHEET"]}{chr(vertical)}{int(values["CHAR_H"]) + column}'

def reference_tokens(text):
    return {part.strip() for part in text.replace("%%u", "").split(",") if part.strip()}

def occurrence(insert, document, source, configuration, layout_name):
    mapped = attributes(insert)
    tag_keys = [key for key in ("TAG1", "TAG2") if key in mapped]
    if not tag_keys:
        return None
    if len(tag_keys) != 1 or not mapped[tag_keys[0]]["text"].strip():
        raise ValueError(f"Ambiguous or empty device tag: {insert.dxf.handle}")
    if mapped.get("FAMILY", {}).get("text") != "CR":
        raise ValueError(f"Unsupported device family: {insert.dxf.handle}")
    tag_key = tag_keys[0]
    role = "coil" if tag_key == "TAG1" else {"NO": "contact_no", "NC": "contact_nc"}.get(
        mapped.get("CONTACT", {}).get("text"))
    if role is None:
        raise ValueError(f"Unsupported contact role: {insert.dxf.handle}")
    block = document.blocks.get(insert.dxf.name)
    if insert.dxf.row_count != 1 or insert.dxf.column_count != 1 or block.query("INSERT"):
        raise ValueError("Nested or array INSERT is not supported")
    position = insert.ocs().to_wcs(insert.dxf.insert)
    scope_values = {name: mapped.get(tag, {}).get("text", "").strip() or None
                    for name, tag in (("installation", "INST"), ("location", "LOC"))}
    scope = scope_values if any(scope_values.values()) else None
    semantic_tags = {"TAG1", "TAG2", "FAMILY", "CONTACT", "LOC", "INST", "XREF", "XREFNO", "XREFNC"}
    return {
        "id": f'occurrence:{source["sha256"][:16]}:{insert.dxf.handle}',
        "source_handle": insert.dxf.handle,
        "source_reference": {**source, "handle": insert.dxf.handle},
        "tag_raw": mapped[tag_key]["text"],
        "tag_source": {"entity_type": "ATTRIB", "handle": mapped[tag_key]["handle"],
                       "tag": mapped[tag_key]["tag"]},
        "device_id": None, "scope": scope, "role": role,
        "grid_reference": grid_reference(position, configuration),
        "association": {"method": "unresolved", "reason": "missing_or_ambiguous_evidence"},
        "attributes": [value for key, value in mapped.items() if key in semantic_tags],
        "graphics": {"block_name": block.name, "block_record_handle": block.block_record_handle,
                     "primitive_handles": [entity.dxf.handle for entity in block if entity.dxftype() != "ATTDEF"]},
        "coordinate_space": {"insert": "OCS", "matrix_from": "block_local",
                             "matrix_to": f"{layout_name} WCS", "matrix_convention": "row_vector_p_times_M",
                             "insunits": source["insunits"]},
        "transform": {
            "insert_ocs": list(insert.dxf.insert),
            "scale_xyz": [insert.dxf.xscale, insert.dxf.yscale, insert.dxf.zscale],
            "rotation_degrees": insert.dxf.rotation,
            "extrusion": list(insert.dxf.extrusion),
            "block_base_point": list(block.block.dxf.base_point),
            "row_count": insert.dxf.row_count, "column_count": insert.dxf.column_count,
            "row_spacing": insert.dxf.row_spacing, "column_spacing": insert.dxf.column_spacing,
            "matrix44": [list(row) for row in insert.matrix44().rows()]
        }
    }
