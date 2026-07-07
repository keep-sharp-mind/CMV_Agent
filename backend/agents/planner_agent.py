"""
Planner Agent - Computes field-level lineage for each dependency edge.

For every edge A -> B, the planner first determines the fields B consumes
from A. Node in_fields and out_fields are then derived exclusively from those
edge fields.
"""

import ast
import json
import re
from typing import List, Dict, Any, Set, Tuple


EdgeKey = Tuple[str, str, str]


class PlannerAgent:
    """Analyze field consumption on every plan dependency edge."""

    DATA_TO_D_EDGES = {"d->D", "D->D"}
    DATA_TO_V_EDGES = {"d->V", "D->V"}

    def __init__(self, project_dir: str = None):
        self.project_dir = project_dir

    @staticmethod
    def build_node_contract(
        data_flow: Dict[str, Dict[str, Any]],
        node_id: str
    ) -> Dict[str, Any]:
        """Build the stable field contract used when regenerating one node."""
        flow = (data_flow or {}).get(node_id) or {}
        if not isinstance(flow, dict) or not flow:
            return {}
        return {
            "node_id": node_id,
            "required_inputs": flow.get("predecessor_fields") or {},
            "required_outputs": flow.get("out_fields") or [],
            "predicted_inputs": flow.get("predicted_in_fields") or [],
            "predicted_outputs": flow.get("predicted_out_fields") or [],
            "allowed_predecessors": [
                edge.get("from")
                for edge in (flow.get("incoming_edges") or [])
                if isinstance(edge, dict) and edge.get("from")
            ],
            "incoming_edges": flow.get("incoming_edges") or [],
            "outgoing_edges": flow.get("outgoing_edges") or []
        }

    @classmethod
    def validate_artifact_contract(
        cls,
        node_id: str,
        node_type: str,
        artifact: Dict[str, Any],
        contract: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Validate a generated D/V/I artifact against its last stable lineage."""
        if not isinstance(contract, dict) or not contract:
            return []

        required_outputs = cls._normalize_field_values(
            contract.get("required_outputs")
        )
        issues = []

        def add(detail: str, fields=None):
            issues.append({
                "type": "field_contract_violation",
                "columns": sorted(cls._normalize_field_values(fields)),
                "count": len(cls._normalize_field_values(fields)),
                "detail": detail
            })

        if node_type == "D":
            output_fields = {
                str(column.get("column_name"))
                for column in (artifact.get("columns") or [])
                if isinstance(column, dict) and column.get("column_name")
            }
            missing_outputs = required_outputs - output_fields
            if missing_outputs:
                add(
                    f"{node_id} would break downstream nodes by removing fields: "
                    f"{sorted(missing_outputs)}",
                    missing_outputs
                )

        elif node_type == "V":
            metadata = artifact.get("metadata") or {}
            used_fields = cls._normalize_field_values(metadata.get("used_fields"))
            missing_outputs = required_outputs - used_fields
            if missing_outputs:
                add(
                    f"{node_id} must keep fields used by interactions: "
                    f"{sorted(missing_outputs)}",
                    missing_outputs
                )

        elif node_type == "I":
            spec = artifact.get("interaction_spec") or artifact
            controlled_fields = {
                item.get("field")
                for item in (spec.get("controlled_view") or [])
                if isinstance(item, dict) and item.get("field")
            }
            missing_outputs = required_outputs - controlled_fields
            if missing_outputs:
                add(
                    f"{node_id} must preserve controlled-view fields: "
                    f"{sorted(missing_outputs)}",
                    missing_outputs
                )

        return issues

    def analyze_data_flow(
        self,
        plan_data: Dict[str, Any],
        database_schema: List[Dict[str, Any]],
        processed_vis: Dict[str, Any],
        processed_nodes: Dict[str, Any],
        interaction_results: Dict[str, Any] = None
    ) -> Dict[str, Dict[str, Any]]:
        """Compute edge fields, then aggregate them into per-node data flow."""
        processed_vis = processed_vis if isinstance(processed_vis, dict) else {}
        processed_nodes = (
            processed_nodes if isinstance(processed_nodes, dict) else {}
        )
        interaction_results = (
            interaction_results if isinstance(interaction_results, dict) else {}
        )
        print(
            f"[PlannerAgent] analyze_data_flow: "
            f"vis={len(processed_vis)} nodes={len(processed_nodes)}",
            flush=True
        )

        grouped_nodes = plan_data.get("nodes") or {}
        if not isinstance(grouped_nodes, dict):
            grouped_nodes = {}
        dependencies = plan_data.get("dependencies") or []
        node_types = ("d", "D", "V", "I")
        all_nodes = [
            node
            for node_type in node_types
            for node in (grouped_nodes.get(node_type) or [])
            if isinstance(node, dict) and node.get("id")
        ]
        node_map = {node["id"]: node for node in all_nodes}
        type_map = {
            node["id"]: node_type
            for node_type in node_types
            for node in (grouped_nodes.get(node_type) or [])
            if isinstance(node, dict) and node.get("id")
        }

        valid_edges = []
        incoming = {node_id: [] for node_id in node_map}
        outgoing = {node_id: [] for node_id in node_map}
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                continue
            source = dependency.get("from")
            target = dependency.get("to")
            if source not in node_map or target not in node_map:
                continue
            valid_edges.append(dependency)
            outgoing[source].append(dependency)
            incoming[target].append(dependency)

        table_columns = self._build_table_column_map(database_schema)
        available_fields: Dict[str, Set[str]] = {}
        for node_id, node in node_map.items():
            node_type = type_map[node_id]
            if node_type == "d":
                fields = self._get_source_fields(node, table_columns)
            elif node_type == "D":
                fields = self._get_d_output_fields(node_id, processed_nodes)
            elif node_type == "V":
                fields = self._get_v_required_fields(node_id, processed_vis)
            else:
                fields = set()
            available_fields[node_id] = self._normalize_field_values(fields)

        edge_fields: Dict[EdgeKey, Set[str]] = {}
        edge_evidence: Dict[EdgeKey, str] = {}
        undeclared_predecessors = {
            node_id: set() for node_id in node_map
        }

        # Analyze each D node once, then assign the result to its declared
        # incoming d->D / D->D edges.
        for node in grouped_nodes.get("D") or []:
            if not isinstance(node, dict) or node.get("id") not in node_map:
                continue
            node_id = node["id"]
            processed = processed_nodes.get(node_id) or {}
            if not isinstance(processed, dict):
                processed = {}
            code = processed.get("code") or ""
            declared_sources = [
                edge["from"]
                for edge in incoming[node_id]
                if edge.get("type") in self.DATA_TO_D_EDGES
            ]
            referenced_sources = [
                source
                for source in self._get_referenced_input_nodes(code)
                if source in node_map and type_map.get(source) in ("d", "D")
            ]
            undeclared_predecessors[node_id] = (
                set(referenced_sources) - set(declared_sources)
            )
            candidate_sources = list(dict.fromkeys(
                declared_sources + referenced_sources
            ))
            field_map, evidence_map = self._analyze_d_input_fields(
                node,
                code,
                candidate_sources,
                available_fields
            )
            for edge in incoming[node_id]:
                if edge.get("type") not in self.DATA_TO_D_EDGES:
                    continue
                source = edge["from"]
                key = self._edge_key(edge)
                edge_fields[key] = set(field_map.get(source, set()))
                edge_evidence[key] = evidence_map.get(source, "no_field_evidence")

        # A V spec describes exactly which fields its data edge consumes.
        for edge in valid_edges:
            if edge.get("type") not in self.DATA_TO_V_EDGES:
                continue
            source = edge["from"]
            target = edge["to"]
            key = self._edge_key(edge)
            declared = self._get_v_declared_input_fields(
                target, source, processed_vis
            )
            spec_fields = self._get_v_required_fields(target, processed_vis)
            source_available = available_fields.get(source, set())
            if declared and source_available:
                declared &= source_available
            matched_spec = spec_fields & source_available
            normalized_spec = matched_spec or spec_fields
            if declared or normalized_spec:
                fields = declared | normalized_spec
                evidence_parts = []
                if declared:
                    evidence_parts.append("vis_metadata.input_fields_by_table")
                if normalized_spec:
                    evidence_parts.append("vega_lite_spec")
                evidence = "+".join(evidence_parts)
            else:
                fields = set()
                evidence = "no_field_evidence"
            edge_fields[key] = self._normalize_field_values(fields)
            edge_evidence[key] = evidence

        # Interaction specs are already edge-oriented: link_field belongs to
        # V->I, controlled_view.field belongs to I->V.
        for node in grouped_nodes.get("I") or []:
            if not isinstance(node, dict) or node.get("id") not in node_map:
                continue
            interaction_id = node["id"]
            spec = self._get_interaction_spec(
                interaction_id, interaction_results
            )
            explicit_sources = self._interaction_source_fields(spec)
            explicit_targets = self._interaction_target_fields(spec)

            trigger_edges = [
                edge for edge in incoming[interaction_id]
                if edge.get("type") == "V->I"
            ]
            target_edges = [
                edge for edge in outgoing[interaction_id]
                if edge.get("type") == "I->V"
            ]
            target_view_fields = set().union(*[
                available_fields.get(edge["to"], set())
                for edge in target_edges
            ]) if target_edges else set()

            source_edge_union = set()
            for edge in trigger_edges:
                source = edge["from"]
                key = self._edge_key(edge)
                explicit = explicit_sources.get(source, set())
                source_fields = available_fields.get(source, set())
                shared = source_fields & target_view_fields
                if explicit:
                    fields = explicit
                    evidence = "interaction_spec.source_views.link_field"
                elif shared:
                    fields = shared
                    evidence = "predicted_interaction_shared_field"
                else:
                    fields = set()
                    evidence = "no_field_evidence"
                edge_fields[key] = self._normalize_field_values(fields)
                edge_evidence[key] = evidence
                source_edge_union.update(edge_fields[key])

            for edge in target_edges:
                target = edge["to"]
                key = self._edge_key(edge)
                explicit = explicit_targets.get(target, set())
                shared = source_edge_union & available_fields.get(target, set())
                if explicit:
                    fields = explicit
                    evidence = "interaction_spec.controlled_view.field"
                elif shared:
                    fields = shared
                    evidence = "predicted_interaction_shared_field"
                else:
                    fields = set()
                    evidence = "no_field_evidence"
                edge_fields[key] = self._normalize_field_values(fields)
                edge_evidence[key] = evidence

        # Keep every valid edge visible even when no field evidence is available.
        for edge in valid_edges:
            key = self._edge_key(edge)
            edge_fields.setdefault(key, set())
            edge_evidence.setdefault(key, "no_field_evidence")

        ancestor_cache: Dict[str, Dict[str, Set[str]]] = {}

        def collect_ancestor_fields(
            node_id: str,
            visiting: Set[str] = None
        ) -> Dict[str, Set[str]]:
            """Collect transitive lineage without changing direct in_fields."""
            if node_id in ancestor_cache:
                return {
                    key: set(value)
                    for key, value in ancestor_cache[node_id].items()
                }
            visiting = set(visiting or set())
            if node_id in visiting:
                return {}
            visiting.add(node_id)
            collected: Dict[str, Set[str]] = {}
            for edge in incoming.get(node_id, []):
                source = edge["from"]
                fields = edge_fields.get(self._edge_key(edge), set())
                collected.setdefault(source, set()).update(fields)
                nested = collect_ancestor_fields(source, visiting)
                for ancestor, nested_fields in nested.items():
                    collected.setdefault(ancestor, set()).update(nested_fields)
            ancestor_cache[node_id] = {
                key: set(value) for key, value in collected.items()
            }
            return collected

        result: Dict[str, Dict[str, Any]] = {}
        for node_id in node_map:
            incoming_edges = [
                self._edge_record(edge, edge_fields, edge_evidence)
                for edge in incoming[node_id]
            ]
            outgoing_edges = [
                self._edge_record(edge, edge_fields, edge_evidence)
                for edge in outgoing[node_id]
            ]

            in_field_map: Dict[str, Set[str]] = {}
            predicted_in_field_map: Dict[str, Set[str]] = {}
            for edge in incoming[node_id]:
                key = self._edge_key(edge)
                target_map = (
                    predicted_in_field_map
                    if str(edge_evidence.get(key, "")).startswith("predicted_")
                    else in_field_map
                )
                target_map.setdefault(edge["from"], set()).update(
                    edge_fields.get(key, set())
                )
            out_fields = set()
            predicted_out_fields = set()
            for edge in outgoing[node_id]:
                key = self._edge_key(edge)
                if str(edge_evidence.get(key, "")).startswith("predicted_"):
                    predicted_out_fields.update(edge_fields.get(key, set()))
                else:
                    out_fields.update(edge_fields.get(key, set()))

            ancestor_map = collect_ancestor_fields(node_id)
            result[node_id] = {
                # Direct edge contract: B.in_fields receives exactly A->B fields.
                "in_fields": self._qualify_field_map(in_field_map),
                "direct_in_fields": self._qualify_field_map(in_field_map),
                # Direct edge contract: A.out_fields emits exactly A->B fields.
                "out_fields": sorted(out_fields),
                "predicted_in_fields": self._qualify_field_map(predicted_in_field_map),
                "predicted_out_fields": sorted(predicted_out_fields),
                "predecessors": sorted(in_field_map),
                "undeclared_predecessors": sorted(
                    undeclared_predecessors.get(node_id, set())
                ),
                "predecessor_fields": {
                    source: sorted(fields)
                    for source, fields in sorted(in_field_map.items())
                },
                # Transitive lineage is separate and never pollutes in_fields.
                "ancestors": sorted(ancestor_map),
                "ancestor_fields": {
                    ancestor: sorted(fields)
                    for ancestor, fields in sorted(ancestor_map.items())
                },
                "transitive_in_fields": self._qualify_field_map(ancestor_map),
                "incoming_edges": incoming_edges,
                "outgoing_edges": outgoing_edges
            }

        return result

    @staticmethod
    def _edge_key(edge: Dict[str, Any]) -> EdgeKey:
        return (
            str(edge.get("from", "")),
            str(edge.get("to", "")),
            str(edge.get("type", ""))
        )

    @classmethod
    def _edge_record(
        cls,
        edge: Dict[str, Any],
        edge_fields: Dict[EdgeKey, Set[str]],
        edge_evidence: Dict[EdgeKey, str]
    ) -> Dict[str, Any]:
        key = cls._edge_key(edge)
        return {
            "from": key[0],
            "to": key[1],
            "type": key[2],
            "fields": sorted(edge_fields.get(key, set())),
            "evidence": edge_evidence.get(key, "no_field_evidence")
        }

    def _analyze_d_input_fields(
        self,
        node: Dict[str, Any],
        code: str,
        sources: List[str],
        available_fields: Dict[str, Set[str]]
    ) -> Tuple[Dict[str, Set[str]], Dict[str, str]]:
        """Analyze which fields generated pandas code consumes per input node."""
        candidates = {
            source: self._normalize_field_values(
                available_fields.get(source, set())
            )
            for source in sources
        }
        explicit = self._parse_input_fields_comment(code)
        ast_fields = self._extract_ast_input_fields(code, candidates)
        literals = self._extract_python_string_literals(code)
        referenced = set(self._get_referenced_input_nodes(code))
        task_text = " ".join([
            str(node.get("name", "")),
            str(node.get("description", "")),
            str(node.get("task", ""))
        ]).lower()

        result: Dict[str, Set[str]] = {}
        evidence: Dict[str, str] = {}
        for source in sources:
            available = candidates.get(source, set())
            explicit_fields = self._normalize_field_values(explicit.get(source))
            precise_fields = self._normalize_field_values(ast_fields.get(source))
            literal_fields = {field for field in available if field in literals}
            task_fields = {
                field for field in available
                if self._text_mentions_field(task_text, field)
            }

            if available:
                explicit_fields &= available
            if explicit_fields or precise_fields:
                result[source] = explicit_fields | precise_fields
                evidence_parts = []
                if explicit_fields:
                    evidence_parts.append("code_comment.INPUT_FIELDS")
                if precise_fields:
                    evidence_parts.append("python_ast")
                evidence[source] = "+".join(evidence_parts)
            elif source in referenced and literal_fields:
                result[source] = literal_fields
                evidence[source] = "python_literal_fallback"
            elif task_fields:
                result[source] = task_fields
                evidence[source] = "node_task_fallback"
            elif source in referenced:
                # The whole input is read but field-level usage is opaque.
                result[source] = set(available)
                evidence[source] = "whole_input_fallback"
            else:
                result[source] = set()
                evidence[source] = "declared_edge_not_used_by_code"
        return result, evidence

    @staticmethod
    def _parse_input_fields_comment(code: str) -> Dict[str, Any]:
        """Parse '# INPUT_FIELDS: {...}' without affecting code execution."""
        match = re.search(
            r"^\s*#\s*INPUT_FIELDS\s*:\s*(\{.*\})\s*$",
            code or "",
            re.MULTILINE
        )
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(1))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _extract_ast_input_fields(
        self,
        code: str,
        candidates: Dict[str, Set[str]]
    ) -> Dict[str, Set[str]]:
        """Perform lightweight dataframe provenance and column-use analysis."""
        if not code:
            return {}
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return {}

        provenance: Dict[str, Set[str]] = {}

        def infer_sources(expression: Any) -> Set[str]:
            if expression is None:
                return set()
            if isinstance(expression, ast.Name):
                prefix = "INPUT_TABLE_PATH_"
                if expression.id.startswith(prefix):
                    source = expression.id[len(prefix):]
                    return {source} if source in candidates else set()
                return set(provenance.get(expression.id, set()))
            if isinstance(expression, ast.Attribute):
                return infer_sources(expression.value)
            sources = set()
            for child in ast.iter_child_nodes(expression):
                sources.update(infer_sources(child))
            return sources

        def assigned_names(target: Any) -> Set[str]:
            if isinstance(target, ast.Name):
                return {target.id}
            names = set()
            for child in ast.iter_child_nodes(target):
                names.update(assigned_names(child))
            return names

        # Iterate because a dataframe may be assigned from another variable that
        # appears in a nested expression.
        assignments = [
            child for child in ast.walk(tree)
            if isinstance(child, (ast.Assign, ast.AnnAssign))
        ]
        for _ in range(4):
            changed = False
            for assignment in assignments:
                value = assignment.value
                sources = infer_sources(value)
                targets = (
                    assignment.targets
                    if isinstance(assignment, ast.Assign)
                    else [assignment.target]
                )
                for target in targets:
                    for name in assigned_names(target):
                        if sources and provenance.get(name) != sources:
                            provenance[name] = set(sources)
                            changed = True
            if not changed:
                break

        used = {source: set() for source in candidates}

        def add_fields(sources: Set[str], values: Set[str]):
            for source in sources:
                available = candidates.get(source, set())
                used.setdefault(source, set()).update(values & available)

        for child in ast.walk(tree):
            if isinstance(child, ast.Subscript):
                sources = infer_sources(child.value)
                values = self._extract_ast_strings(child.slice)
                add_fields(sources, values)
            elif isinstance(child, ast.Call):
                if isinstance(child.func, ast.Attribute):
                    sources = infer_sources(child.func.value)
                else:
                    sources = set()
                # pd.merge(left, right, ...) and df.merge(other, ...) consume
                # fields from dataframe arguments as well as the method owner.
                for argument in child.args:
                    sources.update(infer_sources(argument))
                values = set()
                for argument in child.args:
                    values.update(self._extract_ast_strings(argument))
                for keyword in child.keywords:
                    values.update(self._extract_ast_strings(keyword.value))
                add_fields(sources, values)

        return used

    @staticmethod
    def _extract_ast_strings(node: Any) -> Set[str]:
        values = set()
        if node is None:
            return values
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                values.add(child.value)
        return values

    @staticmethod
    def _extract_python_string_literals(code: str) -> Set[str]:
        if not code:
            return set()
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return set(re.findall(r"['\"]([^'\"]+)['\"]", code))
        return {
            child.value
            for child in ast.walk(tree)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
        }

    @staticmethod
    def _get_referenced_input_nodes(code: str) -> List[str]:
        return list(dict.fromkeys(re.findall(
            r"\bINPUT_TABLE_PATH_([A-Za-z0-9_]+)\b",
            code or ""
        )))

    @staticmethod
    def _text_mentions_field(text: str, field: str) -> bool:
        if not text or not field:
            return False
        return re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(field.lower())}(?![A-Za-z0-9_])",
            text
        ) is not None

    @classmethod
    def _get_v_required_fields(
        cls,
        v_id: str,
        processed_vis: Dict[str, Any]
    ) -> Set[str]:
        visualization = cls._normalize_visualization(
            processed_vis.get(v_id)
        )
        metadata = visualization.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        fields = cls._normalize_field_values(metadata.get("used_fields"))
        fields.update(cls._extract_metadata_encoding_fields(
            metadata.get("encoding_fields")
        ))
        spec = visualization.get("spec") or {}

        def visit(value: Any, key: str = ""):
            if isinstance(value, dict):
                for child_key, child_value in value.items():
                    if child_key in ("field", "fieldName", "fields", "groupby"):
                        fields.update(cls._normalize_field_values(child_value))
                    elif child_key in ("calculate", "filter", "test"):
                        fields.update(cls._extract_datum_fields(child_value))
                    visit(child_value, child_key)
            elif isinstance(value, list):
                for item in value:
                    visit(item, key)
            elif key in ("calculate", "filter", "test"):
                fields.update(cls._extract_datum_fields(value))

        visit(spec)
        return {field for field in fields if field}

    @classmethod
    def _get_v_declared_input_fields(
        cls,
        v_id: str,
        source_id: str,
        processed_vis: Dict[str, Any]
    ) -> Set[str]:
        visualization = cls._normalize_visualization(
            processed_vis.get(v_id)
        )
        metadata = visualization.get("metadata") or {}
        if not isinstance(metadata, dict):
            return set()
        mapping = metadata.get("input_fields_by_table") or {}
        if not isinstance(mapping, dict):
            return set()
        return cls._normalize_field_values(mapping.get(source_id))

    @staticmethod
    def _normalize_visualization(value: Any) -> Dict[str, Any]:
        if isinstance(value, list):
            return {"spec": {"layer": value}}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _get_interaction_spec(
        interaction_id: str,
        interaction_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        result = interaction_results.get(interaction_id) or {}
        if not isinstance(result, dict):
            return {}
        spec = result.get("interaction_spec") or {}
        return spec if isinstance(spec, dict) else {}

    @classmethod
    def _interaction_source_fields(
        cls,
        spec: Dict[str, Any]
    ) -> Dict[str, Set[str]]:
        result: Dict[str, Set[str]] = {}
        for item in spec.get("source_views") or []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            result.setdefault(item["id"], set()).update(
                cls._normalize_field_values(item.get("link_field"))
            )
        return result

    @classmethod
    def _interaction_target_fields(
        cls,
        spec: Dict[str, Any]
    ) -> Dict[str, Set[str]]:
        result: Dict[str, Set[str]] = {}
        for item in spec.get("controlled_view") or []:
            if not isinstance(item, dict) or not item.get("view"):
                continue
            result.setdefault(item["view"], set()).update(
                cls._normalize_field_values(item.get("field"))
            )
        return result

    @staticmethod
    def _qualify_field_map(field_map: Dict[str, Set[str]]) -> List[str]:
        return sorted({
            f"{node_id}.{field}"
            for node_id, fields in field_map.items()
            for field in fields
            if field
        })

    @staticmethod
    def _normalize_field_values(value: Any) -> Set[str]:
        fields = set()
        if isinstance(value, str):
            if value:
                fields.add(value)
        elif isinstance(value, dict):
            for nested in value.values():
                fields.update(PlannerAgent._normalize_field_values(nested))
        elif isinstance(value, (list, tuple, set)):
            for nested in value:
                fields.update(PlannerAgent._normalize_field_values(nested))
        return fields

    @staticmethod
    def _extract_metadata_encoding_fields(value: Any) -> Set[str]:
        fields = set()
        if not isinstance(value, dict):
            return PlannerAgent._normalize_field_values(value)
        for encoding in value.values():
            if isinstance(encoding, str):
                fields.add(encoding)
            elif isinstance(encoding, dict):
                field = encoding.get("field") or encoding.get("fieldName")
                fields.update(PlannerAgent._normalize_field_values(field))
        return fields

    @staticmethod
    def _extract_datum_fields(expression: Any) -> Set[str]:
        if not isinstance(expression, str):
            return set()
        return set(
            re.findall(r"\bdatum\.([A-Za-z_][A-Za-z0-9_]*)", expression)
            + re.findall(r"\bdatum\[['\"]([^'\"]+)['\"]\]", expression)
        )

    @staticmethod
    def _get_d_output_fields(
        node_id: str,
        processed_nodes: Dict[str, Any]
    ) -> Set[str]:
        processed = processed_nodes.get(node_id) or {}
        if not isinstance(processed, dict):
            return set()
        fields = set()
        for column in processed.get("columns") or []:
            value = (
                column.get("column_name") or column.get("name")
                if isinstance(column, dict)
                else column
            )
            fields.update(PlannerAgent._normalize_field_values(value))
        for metadata in (
            processed.get("metadata") or {},
            (processed.get("error_recovery") or {}).get("metadata") or {}
        ):
            if isinstance(metadata, dict):
                fields.update(PlannerAgent._normalize_field_values(
                    metadata.get("output_columns")
                ))
        return fields

    @staticmethod
    def _get_source_fields(
        node: Dict[str, Any],
        table_columns: Dict[str, List[str]]
    ) -> List[str]:
        for candidate in (
            node.get("source_table", ""),
            node.get("name", "")
        ):
            if candidate in table_columns:
                return table_columns[candidate]
            short_name = str(candidate).rsplit(".", 1)[-1]
            if short_name in table_columns:
                return table_columns[short_name]
        return []

    @staticmethod
    def _build_table_column_map(
        database_schema: List[Dict[str, Any]]
    ) -> Dict[str, List[str]]:
        column_map = {}
        for database in database_schema or []:
            if not isinstance(database, dict):
                continue
            database_name = database.get("db_name", "")
            for table in database.get("tables") or []:
                if not isinstance(table, dict):
                    continue
                table_name = table.get("table_name", "")
                columns = []
                for column in table.get("columns") or []:
                    value = (
                        column.get("column_name")
                        if isinstance(column, dict)
                        else column
                    )
                    columns.extend(sorted(
                        PlannerAgent._normalize_field_values(value)
                    ))
                column_map[table_name] = columns
                if database_name:
                    column_map[f"{database_name}.{table_name}"] = columns
        return column_map


def get_planner_agent(project_dir: str = None) -> PlannerAgent:
    return PlannerAgent(project_dir=project_dir)
