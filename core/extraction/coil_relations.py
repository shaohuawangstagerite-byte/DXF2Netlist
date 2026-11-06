"""Extract supported coil relations from device attributes."""

from collections import defaultdict

from copy import deepcopy

import re

def extract_coil_relations(devices):
    """纯函数：只支持双端父CR结构，编号值不参与配对。"""
    connections, unresolved, seen = [], [], set()
    for key, device in sorted(devices.items()):
        pins = device.get("pins", [])
        ids = [pin["id"] for pin in pins]
        if len(ids) != len(set(ids)) or seen.intersection(ids):
            raise ValueError("端子 ID 重复或归属冲突")
        seen.update(ids)
        attributes = defaultdict(list)
        for row in device.get("attributes", []):
            attributes[row["tag"].upper()].append(row)
        families = [row["text"].strip().upper() for row in attributes.get("FAMILY", [])]
        if "TAG1" not in attributes and ("TAG2" in attributes or "CONTACT" in attributes):
            continue  # 清晰子触点不产生线圈关系。
        if "TAG1" not in attributes and "CR" not in families:
            continue
        if families and all(value and value != "CR" for value in families):
            continue  # 已知的其他类别不作为线圈。
        reason = None
        if (len(attributes["TAG1"]) != 1 or len(families) != 1 or families[0] != "CR" or
                not attributes["TAG1"][0]["text"].strip() or "TAG2" in attributes or "CONTACT" in attributes):
            reason = "missing_or_conflicting_coil_identity"
        terms = {tag: rows for tag, rows in attributes.items() if re.fullmatch(r"TERM\d+", tag)}
        anchors = {tag: rows for tag, rows in attributes.items() if re.fullmatch(r"X\dTERM\d+", tag)}
        # 2来自受支持的双端线圈结构；方向按接线属性编码识别。
        if reason is None and not len(pins) == len(terms) == len(anchors) == 2:
            reason = "unsupported_terminal_structure"
        suffixes, evidence = [], []
        if reason is None:
            for pin in sorted(pins, key=lambda p: p["id"]):
                match = re.fullmatch(r"X[1248]TERM(\d+)", pin.get("anchor_tag", "").upper())
                rows = anchors.get(pin.get("anchor_tag", "").upper(), [])
                labels = terms.get("TERM" + match.group(1), []) if match else []
                if (not match or len(rows) != 1 or len(labels) != 1 or not rows[0].get("handle") or
                        not labels[0].get("handle") or pin["id"] != "p:" + rows[0]["handle"] or
                        pin.get("anchor_handle") != rows[0]["handle"] or not isinstance(pin.get("number"), str) or
                        not pin["number"].strip() or pin["number"] != labels[0]["text"]):
                    reason = "ambiguous_terminal_mapping"
                    break
                suffixes.append(match.group(1))
                evidence.extend([rows[0], labels[0]])
            if reason is None and len(set(suffixes)) != 2:
                reason = "ambiguous_terminal_mapping"
        origin = device.get("source", {})
        identity = attributes["TAG1"] + attributes.get("FAMILY", [])
        if reason is None and (not all(origin.get(k) for k in ("sha256", "layout", "handle")) or
                               any(not row.get("handle") for row in identity)):
            reason = "missing_source"
        if reason is not None:
            unresolved.append({"device_id": key, "port_ids": sorted(ids), "reason": reason, "source": deepcopy(origin)})
            continue
        evidence = sorted(identity + evidence, key=lambda row: (row["tag"].upper(), row["handle"]))
        connections.append({"id": "coil:" + key, "kind": "coil", "ends": sorted(ids),
            "status": "candidate", "current_state": "unknown",
            "source": dict(deepcopy(origin), handles=[origin["handle"]]),
            "evidence": {"device_id": key, "attributes": deepcopy(evidence)}})
    return {"connections": connections, "unresolved": unresolved}
