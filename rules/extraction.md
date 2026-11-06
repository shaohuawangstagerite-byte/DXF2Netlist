# Extraction rules

Runtime configuration for SPEC R7–R15 and R46–R51. The 64 ULP allowance normalizes floating-point arithmetic; it does not bridge drawing gaps.

```json
{"anchor_tag_regex": "X(\\d)TERM(\\d+)", "float_ulps": 64, "label_tag_regex": "TERM(\\d+)", "marker_mode": "attribute_free_concentric_circle_only_block", "wire_mode": "attribute_seeded_endpoint_graph", "wire_text_mode": "unique_nearest_TEXT_within_own_height", "component_name_mode": "LINK_axis_visible_header_candidates", "signal_information_mode": "documented_signal_fields_on_unique_net", "connector_mating_mode": "opposed_shape_mutually_unique_candidates"}
```
