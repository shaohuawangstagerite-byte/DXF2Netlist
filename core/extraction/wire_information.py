"""Collect signal information and associate independent wire text."""

import re

from ezdxf.math import Vec3

TEXT_MODE = "unique_nearest_TEXT_within_own_height"

def collect_signal_sources(document, connections):
    """R42/R43: native signal fields belong to a uniquely connected geometric net."""
    from collections import Counter, defaultdict
    from core.extraction.extract_devices import grid_configuration, grid_reference
    required, records = {"DESC1", "SIGCODE", "WIRENO", "XREF"}, []
    wire_net = {w:n for n, members in connections.get("nets", {}).items() for w in members}
    try:
        configuration = grid_configuration(document.modelspace())
        grid_error = None
    except (ValueError, TypeError) as error:
        configuration, grid_error = None, str(error)
    for insert in document.modelspace().query("INSERT"):
        attributes = list(insert.attribs)
        counts = Counter(a.dxf.tag.upper() for a in attributes)
        if not required <= counts.keys():
            continue
        mapped = {a.dxf.tag.upper():a for a in attributes}
        block = document.blocks[insert.dxf.name]
        definitions = list(block.query("ATTDEF"))
        def_counts = Counter(a.dxf.tag.upper() for a in definitions)
        defs = {a.dxf.tag.upper():a for a in definitions}
        # Two-digit suffixes and direction digits follow the published connection-attribute schema.
        anchors = [a for a in attributes if re.fullmatch(r"X[1248]TERM\d{2}", a.dxf.tag.upper())]
        record = {"insert_handle":insert.dxf.handle, "net":None, "binding_status":"unsupported_structure",
                  "fields":[{"handle":a.dxf.handle,"tag":a.dxf.tag,"raw":a.dxf.text,"hidden":a.is_invisible} for a in attributes if a.dxf.tag.upper() in required],
                  "reference_status":"unresolved", "value_validated":False}
        records.append(record)
        if len(anchors) != 1 or any(n != 1 for n in counts.values()) or insert.mcount != 1 or block.query("INSERT"):
            continue
        anchor = anchors[0]
        if any(def_counts[tag] != 1 for tag in required | {anchor.dxf.tag.upper()}):
            continue
        for field in record["fields"]:
            field["definition_handle"] = defs[field["tag"].upper()].dxf.handle
            field["definition_prompt"] = defs[field["tag"].upper()].dxf.prompt
            field["definition_default_raw"] = defs[field["tag"].upper()].dxf.text
        hits = connections["anchor_hits"].get(anchor.dxf.handle, [])
        nets = sorted({wire_net[w] for w in hits if w in wire_net})
        record.update(anchor_handle=anchor.dxf.handle, direct_wires=hits, net_candidates=nets,
                      description=mapped["DESC1"].dxf.text, signal_code=mapped["SIGCODE"].dxf.text,
                      reference_raw=mapped["XREF"].dxf.text, wire_number_raw=mapped["WIRENO"].dxf.text)
        if len(nets) != 1 or any(w not in wire_net for w in hits):
            record["binding_status"] = "unwired_or_ambiguous_net"
            continue
        record.update(net=nets[0], binding_status="unique_net", rule="R42",
                      meaning_scope="signal_description_and_declared_reference", grid_error=grid_error)
        prompt = defs["XREF"].dxf.prompt.strip().casefold()
        # Autodesk documents 'to' on source arrows and 'from' on destination arrows; custom prefixes stay unknown.
        record["role"] = {"to":"source", "from":"destination"}.get(prompt) if record["reference_raw"].casefold().startswith(prompt+" ") else None
        reference = record["reference_raw"][len(prompt):].strip() if record["role"] else ""
        record["target_location"] = reference if re.fullmatch(r"\d+[A-Z]\d+", reference) else None
        record["grid_location"] = None
        if configuration:
            try:
                record["grid_location"] = grid_reference(insert.ocs().to_wcs(insert.dxf.insert), configuration)
            except ValueError as error:
                record["grid_error"] = str(error)
    codes = defaultdict(list)
    for record in records:
        if record["net"] and record["signal_code"].strip():
            codes[record["signal_code"]].append(record)
    for record in records:
        if not record["net"]:
            continue
        opposite = {"source":"destination", "destination":"source"}.get(record["role"])
        peers = [p for p in codes[record["signal_code"]] if opposite and p.get("role") == opposite]
        record["peer_candidates"] = [p["insert_handle"] for p in peers]
        if len(peers) != 1 or len(codes[record["signal_code"]]) != 2:
            continue
        peer = peers[0]
        record.update(peer_insert=peer["insert_handle"], peer_net=peer["net"], reference_rule="R43")
        if not all((record["target_location"], peer["target_location"], record["grid_location"], peer["grid_location"])):
            continue
        record["reference_matches_peer"] = record["target_location"] == peer["grid_location"]
        record["reference_status"] = "verified_reciprocal_grid" if record["reference_matches_peer"] and peer["target_location"] == record["grid_location"] else "position_mismatch_pending"
    return records

def associate_wire_text(document, data):
    """Apply SPEC R12; geometry proposes candidates without assigning semantics."""
    wires, statuses = {item["id"]: [] for item in data["lines"]}, {}
    # The margin is SPEC R7; the search radius is each source TEXT's own height.
    tolerance = data["tolerance"]
    for text in document.modelspace().query("TEXT"):
        point = text.ocs().to_wcs(text.get_placement()[1])
        eligible = []
        for line in data["lines"]:
            start, end = map(Vec3, line["ends"])
            direction = end - start
            if not direction.magnitude_square:
                continue
            parameter = (point - start).dot(direction) / direction.magnitude_square
            # 0..1 is the segment's affine domain, not an empirical tolerance.
            if 0 <= parameter <= 1:
                distance = point.distance(start + direction * parameter)
                if distance <= text.dxf.height + tolerance:
                    eligible.append((distance, line["id"]))
        eligible.sort()
        if not eligible:
            statuses[text.dxf.handle] = {"status": "unmatched", "wire_handle": None}
        elif len(eligible) > 1 and eligible[1][0] - eligible[0][0] <= tolerance:
            statuses[text.dxf.handle] = {"status": "ambiguous", "wire_handle": None}
        else:
            distance, handle = eligible[0]
            statuses[text.dxf.handle] = {"status": "unique", "wire_handle": handle}
            wires[handle].append({"handle": text.dxf.handle, "text": text.dxf.text,
                                  "layer": text.dxf.layer, "distance": distance, "status": "candidate"})
    return {"wires": wires, "statuses": statuses}
