"""Query complete wire networks and attach component information."""

from collections import Counter, defaultdict, deque

from copy import deepcopy

from hashlib import sha256

import json

from pathlib import Path

def add_chain_component_info(chain, standard_netlist):
    """从标准网表附上链内元件资料；完整端子表另标是否在链内。"""
    enriched = deepcopy(chain)
    port_groups = {}
    for port_id, port in chain.get("ports", {}).items():
        if port.get("device_id"):
            port_groups.setdefault(port["device_id"], []).append(port_id)
    components = {}
    for device_id, port_ids in sorted(port_groups.items()):
        if device_id not in standard_netlist["devices"]:
            raise ValueError(f"链路引用了未知元件：{device_id}")
        device = standard_netlist["devices"][device_id]
        review = device.get("review", {})
        attributes = {item["tag"].upper(): item["text"] for item in device.get("attributes", [])
                      if item.get("text") and item["tag"].upper() in
                      {"FAMILY", "CONTACT", "DESC1", "DESC2", "DESC3", "XREF", "XREFNO", "XREFNC"}}
        components[device_id] = {
            "name": device.get("name"), "type": review.get("type", ""),
            "function": review.get("function", ""), "confirmed": review.get("confirmed", False),
            "page": device.get("source", {}).get("page"), "attributes": attributes,
            "semantics": deepcopy(device.get("semantics", {})),
            "source": deepcopy(device.get("source", {})),
            "name_status": device.get("name_status"),
            "name_source": deepcopy(device.get("name_source", {})),
            "port_ids": sorted(port_ids),
            "terminals": [{"port_id": pin["id"], "number": pin.get("number"),
                           "in_chain": pin["id"] in port_ids} for pin in device.get("pins", [])],
        }
    enriched["components"] = components
    enriched["component_summary"] = {
        "instances": len(components),
        "by_type": dict(sorted(Counter(item["type"] for item in components.values()).items())),
        "by_name": dict(sorted(Counter(item["name"] for item in components.values()
                                       if item["name"] is not None).items())),
    }
    return enriched

