"""Extract a source-backed netlist from a DXF drawing."""

import hashlib

import json

import re

from pathlib import Path

import ezdxf

from core.extraction.full_rules import FLOAT_ULPS, classify, probe

from core.extraction.full_connections import connect

from core.extraction.compact_netlist import wire_connections

from core.extraction.component_names import COMPONENT_MODE, resolve_component_names

from core.extraction.reference_anchors import classify_reference

from core.extraction.connector_shapes import collect_connector_shapes

from core.extraction.connector_mating import MATING_MODE, pair_connectors

from core.extraction.review_wire_notes import export_wire_texts

from core.extraction.device_semantics import infer_device_semantics

from core.extraction.relations import collect_relations

def extract(source, spec):
    """Keep every source anchor; apply SPEC R13-R15/R50 without replacing raw TAGs."""
    source, spec = Path(source), Path(spec)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    policy = json.loads(re.search(r"```json\s*(.*?)\s*```", spec.read_text(encoding="utf-8"), re.S).group(1))
    supported = {"anchor_tag_regex": r"X(\d)TERM(\d+)", "label_tag_regex": r"TERM(\d+)",
                 "float_ulps": FLOAT_ULPS, "wire_mode": "attribute_seeded_endpoint_graph",
                 "marker_mode": "attribute_free_concentric_circle_only_block",
                 "component_name_mode": COMPONENT_MODE}
    if any(policy.get(key) != value for key, value in supported.items()):
        raise ValueError("Unsupported geometry rules")
    mating_mode = policy.get("connector_mating_mode")
    if mating_mode not in (None, MATING_MODE):
        raise ValueError("Unsupported connector mating mode")
    supported["connector_mating_mode"] = mating_mode
    doc = ezdxf.readfile(source)
    facts = probe(doc)
    devices, anchors = {}, []
    sheets = {a.dxf.text for i in doc.modelspace().query("INSERT") for a in i.attribs
              if a.dxf.tag.upper() == "SHEET" and a.dxf.text.strip()}
    origin = {"sha256": digest, "layout": "Model", "page": next(iter(sheets)) if len(sheets) == 1 else None}
    for insert in doc.modelspace().query("INSERT"):
        raw = [{"handle": a.dxf.handle, "tag": a.dxf.tag, "text": a.dxf.text,
                "hidden": a.is_invisible} for a in insert.attribs]
        names = [a for a in raw if a["tag"].upper() in {"TAG1", "TAG2"}]
        name = names[0]["text"] if len(names) == 1 and names[0]["text"].strip() else None
        name_status = "attribute_candidate" if name is not None else "ambiguous" if len(names) > 1 else "unknown"
        pins = []
        for attribute in insert.attribs:
            match = re.fullmatch(supported["anchor_tag_regex"], attribute.dxf.tag.upper())
            if not match:
                continue
            suffix = match.group(2)
            numbers = [a for a in raw if a["tag"].upper() == "TERM" + suffix]
            number = numbers[0]["text"] if len(numbers) == 1 and numbers[0]["text"].strip() else None
            number_status = "raw" if number is not None else "ambiguous" if len(numbers) > 1 else "empty" if numbers else "missing"
            point = list(attribute.ocs().to_wcs(attribute.dxf.insert))
            anchors.append({"insert": insert, "attribute": attribute, "point": point})
            pins.append({"id": "p:" + attribute.dxf.handle, "uid": digest + ":" + attribute.dxf.handle,
                         "anchor_handle": attribute.dxf.handle, "anchor_tag": attribute.dxf.tag,
                         "anchor_status": "ambiguous" if sum(a["tag"].upper() == attribute.dxf.tag.upper() for a in raw) > 1 else "raw",
                         "point_wcs": point, "number": number, "number_status": number_status,
                         "number_attributes": numbers, "ownership_status": name_status})
        if pins:
            devices["d:" + insert.dxf.handle] = {"name": name, "name_status": name_status,
                "name_reason": None if name is not None else "multiple TAG fields" if len(names) > 1 else "empty TAG" if names else "missing TAG",
                "name_attributes": names, "identity_status": "diagram_only", "pins": pins,
                "attributes": raw, "source": dict(origin, handle=insert.dxf.handle)}
    # probe uses a tag dictionary; replace its anchors so duplicate tags cannot lose source nodes.
    facts["anchors"] = [dict(a, point=ezdxf.math.Vec3(a["point"])) for a in anchors]
    selection = classify(doc, facts)
    # Duplicate relevant tags or multiple visible titles cannot establish unique column evidence.
    blocked = False
    for device in devices.values():
        relevant = [a["tag"].upper() for a in device["attributes"]
                    if re.fullmatch(r"(?:TAG[12]|TERM\d+|X\d(?:TERM\d+|LINK))", a["tag"].upper())]
        visible = [a for a in device["name_attributes"] if not a["hidden"] and a["text"].strip()]
        blocked |= len(relevant) != len(set(relevant)) or len(visible) > 1
    terminals = [{"insert": d["source"]["handle"], "id": h} for d in devices.values()
                 for h in sorted({p["number_attributes"][0]["handle"] for p in d["pins"]
                                  if p["number_status"] == "raw"})]
    names = resolve_component_names(doc, {"terminals": [] if blocked else terminals,
                                         "tolerance": selection["tolerance"]})
    for device in devices.values():
        visible = [a for a in device["name_attributes"] if not a["hidden"] and a["text"].strip()]
        fallback = {"name": visible[0]["text"] if len(visible) == 1 else None,
                    "status": "visible_TAG" if len(visible) == 1 else "ambiguous_source_attributes" if blocked else "no_visible_name",
                    "header_insert": device["source"]["handle"] if len(visible) == 1 else None,
                    "header_attributes": [a["handle"] for a in visible] if len(visible) == 1 else []}
        evidence = names.get(device["source"]["handle"], fallback)
        device.update(raw_name=device["name"], name=evidence["name"],
                      name_status="candidate" if evidence["name"] is not None else "unknown",
                      name_reason=None if evidence["name"] is not None else evidence["status"],
                      name_source=dict(evidence, rule="R13-R15/R50"))
        for pin in device["pins"]:
            pin["ownership_status"] = device["name_status"]
    data = {"source_sha256": digest, "spec_sha256": hashlib.sha256(spec.read_bytes()).hexdigest(),
            "tolerance": selection["tolerance"], "terminals": [],
            "lines": [{"id": e.dxf.handle, "ends": [list(e.dxf.start), list(e.dxf.end)]}
                      for e in selection["wire_lines"]],
            "anchors": [{"id": a["attribute"].dxf.handle, "point": a["point"]} for a in anchors],
            "markers": [{"id": m["insert"].dxf.handle, "point": list(m["point"])} for m in facts["markers"]]}
    graph = connect(data, "explicit_points")
    connections = wire_connections(data, graph)
    for edge in connections:
        edge["source"] = dict(origin, handles=edge["source"])
    for device in devices.values():
        for pin in device["pins"]:
            pin["wire_ids"] = ["w:" + h for h in graph["anchor_hits"][pin["anchor_handle"]]]
            pin["connection_status"] = "candidate" if pin["wire_ids"] else "unwired"
    signal_references = {}
    for key, device in list(devices.items()):
        reference = classify_reference(device)
        if reference is not None:
            signal_references[reference["id"]] = reference
            del devices[key]
    mating = {"mode": mating_mode, "profiles": [], "unresolved": []}
    if mating_mode is not None:
        shapes = collect_connector_shapes(doc, facts, selection["tolerance"])
        paired = pair_connectors(shapes["profiles"], selection["tolerance"])
        mating.update(profiles=shapes["profiles"], unresolved=shapes["unresolved"] + paired["unresolved"])
        for unresolved in mating["unresolved"]:
            unresolved["port_ids"] = ["p:" + unresolved["port"]] if "port" in unresolved else [
                p["id"] for d in devices.values() if d["source"]["handle"] == unresolved["insert"] for p in d["pins"]]
            unresolved["source"] = dict(origin, handles=[unresolved["insert"]])
        for pair in paired["pairs"]:
            connections.append({"id": "mate:" + ":".join(pair["ports"]), "kind": "connector_mating",
                "ends": ["p:" + h for h in pair["ports"]], "status": "candidate", "physical_state": "unknown",
                "source": dict(origin, handles=[p["insert"] for p in pair["profiles"]]), "evidence": pair})
    connector_groups = {}
    for identity, device in devices.items():
        handle = device["source"]["handle"]
        evidence = {key: [r for r in mating[key] if r["insert"] == handle] for key in ("profiles", "unresolved")}
        device["semantics"] = dict(infer_device_semantics(device, evidence), confirmed=False)
        connector = device["semantics"].get("connector")
        if connector is not None:
            group = connector_groups.setdefault(connector["group_id"], {
                "name": connector["name"], "status": connector["status"], "confirmed": False, "terminal_ids": []})
            group["terminal_ids"].append(identity)
    netlist = {"source": dict(origin, path=str(source.resolve())), "rules": supported,
            "devices": devices, "connector_groups": connector_groups, "signal_references": signal_references,
            "connections": connections, "connector_mating": mating, "geometry": data, "graph": graph,
            "coverage": {"anchors": len(anchors), "wire_candidates": len(data["lines"]),
                         "terminal_anchors": sum(len(d["pins"]) for d in devices.values()),
                         "signal_reference_anchors": len(signal_references),
                         "unknown_terminal_names": sum(d["name"] is None for d in devices.values() for p in d["pins"]),
                         "name_inheritance_blocked": blocked,
                         "unclassified_lines": len(facts["lines"]) - len(data["lines"]),
                         "unmatched_anchors": ["p:" + h for h, hits in graph["anchor_hits"].items() if not hits],
                         "unsupported": ["non-Model layouts, nested/array INSERTs are rejected",
                                          "no reference pairing or reference network merging; mating does not merge wire nets"]}}
    netlist["wire_texts"] = export_wire_texts(doc, netlist)
    netlist["relations"] = dict(collect_relations(doc, netlist),
                                schema="extracted_relations_v1", source_sha256=digest)
    if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
        raise ValueError("Source changed during extraction")
    return netlist
