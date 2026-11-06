"""Pair mutually unique connector shape candidates."""

from collections import Counter

from copy import deepcopy

from ezdxf.math import Vec3

MATING_MODE = "opposed_shape_mutually_unique_candidates"

def pair_connectors(profiles, tolerance):
    """纯函数：输入图形特征，返回候选和未解决原因；不读取文件。"""
    if len({p["port"] for p in profiles}) != len(profiles):
        raise ValueError("连接器特征含重复端子身份")
    candidates = []
    for socket in profiles:
        if socket["role"] != "socket":
            continue
        axis, radius = Vec3(socket["axis"]), socket["half_width"]
        for pin in profiles:
            if pin["role"] != "pin" or socket["layout"] != pin["layout"]:
                continue
            mouth, other = Vec3(socket["mouth"]), Vec3(pin["mouth"])
            # 只支持同一 XY 平面；角误差乘实际半径后与 R7 长度容差比较。
            if abs(mouth.z - other.z) > tolerance or (axis + Vec3(pin["axis"])).magnitude * radius > tolerance:
                continue
            delta = other - mouth
            gap = delta.dot(axis)
            offset = (delta - axis * gap).magnitude
            # 2 来自圆的直径定义；范围取符号自身尺寸，不是为本图拟合的距离。
            if -tolerance <= gap <= 2 * radius + tolerance and offset + pin["half_width"] <= radius + tolerance:
                candidates.append({"ports": [socket["port"], pin["port"]],
                                   "profiles": [deepcopy(socket), deepcopy(pin)],
                                   "gap": gap, "transverse_offset": offset})
    degree = Counter(port for pair in candidates for port in pair["ports"])
    pairs = [pair for pair in candidates if all(degree[p] == 1 for p in pair["ports"])]
    paired = {p for pair in pairs for p in pair["ports"]}
    unresolved = []
    for profile in profiles:
        port = profile["port"]
        if port not in paired:
            peers = [p for pair in candidates if port in pair["ports"] for p in pair["ports"] if p != port]
            unresolved.append({"port": port, "insert": profile["insert"], "candidates": peers,
                               "reason": "no_geometric_peer" if not peers else "ambiguous_pairing"})
    return {"pairs": pairs, "unresolved": unresolved}