def extract_chain_with_components(netlist_path, start=None, *, device_name=None, number=None):
    """定位端子，沿wire做BFS，再附上元件和已保存的接地资料。"""
    # 1. 读取标准网表；后续查询只使用这里载入的数据。
    path = Path(netlist_path).resolve()
    payload = path.read_bytes()
    digest = sha256(payload).hexdigest()
    netlist = json.loads(payload)
    if not isinstance(netlist.get("devices"), dict) or not isinstance(netlist.get("connections"), list):
        raise ValueError("需要标准网表的devices对象和connections数组")

    # 2. 建端子表，并用ID或唯一的名称/编号定位起点。
    ports = {}
    for identity, device in netlist["devices"].items():
        review = device.get("review")
        if (not isinstance(review, dict) or not {"type", "function", "confirmed"} <= review.keys()
                or not all(isinstance(review[k], str) for k in ("type", "function"))
                or type(review["confirmed"]) is not bool):
            raise ValueError("标准网表缺少完整元件review(type/function/confirmed)：" + identity)
        if device.get("name") is not None and not isinstance(device["name"], str):
            raise ValueError("元件名称必须为文字或null：" + identity)
        for pin in device["pins"]:
            if not isinstance(pin.get("id"), str) or not pin["id"] or pin["id"] in ports:
                raise ValueError("端子ID缺失或重复")
            if pin.get("number") is not None and not isinstance(pin["number"], str):
                raise ValueError("端子编号必须为字符串或null，保留前导零")
            ports[pin["id"]] = dict(pin, device_id=identity, device_name=device["name"],
                name_status=device.get("name_status"), identity_status=device.get("identity_status"), source=device["source"])
    if start is None:
        if not all(isinstance(v, str) and v.strip() for v in (device_name, number)):
            raise ValueError("提供端子ID，或同时提供非空的device_name和number")
        matches = [p for p, row in ports.items() if row["device_name"] == device_name and row["number"] == number]
        if len(matches) != 1:
            raise ValueError("端子未找到" if not matches else "同名同号端子有多个候选，请用start指定ID：" + ", ".join(sorted(matches)))
        start = matches[0]
    elif device_name is not None or number is not None:
        raise ValueError("端子ID与名称/编号不能混用")
    if not isinstance(start, str) or start not in ports:
        raise ValueError("起点必须是标准网表中唯一存在的端子ID")

    # 3. 从connections建节点与连接的查找表；via/port_ids也属于连接成员。
    signals = netlist.get("signal_references", {})
    if ports.keys() & signals.keys():
        raise ValueError("端子与信号引用锚点 ID 重叠")
    edges, members, adjacent = {}, {}, defaultdict(set)
    for edge in netlist["connections"]:
        eid = edge["id"]
        if eid in edges:
            raise ValueError("连接 ID 重复")
        # 两个不同端点来自现有网表约束；中间节点由via/port_ids保存。
        if len(edge["ends"]) != 2 or len(set(edge["ends"])) != 2:
            raise ValueError("连接必须声明两个不同端点")
        edges[eid] = edge
        members[eid] = set(edge["ends"] + edge.get("via", []) + edge.get("port_ids", []))
        if edge["kind"] != "wire":
            continue
        review = edge.get("review")
        if (not isinstance(review, dict) or not {"a", "b", "note", "confirmed"} <= review.keys()
                or not all(isinstance(review[k], str) for k in ("a", "b", "note"))
                or type(review["confirmed"]) is not bool):
            raise ValueError("标准网表缺少完整导线review(a/b/note/confirmed)：" + eid)
        for node in members[eid]:
            adjacent[node].add(eid)

    # 4. BFS：每条连接只收录一次，分支、闭环和重汇合边都保留。
    seen, used, queue = {start}, set(), deque([start])
    while queue:
        node = queue.popleft()
        for eid in sorted(adjacent[node] - used):
            used.add(eid)
            for other in sorted(members[eid] - seen):
                seen.add(other)
                queue.append(other)
    chain = deepcopy({"kind": "reachable", "start": start, "allowed_kinds": ["wire"],
        "nodes": sorted(seen), "connections": [edges[eid] for eid in sorted(used)],
        "ports": {pid: ports[pid] for pid in sorted(seen & ports.keys())},
        "excluded": [edge for eid, edge in sorted(edges.items()) if edge["kind"] != "wire" and members[eid] & seen],
        "complete": True, "stop": {"reason": "exhausted" if used else "unconnected"},
        "scope": "当前网表和指定假设下的全部可达连接；连接顺序不表示路径或信号方向"})
    if seen & signals.keys():
        chain["signal_references"] = deepcopy({sid: signals[sid] for sid in sorted(seen & signals.keys())})
    chain["netlist_source"] = {"file": str(path), "sha256": digest}

    # 5. 附上链内元件资料，并筛选网表中已保存的接地来源。
    enriched = add_chain_component_info(chain, netlist)
    if "relations" in netlist:
        relations = netlist["relations"]
        required = {"connections": list, "reference_statuses": dict, "unresolved": list,
                    "signal_sources": list, "locations": dict, "ground_sources": list}
        if (not isinstance(relations, dict) or relations.get("schema") != "extracted_relations_v1"
                or any(not isinstance(relations.get(key), kind) for key, kind in required.items())):
            raise ValueError("网表缺少extract保存的完整关系资料，请重新extract；查询不会回读DXF补取")
        source_digest = netlist.get("source", {}).get("sha256")
        if not isinstance(source_digest, str) or not source_digest or relations.get("source_sha256") != source_digest:
            raise ValueError("已保存关系的source_sha256与网表来源不符")
        known_wires = {eid for eid, edge in edges.items() if edge["kind"] == "wire"}
        enriched["ground_sources"] = []
        for ground in relations["ground_sources"]:
            if (ground.get("source", {}).get("sha256") != source_digest
                    or not isinstance(ground.get("wire_ids"), list)
                    or any(not isinstance(w, str) or w not in known_wires for w in ground["wire_ids"])):
                raise ValueError("接地来源或原导线引用与网表不符")
            if used.intersection(ground["wire_ids"]):
                enriched["ground_sources"].append(deepcopy(ground))

    # 6. 核对输入文件未变，再返回结果供命令行保存。
    if sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("提取期间标准网表改变")
    return enriched
