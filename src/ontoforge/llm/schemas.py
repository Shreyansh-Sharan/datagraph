"""JSON schemas for structured model output. Names are local names; IRIs are minted by us."""
from __future__ import annotations

_S = {"type": "string"}
_NS = {"type": ["string", "null"]}
_ARR_S = {"type": "array", "items": _S}

ONTOLOGY_SCHEMA = {
    "type": "object",
    "properties": {
        "label": _S,
        "description": _NS,
        "classes": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": _S, "label": _S, "description": _NS, "parents": _ARR_S},
            "required": ["name", "label", "description", "parents"], "additionalProperties": False}},
        "datatype_properties": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": _S, "label": _S, "description": _NS, "domain": _NS,
                           "range": {"type": "string", "enum": ["string", "integer", "decimal", "double", "boolean",
                                                                "date", "dateTime", "time"]}},
            "required": ["name", "label", "description", "domain", "range"], "additionalProperties": False}},
        "object_properties": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": _S, "label": _S, "description": _NS, "domain": _S, "range": _S},
            "required": ["name", "label", "description", "domain", "range"], "additionalProperties": False}},
    },
    "required": ["label", "description", "classes", "datatype_properties", "object_properties"],
    "additionalProperties": False,
}

MAPPING_SCHEMA = {
    "type": "object",
    "properties": {
        "classes": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "class": _S, "table": _S, "key_columns": _ARR_S, "iri_template": _NS,
                "attributes": {"type": "array", "items": {
                    "type": "object", "properties": {"property": _S, "column": _S},
                    "required": ["property", "column"], "additionalProperties": False}}},
            "required": ["class", "table", "key_columns", "iri_template", "attributes"], "additionalProperties": False}},
        "relations": {"type": "array", "items": {
            "type": "object",
            "properties": {"property": _S, "source_class": _S, "target_class": _S, "table": _NS,
                           "source_key": {"type": ["array", "null"], "items": _S},
                           "target_key": {"type": ["array", "null"], "items": _S}},
            "required": ["property", "source_class", "target_class", "table", "source_key", "target_key"],
            "additionalProperties": False}},
    },
    "required": ["classes", "relations"],
    "additionalProperties": False,
}

INSIGHT_SCHEMA = {
    "type": "object",
    "properties": {
        "key_findings": _S,
        "notable_entities": {"type": "array", "items": {
            "type": "object", "properties": {"iri": _S, "reason": _S}, "required": ["iri", "reason"], "additionalProperties": False}},
        "recommendations": _ARR_S,
    },
    "required": ["key_findings", "notable_entities", "recommendations"],
    "additionalProperties": False,
}

RELATIONS_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["relations"],
    "properties": {"relations": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["property", "source_class", "column", "link_table", "link_source_column", "link_target_column"],
        "properties": {"property": _S, "source_class": _S, "column": _NS, "link_table": _NS, "link_source_column": _NS, "link_target_column": _NS}}}},
}
