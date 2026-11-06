"""Extract supported contact relations from device attributes."""

from collections import defaultdict

from copy import deepcopy

import re

def extract_contact_relations(devices):
    """仅支持两端子NO；COMMON是TERM后缀，名称和坐标不参与配对。"""
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
        child_relay = "TAG2" in attributes and any(row["text"].strip().upper() == "CR" for row in attributes.get("FAMILY", []))
        if "CONTACT" not in attributes and not child_relay:
            continue  # 父线圈和普通设备不新增关系；疑似子触点的缺失属性须登记。
        reason = None
        required = ("CONTACT", "FAMILY", "TAG2")
        if any(len(attributes[tag]) != 1 for tag in required) or "TAG1" in attributes:
            reason = "missing_or_duplicate_contact_attributes"
        elif attributes["CONTACT"][0]["text"].strip().upper() != "NO" or attributes["FAMILY"][0]["text"].strip().upper() != "CR":
            reason = "unsupported_contact_type_or_family"
        # 2来自受支持的两端子触点结构，不是几何容差。
        terms = {tag: rows for tag, rows in attributes.items() if re.fullmatch(r"TERM\d+", tag)}
        if reason is None and (len(pins) != 2 or len(terms) != 2):
            reason = "unsupported_terminal_structure"
        suffixes, evidence = [], []
        if reason is None:
            for pin in sorted(pins, key=lambda p: p["id"]):
                # 按接线方向编码及TERM同后缀关系匹配；不按编号值推断。
                tag = pin.get("anchor_tag", "").upper()
                match = re.fullmatch(r"X[1248]TERM(\d+)", tag)
                rows = attributes.get(tag, [])
                labels = terms.get("TERM" + match.group(1), []) if match else []
                if (not match or len(rows) != 1 or len(labels) != 1 or not rows[0].get("handle") or
                        not labels[0].get("handle") or pin["id"] != "p:" + rows[0]["handle"] or
                        pin.get("anchor_handle", rows[0]["handle"]) != rows[0]["handle"] or
                        not isinstance(pin.get("number"), str) or not pin["number"].strip() or
                        labels[0]["text"] != pin["number"]):
                    reason = "ambiguous_terminal_mapping"
                    break
                suffixes.append(match.group(1))
                evidence.extend([rows[0], labels[0]])
            if reason is None and len(set(suffixes)) != 2:
                reason = "ambiguous_terminal_mapping"
        common = attributes.get("COMMON", [])
        if reason is None and (len(common) > 1 or common and common[0]["text"].strip() not in suffixes):
            reason = "invalid_common_suffix"
        origin = device.get("source", {})
        if reason is None and any(not row.get("handle") for tag in required for row in attributes[tag]):
            reason = "missing_source_attributes"
        if reason is None and any(not row.get("handle") for row in common):
            reason = "missing_source_attributes"
        if reason is None and not all(origin.get(field) for field in ("sha256", "layout", "handle")):
            reason = "missing_source"
        if reason is not None:
            unresolved.append({"device_id": key, "port_ids": sorted(ids), "reason": reason, "source": deepcopy(origin)})
            continue
        evidence += [attributes[tag][0] for tag in required] + common
        evidence = sorted(evidence, key=lambda row: (row["tag"].upper(), row["handle"]))
        connections.append({"id": "contact:" + key, "kind": "contact", "ends": sorted(ids),
            "status": "candidate", "contact_type": "NO", "normal_state": "open", "current_state": "unknown",
            "source": dict(deepcopy(origin), handles=[origin["handle"]]),
            "evidence": {"device_id": key, "attributes": deepcopy(evidence)}})
    return {"connections": connections, "unresolved": unresolved}
