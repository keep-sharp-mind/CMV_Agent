"""
Error Agent - Agent for handling errors during data processing, visualization, and plan generation.
Responsible for receiving, recording, and attempting to fix errors found during
data processing / visualization generation / plan validation.
"""

import os
import json
import copy
import re
import traceback
from datetime import datetime
from typing import List, Dict, Any, Optional
from model import get_model_client, ModelClient
from prompts.error_agent_prompts import (
    ANALYZE_PLAN_ERRORS_PROMPT,
    FIX_DEPENDENCIES_PROMPT,
    FIX_REQUIREMENTS_PROMPT,
    VIS_ERROR_ANALYSIS_PROMPT,
    INTERACTION_ERROR_ANALYSIS_PROMPT,
    FIX_VIS_SPEC_PROMPT,
    FIX_INTERACTION_PROMPT,
    DATA_ERROR_ANALYSIS_PROMPT,
    FIX_DATA_CODE_PROMPT
)


def _clean_json_text(text: str) -> str:
    """Replace NaN/Infinity with null for compliant JSON parsing."""
    return re.sub(r'\bNaN\b|\bInfinity\b|\b-Infinity\b', 'null', text)


class ErrorAgent:
    """Error Agent - Handles errors from data processing / visualization / plan nodes"""

    def __init__(
        self,
        model_client: Optional[ModelClient] = None,
        project_dir: str = None
    ):
        self.model_client = model_client or get_model_client()
        self.project_dir = project_dir

    def _format_nodes_for_prompt(self, nodes: Dict[str, Any]) -> str:
        """Format node definitions for prompt inclusion."""
        node_lines = []
        for ntype, nlist in nodes.items():
            for n in nlist:
                nid = n["id"]
                nname = n.get("name", nid)
                ndesc = n.get("description", "")
                if ntype == "D":
                    node_lines.append(f"  {nid} ({ntype}): {nname} - {ndesc} | task: {n.get('task', '')}")
                elif ntype == "V":
                    node_lines.append(f"  {nid} ({ntype}): {nname} - {ndesc} | chart_type: {n.get('chart_type', '')}")
                elif ntype == "I":
                    node_lines.append(f"  {nid} ({ntype}): {nname} - {ndesc} | trigger: {n.get('trigger', '')} effect: {n.get('effect', '')}")
                else:
                    node_lines.append(f"  {nid} ({ntype}): {nname} - {ndesc}")
        return "\n".join(node_lines)

    def _extract_json_object(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract a JSON object from text"""
        cleaned = _clean_json_text(text).strip()
        if cleaned.startswith("{") and cleaned.endswith("}"):
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass
        pattern = r"```(?:json)?\s*(\{[\s\S]*?\})\s*```"
        matches = re.findall(pattern, cleaned)
        for match in matches:
            try:
                return json.loads(match.strip())
            except json.JSONDecodeError:
                continue
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                pass
        return None

    def _extract_json_array(self, text: str) -> Optional[List[Dict[str, Any]]]:
        """Extract a JSON array from text"""
        cleaned = _clean_json_text(text).strip()
        if cleaned.startswith("[") and cleaned.endswith("]"):
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass
        pattern = r"```(?:json)?\s*(\[[\s\S]*?\])\s*```"
        matches = re.findall(pattern, cleaned)
        for match in matches:
            try:
                return json.loads(match.strip())
            except json.JSONDecodeError:
                continue
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                pass
        return None

    def analyze_plan_errors(
        self,
        requirements_text: str,
        validation_errors: List[Dict[str, Any]],
        dependencies: List[Dict[str, Any]],
        nodes: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Analyze validation errors and determine root cause.

        Returns:
            Dict with root_cause, suggestions, affected_nodes, needs_requirement_change
        """
        node_details = self._format_nodes_for_prompt(nodes)
        error_details = "\n".join([f"  - {e['message']}" for e in validation_errors])
        deps_json = json.dumps(dependencies, ensure_ascii=False, indent=2)
        requires_requirement_change = any(
            error.get("rule") == "data_feasibility"
            for error in validation_errors
        )

        # Describe the validation rules for the prompt
        validation_rules_text = (
            "1. Every non-d node must have at least one valid incoming predecessor\n"
            "2. Every D needs a d->D or D->D predecessor and a D/V consumer\n"
            "3. Every V needs exactly one d->V or D->V data predecessor\n"
            "4. Every I needs an incoming V->I and outgoing I->V to a different V\n"
            "5. Every edge endpoint must exist and its type must match endpoint node types\n"
            "6. Duplicate edges, self-loops, incoming edges to d, and cycles are forbidden\n"
            "7. D/V nodes must use only metrics present in upstream schemas; unavailable metrics cannot be replaced with invented proxies"
        )

        prompt = ANALYZE_PLAN_ERRORS_PROMPT.format(
            requirements_text=requirements_text,
            node_details=node_details,
            current_dependencies_json=deps_json,
            error_details=error_details,
            validation_rules_text=validation_rules_text
        )

        messages = [
            {"role": "system", "content": "You are an expert data analysis planner and debugger."},
            {"role": "user", "content": prompt}
        ]

        try:
            response = self.model_client.chat(messages, temperature=0.3)
            content = response["content"]

            result = self._extract_json_object(content)
            if not result:
                if requires_requirement_change:
                    return {
                        "success": True,
                        "root_cause": "requirements",
                        "suggestions": (
                            "Remove or redesign infeasible requirements and their "
                            "D/V nodes using only fields present in the input schemas."
                        ),
                        "affected_nodes": [
                            node_id
                            for error in validation_errors
                            if error.get("rule") == "data_feasibility"
                            for node_id in error.get("nodes", [])
                        ],
                        "needs_requirement_change": True,
                        "explanation": "Deterministic data-feasibility validation failed."
                    }
                return {
                    "success": False,
                    "root_cause": "dependency_graph",
                    "suggestions": "Failed to parse analysis from LLM",
                    "affected_nodes": [],
                    "needs_requirement_change": False,
                    "explanation": ""
                }

            return {
                "success": True,
                "root_cause": (
                    "requirements" if requires_requirement_change
                    else result.get("root_cause", "dependency_graph")
                ),
                "suggestions": result.get("suggestions", ""),
                "affected_nodes": result.get("affected_nodes", []),
                "needs_requirement_change": (
                    requires_requirement_change
                    or result.get("needs_requirement_change", False)
                ),
                "explanation": result.get("explanation", "")
            }

        except Exception as e:
            tb = traceback.format_exc()
            return {
                "success": False,
                "root_cause": "dependency_graph",
                "suggestions": f"Exception: {e}",
                "affected_nodes": [],
                "needs_requirement_change": False,
                "explanation": tb
            }

    def fix_dependencies(
        self,
        requirements_text: str,
        nodes: Dict[str, Any],
        current_dependencies: List[Dict[str, Any]],
        validation_errors: List[Dict[str, Any]],
        diagnosis_text: str
    ) -> Dict[str, Any]:
        """
        Ask LLM to regenerate only the dependencies array based on diagnosis.

        Returns:
            Dict with success, dependencies, error
        """
        node_details = self._format_nodes_for_prompt(nodes)
        error_details = "\n".join([f"  - {e['message']}" for e in validation_errors])
        deps_json = json.dumps(current_dependencies, ensure_ascii=False, indent=2)

        prompt = FIX_DEPENDENCIES_PROMPT.format(
            requirements_text=requirements_text,
            node_details=node_details,
            error_details=error_details,
            diagnosis_text=diagnosis_text
        )

        messages = [
            {"role": "system", "content": "You are an expert data analysis planner."},
            {"role": "user", "content": prompt}
        ]

        try:
            response = self.model_client.chat(messages, temperature=0.3)
            content = response["content"]

            fixed_deps = self._extract_json_array(content)

            if fixed_deps is None or not isinstance(fixed_deps, list):
                return {
                    "success": False,
                    "dependencies": current_dependencies,
                    "error": "Failed to parse LLM output as JSON array"
                }

            for dep in fixed_deps:
                if not all(k in dep for k in ("from", "to", "type")):
                    return {
                        "success": False,
                        "dependencies": current_dependencies,
                        "error": "LLM returned invalid dependency format (missing from/to/type)"
                    }

            return {
                "success": True,
                "dependencies": fixed_deps,
                "error": None
            }

        except Exception as e:
            tb = traceback.format_exc()
            return {
                "success": False,
                "dependencies": current_dependencies,
                "error": f"{e}\n{tb}"
            }

    def fix_requirements(
        self,
        goal: str,
        current_requirements: List[Dict[str, Any]],
        nodes: Dict[str, Any],
        validation_errors: List[Dict[str, Any]],
        diagnosis_text: str
    ) -> Dict[str, Any]:
        """
        Ask LLM to fix the refined requirements based on diagnosis.

        Returns:
            Dict with success, requirements, error
        """
        node_details = self._format_nodes_for_prompt(nodes)
        error_details = "\n".join([f"  - {e['message']}" for e in validation_errors])
        req_json = json.dumps(current_requirements, ensure_ascii=False, indent=2)

        prompt = FIX_REQUIREMENTS_PROMPT.format(
            goal=goal,
            current_requirements_json=req_json,
            node_details=node_details,
            error_details=error_details,
            diagnosis_text=diagnosis_text
        )

        messages = [
            {"role": "system", "content": "You are an expert data analysis planner."},
            {"role": "user", "content": prompt}
        ]

        try:
            response = self.model_client.chat(messages, temperature=0.3)
            content = response["content"]

            fixed_reqs = self._extract_json_array(content)

            if fixed_reqs is None or not isinstance(fixed_reqs, list):
                return {
                    "success": False,
                    "requirements": current_requirements,
                    "error": "Failed to parse LLM output as JSON array"
                }

            for r in fixed_reqs:
                if not all(k in r for k in ("id", "name", "description")):
                    return {
                        "success": False,
                        "requirements": current_requirements,
                        "error": "LLM returned invalid requirement format (missing id/name/description)"
                    }

            return {
                "success": True,
                "requirements": fixed_reqs,
                "error": None
            }

        except Exception as e:
            tb = traceback.format_exc()
            return {
                "success": False,
                "requirements": current_requirements,
                "error": f"{e}\n{tb}"
            }

    def analyze_vis_error(
        self,
        node: Dict[str, Any],
        spec: Dict[str, Any],
        input_nodes: List[Dict[str, Any]],
        input_table_paths: Dict[str, str],
        execution_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Analyze a visualization error and suggest fixes (may target plan/data/vis).

        Returns:
            Dict with root_cause, fix_strategy, suggested_fixes, explanation
        """
        node_details = f"  {node['id']} ({node.get('chart_type', 'N/A')}): {node.get('name', '')} - {node.get('description', '')}"
        chart_type = node.get("chart_type", "N/A")
        spec_json = json.dumps(spec, ensure_ascii=False, indent=2) if spec else "{}"

        input_info_lines = []
        for inp in input_nodes:
            inp_id = inp["id"]
            path = input_table_paths.get(inp_id, "")
            if path and os.path.exists(path):
                import csv
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        reader = csv.reader(f)
                        headers = next(reader, [])
                    input_info_lines.append(f"  {inp_id}: columns={headers}")
                except Exception:
                    input_info_lines.append(f"  {inp_id}: path={path}")
            else:
                input_info_lines.append(f"  {inp_id}: path={path}")
        input_tables_info = "\n".join(input_info_lines) if input_info_lines else "  No input tables"

        error_lines = []
        err = execution_result.get("error", "")
        if err:
            error_lines.append(f"  error: {err}")
        sc = execution_result.get("syntax_check", {})
        if sc and not sc.get("valid"):
            error_lines.append(f"  syntax: {sc.get('error', '')}")
        for iss in execution_result.get("validation_issues", []):
            error_lines.append(f"  validation: {iss.get('detail', '')}")
        error_details = "\n".join(error_lines) if error_lines else "  No error details"

        prompt = VIS_ERROR_ANALYSIS_PROMPT.format(
            node_details=node_details,
            chart_type=chart_type,
            input_tables_info=input_tables_info,
            spec_json=spec_json,
            error_details=error_details
        )

        messages = [
            {"role": "system", "content": "You are a Vega-Lite visualization expert and debugger."},
            {"role": "user", "content": prompt}
        ]
        _raw = ""

        try:
            response = self.model_client.chat(messages, temperature=0.3)
            _raw = response["content"]
            result = self._extract_json_object(_raw)
            if not result:
                return {
                    "success": False, "root_cause": "vis_spec",
                    "fix_strategy": "modify_vis", "suggested_fixes": {},
                    "explanation": "Failed to parse LLM output",
                    "_prompt_messages": messages, "_raw_response": _raw
                }
            return {
                "success": True,
                "root_cause": result.get("root_cause", "vis_spec"),
                "fix_strategy": result.get("fix_strategy", "modify_vis"),
                "suggested_fixes": result.get("suggested_fixes", {}),
                "explanation": result.get("explanation", ""),
                "_prompt_messages": messages, "_raw_response": _raw
            }
        except Exception as e:
            return {
                "success": False, "root_cause": "vis_spec",
                "fix_strategy": "modify_vis", "suggested_fixes": {},
                "explanation": f"Exception: {e}",
                "_prompt_messages": messages, "_raw_response": _raw
            }

    def fix_vis_spec(
        self,
        node: Dict[str, Any],
        spec: Dict[str, Any],
        input_nodes: List[Dict[str, Any]],
        input_table_paths: Dict[str, str],
        execution_result: Dict[str, Any],
        diagnosis_text: str
    ) -> Dict[str, Any]:
        """
        Ask LLM to regenerate a corrected Vega-Lite spec based on the diagnosis.

        Returns:
            Dict with success, spec, metadata, error
        """
        node_details = f"  {node['id']} ({node.get('chart_type', 'N/A')}): {node.get('name', '')} - {node.get('description', '')}"
        chart_type = node.get("chart_type", "N/A")
        spec_json = json.dumps(spec, ensure_ascii=False, indent=2) if spec else "{}"

        input_info_lines = []
        all_fields = set()
        for inp in input_nodes:
            inp_id = inp["id"]
            path = input_table_paths.get(inp_id, "")
            if path and os.path.exists(path):
                import csv
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        reader = csv.reader(f)
                        headers = next(reader, [])
                    input_info_lines.append(f"  {inp_id}: columns={headers}")
                    all_fields.update(headers)
                except Exception:
                    input_info_lines.append(f"  {inp_id}: path={path}")
            else:
                input_info_lines.append(f"  {inp_id}: path={path}")
        input_tables_info = "\n".join(input_info_lines) if input_info_lines else "  No input tables"
        available_fields = ", ".join(sorted(all_fields)) if all_fields else "unknown"

        error_lines = []
        err = execution_result.get("error", "")
        if err:
            error_lines.append(f"  error: {err}")
        sc = execution_result.get("syntax_check", {})
        if sc and not sc.get("valid"):
            error_lines.append(f"  syntax: {sc.get('error', '')}")
        for iss in execution_result.get("validation_issues", []):
            error_lines.append(f"  validation: {iss.get('detail', '')}")
        error_details = "\n".join(error_lines) if error_lines else "  No error details"

        prompt = FIX_VIS_SPEC_PROMPT.format(
            node_details=node_details,
            chart_type=chart_type,
            input_tables_info=input_tables_info,
            spec_json=spec_json,
            error_details=error_details,
            diagnosis_text=diagnosis_text,
            available_fields=available_fields
        )

        messages = [
            {"role": "system", "content": "You are a Vega-Lite visualization expert."},
            {"role": "user", "content": prompt}
        ]
        _raw = ""

        try:
            response = self.model_client.chat(messages, temperature=0.3)
            _raw = response["content"]
            parsed = self._extract_json_object(_raw)
            if not parsed:
                return {"success": False, "spec": {}, "metadata": {}, "error": "Failed to parse LLM output",
                        "_prompt_messages": messages, "_raw_response": _raw}

            spec = parsed.get("spec", {})
            metadata = parsed.get("metadata", {})
            if not spec:
                return {"success": False, "spec": {}, "metadata": {}, "error": "LLM returned empty spec",
                        "_prompt_messages": messages, "_raw_response": _raw}

            return {"success": True, "spec": spec, "metadata": metadata, "error": None,
                    "_prompt_messages": messages, "_raw_response": _raw}
        except Exception as e:
            return {"success": False, "spec": {}, "metadata": {}, "error": str(e),
                    "_prompt_messages": messages, "_raw_response": _raw}

    def analyze_interaction_error(
        self,
        node: Dict[str, Any],
        interaction_spec: Dict[str, Any],
        js_code: str,
        source_specs: Dict[str, Dict],
        target_specs: Dict[str, Dict],
        execution_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Analyze an interaction error and suggest fixes (may target plan/data/vis/interaction).

        Returns:
            Dict with root_cause, fix_strategy, suggested_fixes, explanation
        """
        node_details = f"  {node['id']}: {node.get('name', '')} - {node.get('description', '')} | trigger: {node.get('trigger', '')} effect: {node.get('effect', '')}"
        interaction_spec_json = json.dumps(interaction_spec, ensure_ascii=False, indent=2) if interaction_spec else "{}"
        source_views_info = "\n".join(
            f"  {sv.get('id', '')}: link_field={sv.get('link_field', '')} channels={sv.get('source_channels', [])}"
            for sv in (interaction_spec.get("source_views", []) if interaction_spec else [])
        ) or "  None"
        cv = interaction_spec.get("controlled_view", {}) if interaction_spec else {}
        target_views_info = f"  {cv.get('view', '')}: field={cv.get('field', '')} action={cv.get('action', '')}"
        source_specs_json = json.dumps({k: v.get("spec", {}) for k, v in source_specs.items()}, ensure_ascii=False, indent=2) if source_specs else "{}"
        target_specs_json = json.dumps({k: v.get("spec", {}) for k, v in target_specs.items()}, ensure_ascii=False, indent=2) if target_specs else "{}"

        error_lines = []
        err = execution_result.get("error", "")
        if err:
            error_lines.append(f"  error: {err}")
        for iss in execution_result.get("validation_issues", []):
            error_lines.append(f"  validation: {iss.get('detail', iss.get('message', ''))}")
        error_details = "\n".join(error_lines) if error_lines else "  No error details"

        prompt = INTERACTION_ERROR_ANALYSIS_PROMPT.format(
            node_details=node_details,
            source_views_info=source_views_info,
            target_views_info=target_views_info,
            interaction_spec_json=interaction_spec_json,
            js_code=js_code or "",
            source_specs_json=source_specs_json,
            target_specs_json=target_specs_json,
            error_details=error_details
        )

        messages = [
            {"role": "system", "content": "You are a Vega-Lite interaction expert and debugger."},
            {"role": "user", "content": prompt}
        ]
        _raw = ""

        try:
            response = self.model_client.chat(messages, temperature=0.3)
            _raw = response["content"]
            result = self._extract_json_object(_raw)
            if not result:
                return {
                    "success": False, "root_cause": "interaction_code",
                    "fix_strategy": "modify_interaction", "suggested_fixes": {},
                    "explanation": "Failed to parse LLM output",
                    "_prompt_messages": messages, "_raw_response": _raw
                }
            return {
                "success": True,
                "root_cause": result.get("root_cause", "interaction_code"),
                "fix_strategy": result.get("fix_strategy", "modify_interaction"),
                "suggested_fixes": result.get("suggested_fixes", {}),
                "explanation": result.get("explanation", ""),
                "_prompt_messages": messages, "_raw_response": _raw
            }
        except Exception as e:
            return {
                "success": False, "root_cause": "interaction_code",
                "fix_strategy": "modify_interaction", "suggested_fixes": {},
                "explanation": f"Exception: {e}",
                "_prompt_messages": messages, "_raw_response": _raw
            }

    def fix_interaction(
        self,
        node: Dict[str, Any],
        interaction_spec: Dict[str, Any],
        js_code: str,
        source_specs: Dict[str, Dict],
        target_specs: Dict[str, Dict],
        execution_result: Dict[str, Any],
        diagnosis_text: str,
        available_fields: str = ""
    ) -> Dict[str, Any]:
        """
        Ask LLM to regenerate a corrected interaction spec based on diagnosis.

        Returns:
            Dict with success, interaction_spec, js_fix_hint, error
        """
        node_details = f"  {node['id']}: {node.get('name', '')} - {node.get('description', '')} | trigger: {node.get('trigger', '')} effect: {node.get('effect', '')}"
        interaction_spec_json = json.dumps(interaction_spec, ensure_ascii=False, indent=2) if interaction_spec else "{}"
        source_views_info = "\n".join(
            f"  {sv.get('id', '')}: link_field={sv.get('link_field', '')} channels={sv.get('source_channels', [])}"
            for sv in (interaction_spec.get("source_views", []) if interaction_spec else [])
        ) or "  None"
        cv = interaction_spec.get("controlled_view", {}) if interaction_spec else {}
        target_views_info = f"  {cv.get('view', '')}: field={cv.get('field', '')} action={cv.get('action', '')}"

        error_lines = []
        err = execution_result.get("error", "")
        if err:
            error_lines.append(f"  error: {err}")
        for iss in execution_result.get("validation_issues", []):
            error_lines.append(f"  validation: {iss.get('detail', iss.get('message', ''))}")
        error_details = "\n".join(error_lines) if error_lines else "  No error details"

        prompt = FIX_INTERACTION_PROMPT.format(
            node_details=node_details,
            source_views_info=source_views_info,
            target_views_info=target_views_info,
            interaction_spec_json=interaction_spec_json,
            js_code=js_code or "",
            error_details=error_details,
            diagnosis_text=diagnosis_text,
            available_fields=available_fields
        )

        messages = [
            {"role": "system", "content": "You are a Vega-Lite interaction expert."},
            {"role": "user", "content": prompt}
        ]
        _raw = ""

        try:
            response = self.model_client.chat(messages, temperature=0.3)
            _raw = response["content"]
            parsed = self._extract_json_object(_raw)
            if not parsed:
                return {"success": False, "interaction_spec": {}, "js_fix_hint": "", "error": "Failed to parse LLM output",
                        "_prompt_messages": messages, "_raw_response": _raw}

            return {
                "success": True,
                "interaction_spec": parsed.get("interaction_spec", {}),
                "js_fix_hint": parsed.get("js_fix_hint", ""),
                "error": None,
                "_prompt_messages": messages, "_raw_response": _raw
            }
        except Exception as e:
            return {"success": False, "interaction_spec": {}, "js_fix_hint": "", "error": str(e),
                    "_prompt_messages": messages, "_raw_response": _raw}

    # ------------------------------------------------------------------
    # Data error analysis
    # ------------------------------------------------------------------
    def _build_data_input_profiles(
        self,
        input_nodes: List[Dict[str, Any]],
        input_table_paths: Dict[str, str],
        sample_rows: int = 5
    ) -> str:
        """Build exact, compact table profiles for data diagnosis/fixing prompts."""
        node_map = {item.get("id"): item for item in input_nodes if item.get("id")}
        ordered_ids = list(node_map)
        ordered_ids.extend(node_id for node_id in input_table_paths if node_id not in node_map)
        profiles = []

        for node_id in ordered_ids:
            node = node_map.get(node_id, {})
            path = input_table_paths.get(node_id, "")
            profile = {
                "id": node_id,
                "name": node.get("name", node_id),
                "path_variable": f"INPUT_TABLE_PATH_{node_id}",
                "path_available": bool(path and os.path.isfile(path))
            }
            if not profile["path_available"]:
                profile["error"] = "Input path is missing or the file does not exist"
                profiles.append(profile)
                continue

            try:
                import pandas as pd
                frame = pd.read_csv(path, nrows=sample_rows)
                profile.update({
                    "columns": list(frame.columns),
                    "dtypes": {column: str(frame[column].dtype) for column in frame.columns},
                    "null_counts_in_sample": {
                        column: int(frame[column].isna().sum()) for column in frame.columns
                    },
                    "sample_rows": frame.to_dict(orient="records")
                })
            except Exception as exc:
                profile["error"] = f"Failed to profile CSV: {type(exc).__name__}: {exc}"
            profiles.append(profile)

        if not profiles:
            profiles.append({
                "error": "No upstream input table was provided",
                "path_available": False
            })
        return json.dumps(profiles, ensure_ascii=False, indent=2, default=str)

    @staticmethod
    def _format_data_error_details(execution_result: Dict[str, Any]) -> str:
        """Format all available runtime evidence, including traceback and validation."""
        details = []
        error = execution_result.get("error")
        if error:
            details.append(f"error: {error}")

        traceback_text = execution_result.get("error_traceback")
        if traceback_text:
            details.append(f"traceback:\n{traceback_text[-6000:]}")

        syntax_check = execution_result.get("syntax_check") or {}
        if not syntax_check.get("valid", True):
            details.append(
                f"syntax_check: type={syntax_check.get('error_type')} "
                f"detail={syntax_check.get('error')}"
            )

        for issue in execution_result.get("validation_issues") or []:
            details.append(
                "validation: "
                f"type={issue.get('type')} columns={issue.get('columns', [])} "
                f"count={issue.get('count', 0)} detail={issue.get('detail', '')}"
            )

        if execution_result.get("success") and not execution_result.get("validation_issues"):
            details.append("No execution failure or validation issue was reported")
        return "\n".join(f"  {line}" for line in details) if details else "  No error details"

    @staticmethod
    def _infer_data_diagnosis(execution_result: Dict[str, Any]) -> Dict[str, Any]:
        """Create an evidence-based fallback diagnosis before asking the model."""
        error = str(execution_result.get("error") or "")
        syntax_check = execution_result.get("syntax_check") or {}
        issues = execution_result.get("validation_issues") or []
        root_cause = "runtime_error"
        evidence = []
        modification = "Repair the failing expression using the traceback and exact input profile."

        if syntax_check and not syntax_check.get("valid", True):
            root_cause = "syntax_error"
            evidence.append(str(syntax_check.get("error") or error))
            modification = "Correct the reported Python syntax error before changing data logic."
        elif "No such file" in error or "FileNotFoundError" in error:
            root_cause = "missing_input"
            evidence.append(error)
            modification = "Use only the provided INPUT_TABLE_PATH_* variables and verify the upstream dependency."
        elif "KeyError" in error:
            root_cause = "column_name"
            evidence.append(error)
            modification = "Replace the missing field with the exact matching column from the input profile."
        elif any(token in error for token in ("TypeError", "ValueError", "could not convert", "Can only use")):
            root_cause = "data_type"
            evidence.append(error)
            modification = "Normalize the involved columns to compatible types before the failing operation."
        elif "result_df" in error or "did not produce" in error or "is not a DataFrame" in error:
            root_cause = "output_contract"
            evidence.append(error)
            modification = "Assign the final pandas DataFrame to the mandatory variable result_df."
        elif any(issue.get("type") == "empty_result" for issue in issues):
            root_cause = "empty_result"
            evidence.extend(str(issue.get("detail")) for issue in issues)
            modification = "Correct filters, joins, or grouping so the intended transformation returns rows."
        elif any(issue.get("type") in ("nan_values", "inf_values") for issue in issues):
            root_cause = "invalid_values"
            evidence.extend(str(issue.get("detail")) for issue in issues)
            modification = "Handle missing values and division-by-zero explicitly without disabling validation."
        elif any(issue.get("type") == "constant_analytical_output" for issue in issues):
            root_cause = "logic_error"
            evidence.extend(str(issue.get("detail")) for issue in issues)
            modification = (
                "Use a genuinely varying analytical field from the available "
                "inputs. Do not relabel counts, IDs, or constants as the requested metric."
            )
        elif any(issue.get("type") == "field_contract_violation" for issue in issues):
            root_cause = "output_contract"
            evidence.extend(str(issue.get("detail")) for issue in issues)
            modification = (
                "Preserve every required input/output field in the stable field "
                "contract and do not introduce undeclared predecessors."
            )
        elif error:
            evidence.append(error)

        return {
            "root_cause": root_cause,
            "fix_strategy": "modify_code",
            "suggested_fixes": {
                "code_modifications": modification,
                "data_modifications": None
            },
            "evidence": evidence,
            "explanation": "Local diagnosis inferred from the structured execution result."
        }

    @staticmethod
    def _extract_python_code(text: str) -> str:
        """Extract a Python code block when a model does not return valid JSON."""
        for pattern in (
            r"\x60\x60\x60python\s*([\s\S]*?)\s*\x60\x60\x60",
            r"\x60\x60\x60\s*([\s\S]*?)\s*\x60\x60\x60"
        ):
            matches = re.findall(pattern, text or "")
            if matches:
                return matches[-1].strip()
        return ""

    def analyze_data_error(
        self,
        node: Dict[str, Any],
        code: str,
        input_nodes: List[Dict[str, Any]],
        input_table_paths: Dict[str, str],
        execution_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyze a data processing error and suggest fixes."""
        print(f"[ErrorAgent.analyze_data_error] node={node.get('id','?')} success={execution_result.get('success')}", flush=True)
        node_details = f"  {node['id']}: {node.get('name', '')} - {node.get('description', '')} | task: {node.get('task', '')}"
        input_tables_info = self._build_data_input_profiles(input_nodes, input_table_paths)
        local_diagnosis = self._infer_data_diagnosis(execution_result)
        error_details = (
            self._format_data_error_details(execution_result)
            + "\n\n  Local pre-diagnosis: "
            + json.dumps(local_diagnosis, ensure_ascii=False, default=str)
        )

        prompt = DATA_ERROR_ANALYSIS_PROMPT.format(
            node_details=node_details,
            input_tables_info=input_tables_info,
            code=code,
            error_details=error_details
        )

        messages = [
            {"role": "system", "content": "You are a Python/pandas data processing expert."},
            {"role": "user", "content": prompt}
        ]
        _raw = ""

        try:
            response = self.model_client.chat(messages, temperature=0.3)
            _raw = response["content"]
            result = self._extract_json_object(_raw)
            if not result:
                return {
                    "success": True,
                    **local_diagnosis,
                    "diagnosis_source": "local_fallback",
                    "llm_parse_error": "Failed to parse LLM output",
                    "_prompt_messages": messages,
                    "_raw_response": _raw
                }
            return {
                "success": True,
                "root_cause": result.get("root_cause", local_diagnosis["root_cause"]),
                "fix_strategy": result.get("fix_strategy", "modify_code"),
                "suggested_fixes": result.get("suggested_fixes") or local_diagnosis["suggested_fixes"],
                "evidence": result.get("evidence") or local_diagnosis["evidence"],
                "explanation": result.get("explanation", ""),
                "diagnosis_source": "llm",
                "local_diagnosis": local_diagnosis,
                "_prompt_messages": messages,
                "_raw_response": _raw
            }
        except Exception as e:
            return {
                "success": True,
                **local_diagnosis,
                "diagnosis_source": "local_fallback",
                "llm_error": str(e),
                "_prompt_messages": messages,
                "_raw_response": _raw
            }

    # ------------------------------------------------------------------
    # Fix data processing code
    # ------------------------------------------------------------------
    def fix_data(
        self,
        node: Dict[str, Any],
        code: str,
        input_nodes: List[Dict[str, Any]],
        input_table_paths: Dict[str, str],
        execution_result: Dict[str, Any],
        diagnosis_text: str
    ) -> Dict[str, Any]:
        """Fix data processing code based on diagnosis."""
        print(f"[ErrorAgent.fix_data] node={node.get('id','?')}", flush=True)
        node_details = f"  {node['id']}: {node.get('name', '')} - {node.get('description', '')}"
        input_tables_info = self._build_data_input_profiles(input_nodes, input_table_paths)
        error_details = self._format_data_error_details(execution_result)
        output_var = "result_df"

        prompt = FIX_DATA_CODE_PROMPT.format(
            node_details=node_details,
            input_tables_info=input_tables_info,
            code=code,
            error_details=error_details,
            diagnosis_text=diagnosis_text,
            output_var=output_var
        )

        messages = [
            {"role": "system", "content": "You are a Python/pandas data processing expert."},
            {"role": "user", "content": prompt}
        ]
        _raw = ""

        try:
            response = self.model_client.chat(messages, temperature=0.3)
            _raw = response["content"]
            result = self._extract_json_object(_raw)
            fixed_code = result.get("code", "") if result else self._extract_python_code(_raw)
            fixed_code = fixed_code.strip()

            if fixed_code and not re.search(r"\bresult_df\s*=", fixed_code):
                legacy_output = f"{node['id']}_result"
                if re.search(rf"\b{re.escape(legacy_output)}\s*=", fixed_code):
                    fixed_code += f"\nresult_df = {legacy_output}"

            if not fixed_code:
                return {
                    "success": False, "code": code,
                    "error": "Failed to generate fixed code",
                    "_prompt_messages": messages, "_raw_response": _raw
                }

            try:
                compile(fixed_code, "<error_agent_fixed_code>", "exec")
            except SyntaxError as exc:
                return {
                    "success": False,
                    "code": fixed_code,
                    "error": f"Generated fix has SyntaxError at line {exc.lineno}: {exc.msg}",
                    "syntax_check": {
                        "valid": False,
                        "error": str(exc),
                        "error_type": "syntax_error"
                    },
                    "_prompt_messages": messages,
                    "_raw_response": _raw
                }

            if not re.search(r"\bresult_df\s*=", fixed_code):
                return {
                    "success": False,
                    "code": fixed_code,
                    "error": "Generated fix does not assign the mandatory result_df variable",
                    "_prompt_messages": messages,
                    "_raw_response": _raw
                }

            return {
                "success": True,
                "code": fixed_code,
                "metadata": result.get("metadata", {}) if result else {},
                "syntax_check": {"valid": True, "error": None, "error_type": None},
                "_prompt_messages": messages,
                "_raw_response": _raw
            }
        except Exception as e:
            return {
                "success": False, "code": code,
                "error": str(e),
                "_prompt_messages": messages, "_raw_response": _raw
            }

    def handle_error(
        self,
        error_context: Dict[str, Any],
        source_tag: str = "unknown",
        analysis_result: Dict[str, Any] = None,
        fix_result: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Record and handle an error from a node processing step.

        Args:
            error_context: Dict containing node info, inputs, execution result.
            source_tag: Origin tag, e.g. "data_generate", "vis_generate", "regenerate".
            analysis_result: Optional result from analyze_vis_error / analyze_interaction_error.
            fix_result: Optional result from fix_vis_spec / fix_interaction.

        Returns:
            Dict with handled, record_path, timestamp, source_tag, summary
        """
        print(f"[ErrorAgent.handle_error] source_tag={source_tag} node_id={error_context.get('node', {}).get('id','?')}", flush=True)
        timestamp = datetime.now().isoformat()

        node = error_context.get("node", {})
        node_id = node.get("id", "unknown")
        exec_result = error_context.get("execution_result", {})
        original_exec_result = (
            error_context.get("original_execution_result")
            or exec_result
        )
        recovery_attempts = error_context.get("recovery_attempts", [])
        syntax_check = original_exec_result.get("syntax_check") or {}
        validation_issues = original_exec_result.get("validation_issues") or []
        error_msg = original_exec_result.get("error") or "No error message"

        issues_summary = []
        if syntax_check and not syntax_check.get("valid"):
            issues_summary.append(f"syntax_error: {syntax_check.get('error')}")
        if not original_exec_result.get("success"):
            issues_summary.append(f"execution_error: {error_msg}")
        for issue in validation_issues:
            issues_summary.append(
                f"{issue.get('type', 'validation_error')}: "
                f"{issue.get('count', 0)} issue(s) in {issue.get('columns', [])}"
            )

        summary = "; ".join(issues_summary) if issues_summary else "unknown_issue"
        recovered = bool(
            exec_result.get("success")
            and not (exec_result.get("validation_issues") or [])
            and recovery_attempts
        )

        record = {
            "timestamp": timestamp,
            "node_id": node_id,
            "source_tag": source_tag,
            "summary": summary,
            "recovery_status": {
                "recovered": recovered,
                "attempt_count": len(recovery_attempts),
                "final_success": bool(exec_result.get("success")),
                "final_validation_issue_count": len(exec_result.get("validation_issues") or [])
            },
            "original_error": {
                "error": original_exec_result.get("error"),
                "error_traceback": original_exec_result.get("error_traceback"),
                "syntax_check": original_exec_result.get("syntax_check"),
                "validation_issues": original_exec_result.get("validation_issues", []),
                "columns": original_exec_result.get("columns", []),
                "row_count": original_exec_result.get("row_count", 0)
            },
            "final_execution_result": exec_result,
            "recovery_attempts": recovery_attempts,
            "error_context": error_context,
            "analysis_result": analysis_result,
            "fix_result": fix_result
        }

        if analysis_result:
            record["diagnosis"] = {
                "root_cause": analysis_result.get("root_cause"),
                "fix_strategy": analysis_result.get("fix_strategy"),
                "suggested_fixes": analysis_result.get("suggested_fixes"),
                "evidence": analysis_result.get("evidence"),
                "explanation": analysis_result.get("explanation"),
                "diagnosis_source": analysis_result.get("diagnosis_source"),
                "local_diagnosis": analysis_result.get("local_diagnosis"),
                "llm_error": analysis_result.get("llm_error"),
                "llm_parse_error": analysis_result.get("llm_parse_error"),
                "analysis_prompt_messages": analysis_result.get("_prompt_messages"),
                "analysis_raw_response": analysis_result.get("_raw_response")
            }
        if fix_result:
            record["fix"] = {
                "applied_fix_success": fix_result.get("success"),
                "fixed_code": fix_result.get("code"),
                "metadata": fix_result.get("metadata"),
                "error": fix_result.get("error"),
                "syntax_check": fix_result.get("syntax_check"),
                "fix_prompt_messages": fix_result.get("_prompt_messages"),
                "fix_raw_response": fix_result.get("_raw_response")
            }

        record_path = None
        if self.project_dir:
            error_dir = os.path.join(self.project_dir, "errors")
            os.makedirs(error_dir, exist_ok=True)
            safe_ts = timestamp.replace(":", "-").replace(".", "-")
            safe_node_id = re.sub(r'[<>:"/\\|?*]', '_', node_id)
            record_path = os.path.join(error_dir, f"{source_tag}_{safe_node_id}_{safe_ts}.json")
            with open(record_path, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)

        return {
            "handled": True,
            "record_path": record_path,
            "timestamp": timestamp,
            "source_tag": source_tag,
            "summary": summary,
            "has_diagnosis": analysis_result is not None,
            "has_fix": fix_result is not None,
            "recovered": recovered,
            "attempt_count": len(recovery_attempts)
        }


_error_agent: Optional[ErrorAgent] = None


def get_error_agent(project_dir: str = None) -> ErrorAgent:
    """Get or create the global Error Agent instance"""
    global _error_agent
    if _error_agent is None or (project_dir and _error_agent.project_dir != project_dir):
        _error_agent = ErrorAgent(project_dir=project_dir)
    return _error_agent


def init_error_agent(project_dir: str = None) -> ErrorAgent:
    """Initialize the global Error Agent"""
    global _error_agent
    _error_agent = ErrorAgent(project_dir=project_dir)
    return _error_agent
