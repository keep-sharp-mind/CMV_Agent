"""
Error Agent - Agent for handling errors during data processing, visualization, and plan generation.
Responsible for receiving, recording, and attempting to fix errors found during
data processing / visualization generation / plan validation.
"""

import os
import json
import traceback
from datetime import datetime
from typing import List, Dict, Any, Optional
from model import get_model_client, ModelClient
from prompts.error_agent_prompts import (
    ANALYZE_PLAN_ERRORS_PROMPT,
    FIX_DEPENDENCIES_PROMPT,
    FIX_REQUIREMENTS_PROMPT
)


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
        text = text.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
        import re
        pattern = r"```(?:json)?\s*(\{[\s\S]*?\})\s*```"
        matches = re.findall(pattern, text)
        for match in matches:
            try:
                return json.loads(match.strip())
            except json.JSONDecodeError:
                continue
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        return None

    def _extract_json_array(self, text: str) -> Optional[List[Dict[str, Any]]]:
        """Extract a JSON array from text"""
        text = text.strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
        import re
        pattern = r"```(?:json)?\s*(\[[\s\S]*?\])\s*```"
        matches = re.findall(pattern, text)
        for match in matches:
            try:
                return json.loads(match.strip())
            except json.JSONDecodeError:
                continue
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
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

    def handle_error(
        self,
        error_context: Dict[str, Any],
        source_tag: str = "unknown"
    ) -> Dict[str, Any]:
        """
        Record and handle an error from a node processing step.

        Args:
            error_context: Dict containing node info, inputs, execution result.
            source_tag: Origin tag, e.g. "data_generate", "vis_generate", "regenerate".

        Returns:
            Dict: {
                "handled": bool,
                "record_path": str|None,
                "timestamp": str,
                "source_tag": str,
                "summary": str
            }
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
            "error_context": error_context
        }

        record_path = None
        if self.project_dir:
            error_dir = os.path.join(self.project_dir, "errors")
            os.makedirs(error_dir, exist_ok=True)
            safe_ts = timestamp.replace(":", "-").replace(".", "-")
            record_path = os.path.join(error_dir, f"{source_tag}_{node_id}_{safe_ts}.json")
            with open(record_path, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)

        return {
            "handled": True,
            "record_path": record_path,
            "timestamp": timestamp,
            "source_tag": source_tag,
            "summary": summary
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
