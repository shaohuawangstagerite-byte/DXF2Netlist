"""Validate saved relation data and source consistency."""

from copy import deepcopy

def load_saved_relations(netlist):
    """Return complete saved facts; old or partial exports require re-extraction."""
    relations = netlist.get("relations")
    required = {"connections": list, "reference_statuses": dict, "unresolved": list,
                "signal_sources": list, "locations": dict, "ground_sources": list}
    if (not isinstance(relations, dict) or relations.get("schema") != "extracted_relations_v1"
            or any(not isinstance(relations.get(key), kind) for key, kind in required.items())):
        raise ValueError("网表缺少extract保存的完整关系资料，请重新extract；查询不会回读DXF补取")
    digest = netlist.get("source", {}).get("sha256")
    if not isinstance(digest, str) or not digest or relations.get("source_sha256") != digest:
        raise ValueError("已保存关系的source_sha256与网表来源不符")
    return deepcopy(relations)
