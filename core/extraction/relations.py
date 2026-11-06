"""Collect contact, coil, control, signal and ground relation evidence."""

from copy import deepcopy

from core.extraction.contact_relations import extract_contact_relations

from core.extraction.coil_relations import extract_coil_relations

from core.extraction.extract_devices import grid_configuration, occurrence, reference_tokens

from core.extraction.wire_information import collect_signal_sources

from core.extraction.grounds import extract_ground_candidates

def collect_relations(document, raw):
    """复用已验证结构；相同名称不足以建立控制或信号连接。"""
    normalized = deepcopy(raw["devices"])
    for device in normalized.values():
        for attribute in device["attributes"]:
            if attribute["tag"].upper() == "CONTACT" and attribute["text"].strip().upper() == "NC":
                attribute["text"] = "NO"  # 仅借原函数检查双端触点结构，随后恢复NC原文。
    contacts = extract_contact_relations(normalized)
    coils = extract_coil_relations(raw["devices"])
    connections = contacts["connections"] + coils["connections"]
    unresolved = [dict(r, kind="contact") for r in contacts["unresolved"]]
    unresolved += [dict(r, kind="coil") for r in coils["unresolved"]]
    for edge in contacts["connections"]:
        original = raw["devices"][edge["evidence"]["device_id"]]
        contact = next(a["text"].strip().upper() for a in original["attributes"] if a["tag"].upper() == "CONTACT")
        edge.update(contact_type=contact, normal_state="closed" if contact == "NC" else "open")
        handles = {a["handle"] for a in edge["evidence"]["attributes"]}
        edge["evidence"]["attributes"] = deepcopy([a for a in original["attributes"] if a["handle"] in handles])
    locations, grid_error = {}, None
    try:
        configuration = grid_configuration(document.modelspace())
    except (ValueError, TypeError) as error:
        configuration, grid_error = None, str(error)
    origin = dict(raw["source"], insunits=document.header.get("$INSUNITS", 0))
    for edge in connections:
        handle = edge["source"]["handle"]
        try:
            if configuration is None:
                raise ValueError(grid_error)
            insert = document.entitydb.get(handle)
            if insert is None:
                raise ValueError("符号来源不存在")
            locations[edge["id"]] = occurrence(insert, document, origin, configuration, raw["source"]["layout"])
        except (ValueError, TypeError) as error:
            unresolved.append({"kind": "control", "object": edge["id"], "reason": str(error)})
    controls = []
    for contact in contacts["connections"]:
        child, matches = locations.get(contact["id"]), []
        if child is None:
            continue
        child_fields = {a["tag"].upper(): a["text"] for a in child["attributes"]}
        parent_tag = "XREFNC" if contact["contact_type"] == "NC" else "XREFNO"
        for coil in coils["connections"]:
            parent = locations.get(coil["id"])
            if parent is None:
                continue
            fields = {a["tag"].upper(): a["text"] for a in parent["attributes"]}
            if (child["tag_raw"].strip() == parent["tag_raw"].strip() and child["scope"] == parent["scope"]
                    and parent["grid_reference"] in reference_tokens(child_fields.get("XREF", ""))
                    and child["grid_reference"] in reference_tokens(fields.get(parent_tag, ""))):
                matches.append(coil)
        if len(matches) == 1:
            coil = matches[0]
            controls.append({"id": "control:" + contact["id"], "kind": "control",
                "ends": [coil["id"], contact["id"]], "association_status": "verified_reciprocal_reference",
                "source": dict(raw["source"], handles=[coil["source"]["handle"], contact["source"]["handle"]]),
                "evidence": {"coil_location": locations[coil["id"]], "contact_location": child}})
        else:
            unresolved.append({"kind": "control", "object": contact["id"],
                "reason": "no_reciprocal_reference" if not matches else "ambiguous_reciprocal_reference",
                "candidates": [c["id"] for c in matches]})
    signal_sources = collect_signal_sources(document, raw["graph"])
    references = raw.get("signal_references", {})
    by_insert = {r["source"]["handle"]: identity for identity, r in references.items()}
    statuses, signals, paired = {}, [], set()
    for record in signal_sources:
        identity = by_insert.get(record["insert_handle"])
        if identity is None:
            continue
        statuses[identity] = "unresolved"
        peer = by_insert.get(record.get("peer_insert"))
        if record.get("reference_status") == "verified_reciprocal_grid" and peer:
            statuses[identity] = "verified_reciprocal_grid"
            pair = tuple(sorted((identity, peer)))
            if pair not in paired:
                paired.add(pair)
                signals.append({"id": "signal:" + ":".join(pair), "kind": "signal", "ends": list(pair),
                    "pairing_status": "verified_reciprocal_grid", "source": dict(raw["source"],
                        handles=[references[p]["source"]["handle"] for p in pair])})
        else:
            unresolved.append({"kind": "reference", "object": identity,
                "reason": record.get("reference_status", "not_evaluated")})
    return {"connections": connections + controls + signals, "reference_statuses": statuses,
            "unresolved": unresolved, "signal_sources": signal_sources, "locations": locations,
            "ground_sources": extract_ground_candidates(document, raw) if "geometry" in raw else []}
