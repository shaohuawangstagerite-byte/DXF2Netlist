"""Infer and validate device semantics without confirming physical state."""

from collections import defaultdict

from copy import deepcopy

import json

from core.extraction.contact_relations import extract_contact_relations

def infer_device_semantics(device, connector_evidence=None):
    """Keep description text verbatim; qualify ordinary NO/NC contact behavior."""
    attributes = defaultdict(list)
    for row in device.get("attributes", []):
        attributes[row["tag"].upper()].append(row)
    family = attributes["FAMILY"][0]["text"].strip().upper() if len(attributes["FAMILY"]) == 1 else ""
    description = "；".join(attributes[tag][0]["text"] for tag in ("DESC1", "DESC2", "DESC3")
                           if len(attributes[tag]) == 1 and attributes[tag][0]["text"].strip())
    result = {"type": {"CR": "控制继电器", "DO": "二极管"}.get(family, ""), "function": description,
              "function_kind": "description" if description else None, "status": "candidate",
              "rule": "documented_family_contact_desc_v1", "current_state": "unknown",
              "attributes": deepcopy([r for tag in ("FAMILY", "CONTACT", "DESC1", "DESC2", "DESC3") for r in attributes[tag]]),
              "source": deepcopy(device.get("source", {})), "assumption": "",
              "references": ["https://help.autodesk.com/cloudhelp/2023/ENU/AutoCAD-Electrical/files/GUID-E60FDE25-3CF0-492F-AFD2-C30DA9DCCDA7.htm",
                             "https://help.autodesk.com/cloudhelp/2016/ENU/AutoCAD-Electrical/files/GUID-A42DA038-B1AB-4401-BD71-BC7A683D8DF7.htm"]}
    if family and family not in {"CR", "DO", "PJ"}:
        result.update(type="", function="", function_kind=None, status="unknown",
                      reason="unsupported_family")
    contact = attributes["CONTACT"][0]["text"].strip().upper() if len(attributes["CONTACT"]) == 1 else ""
    if family == "CR" and contact in {"NO", "NC"}:
        # Reuse existing source/pin/TERM checks. CONTACT meaning is checked separately;
        # normalizing only this temporary copy lets the NO-only validator check NC structure.
        normalized = deepcopy(device)
        for row in normalized["attributes"]:
            if row["tag"].upper() == "CONTACT":
                row["text"] = "NO"
        checked = extract_contact_relations({"device": normalized})
        if checked["connections"]:
            result["type"] = "控制继电器" + ("常闭" if contact == "NC" else "常开") + "触点"
            result["function"] = ("线圈未励磁时闭合，励磁时断开" if contact == "NC"
                                  else "线圈未励磁时断开，励磁时闭合")
            result["function_kind"] = "behavior"
            result["assumption"] = "普通非保持继电器的参考行为；当前通断状态未知。"
            result["references"].append("https://www.ia.omron.com/support/guide/36/explanation_of_terms.html")
        else:
            result["reason"] = checked["unresolved"][0]["reason"]
    result["category"] = "component"
    pins = device.get("pins", [])
    if family == "PJ" and len(pins) == 1 and pins[0].get("number"):
        evidence = deepcopy(connector_evidence or {"profiles": [], "unresolved": []})
        profiles = [p for p in evidence["profiles"] if p["insert"] == device.get("source", {}).get("handle")
                    and p["port"] == pins[0].get("anchor_handle")]
        role = profiles[0]["role"] if len(profiles) == 1 else None
        name, source = device.get("name"), device.get("source", {})
        group_id = json.dumps([source.get("sha256"), source.get("layout"), source.get("page"),
                               name or {"unknown_insert": source.get("handle")}], ensure_ascii=False)
        result.update(category="connector_terminal", type={"pin": "插针", "socket": "插孔"}.get(role, ""),
                      function="", function_kind=None, rule="PJ_single_numbered_pin_R46_profile",
                      connector_evidence=evidence,
                      connector={"group_id": group_id, "name": name, "status": device.get("name_status", "unknown"),
                                 "name_source": deepcopy(device.get("name_source", {})), "confirmed": False})
    if not result["type"] and not result["function"]:
        result["status"] = "unknown"
    return result

def read_device_semantics(device):
    """Read exported candidates without rerunning attribute conversion."""
    stored = device.get("semantics")
    required = {"type", "function", "function_kind", "status", "rule", "attributes", "source",
                "assumption", "references", "current_state", "confirmed"}
    if (not isinstance(stored, dict) or not required <= stored.keys()
            or any(not isinstance(stored[k], str) for k in ("type", "function", "rule", "assumption"))
            or not isinstance(stored["attributes"], list) or not isinstance(stored["references"], list)
            or stored["confirmed"] is not False or stored["current_state"] != "unknown"
            or stored["status"] not in {"candidate", "unknown"}
            or stored["function_kind"] not in {"behavior", "description", None}):
        raise ValueError("网表缺少完整的元件类型或 Function 转换结果，请重新提取")
    if stored["source"] != device.get("source", {}) or any(a not in device.get("attributes", []) for a in stored["attributes"]):
        raise ValueError("元件转换依据与原始属性或来源不一致")
    return stored
