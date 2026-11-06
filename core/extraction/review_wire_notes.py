"""Save and validate wire text candidates for netlist queries."""

from core.extraction.wire_information import TEXT_MODE, associate_wire_text

def export_wire_texts(document, netlist):
    """Serialize unchanged R12 matches, including unbound raw text and evidence."""
    binding = associate_wire_text(document, netlist["geometry"])
    digest, tolerance = netlist["source"]["sha256"], netlist["geometry"]["tolerance"]
    matched = {c["handle"]: c for candidates in binding["wires"].values() for c in candidates}
    texts = {}
    for entity in document.modelspace().query("TEXT MTEXT"):
        handle, kind = entity.dxf.handle, entity.dxftype()
        status = binding["statuses"].get(handle, {"status": "unsupported_mtext", "wire_handle": None})
        candidate = matched.get(handle)
        height = entity.dxf.height if kind == "TEXT" else None
        texts[handle] = {"handle": handle, "uid": digest + ":" + handle, "entity_type": kind,
            "text": entity.dxf.text if kind == "TEXT" else entity.text, "layer": entity.dxf.layer,
            "wire_id": "w:" + status["wire_handle"] if status["wire_handle"] else None,
            "binding_status": status["status"], "status": "unconfirmed", "confirmed": False,
            "evidence": {"rule": "R12", "mode": TEXT_MODE, "tolerance": tolerance,
                "text_height": height, "max_distance": height + tolerance if height is not None else None,
                "distance": candidate["distance"] if candidate else None,
                "projection_within_segment": True if candidate else None}}
    wires = {}
    for handle, candidates in binding["wires"].items():
        single = len(candidates) == 1 and bool(candidates[0]["text"].strip())
        wires["w:" + handle] = {"note": candidates[0]["text"] if single else "",
            "text_candidates": [dict(c, wire_id="w:" + handle, confirmed=False,
                                     evidence=texts[c["handle"]]["evidence"]) for c in candidates],
            "status": "candidate" if single else "unresolved",
            "rule": "R12_unique_TEXT_and_single_candidate_per_LINE", "source_sha256": digest}
    return {"schema": "wire_text_candidates_v1", "wires": wires, "texts": texts,
            "text_statuses": binding["statuses"], "source_sha256": digest}

def collect_review_wire_notes(netlist):
    """Read serialized evidence only; a missing export never triggers DXF access."""
    stored = netlist.get("wire_texts")
    if (not isinstance(stored, dict) or stored.get("schema") != "wire_text_candidates_v1"
            or not isinstance(stored.get("texts"), dict) or not isinstance(stored.get("wires"), dict)):
        raise ValueError("网表缺少完整的 TEXT 关联结果，请重新提取")
    expected = {"w:" + line["id"] for line in netlist["geometry"]["lines"]}
    if stored.get("source_sha256") != netlist["source"]["sha256"] or set(stored["wires"]) != expected:
        raise ValueError("网表 TEXT 关联的来源或导线集合不一致")
    return stored
