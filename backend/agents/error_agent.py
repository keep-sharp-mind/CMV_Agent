"""
Error Agent - Agent for handling errors during data processing, visualization, and plan generation.
Responsible for receiving, recording, and attempting to fix errors found during
data processing / visualization generation / plan validation.
"""

import os
import json
import copy
import re
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
    FIX_INTERACTION_PROMPT
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

        # Describe the validation rules for the prompt
        validation_rules_text = (
            "1. Each V must have exactly ONE incoming data edge (d->V or D->V)\n"
            "2. No cycles in the graph (acyclic)\n"
            "3. No isolated nodes (every D/V/I must connect to at least one other node)\n"
            "4. Every D node must have at least one incoming data edge (d->D or D->D)\n"
            "5. Every D node should have at least one downstream consumer\n"
            "6. Invalid edges: D->I, I->D, V->D, I->I are forbidden"
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
                "root_cause": result.get("root_cause", "dependency_graph"),
                "suggestions": result.get("suggestions", ""),
                "affected_nodes": result.get("affected_nodes", []),
                "needs_requirement_change": result.get("needs_requirement_change", False),
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
        timestamp = datetime.now().isoformat()

        node = error_context.get("node", {})
        node_id = node.get("id", "unknown")
        exec_result = error_context.get("execution_result", {})
        syntax_check = exec_result.get("syntax_check", {})
        validation_issues = exec_result.get("validation_issues", [])
        error_msg = exec_result.get("error", "No error message")

        issues_summary = []
        if syntax_check and not syntax_check.get("valid"):
            issues_summary.append(f"syntax_error: {syntax_check.get('error')}")
        if not exec_result.get("success"):
            issues_summary.append(f"execution_error: {error_msg}")
        for issue in validation_issues:
            issues_summary.append(
                f"{issue['type']}: {issue['count']} issue(s) in {issue['columns']}"
            )

        summary = "; ".join(issues_summary) if issues_summary else "unknown_issue"

        record = {
            "timestamp": timestamp,
            "node_id": node_id,
            "source_tag": source_tag,
            "summary": summary,
            "error_context": error_context,
            "analysis_result": analysis_result,
            "fix_result": fix_result
        }

        if analysis_result:
            record["diagnosis"] = {
                "root_cause": analysis_result.get("root_cause"),
                "fix_strategy": analysis_result.get("fix_strategy"),
                "suggested_fixes": analysis_result.get("suggested_fixes"),
                "explanation": analysis_result.get("explanation"),
                "analysis_prompt_messages": analysis_result.get("_prompt_messages"),
                "analysis_raw_response": analysis_result.get("_raw_response")
            }
        if fix_result:
            record["fix"] = {
                "applied_fix_success": fix_result.get("success"),
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
            "has_fix": fix_result is not None
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
