"""
Vis Agent - Agent responsible for generating and validating Vega-Lite
visualization specifications for V (visualization) nodes.
"""

import os
import json
import re
import traceback
from typing import List, Dict, Any, Optional
from model import get_model_client, ModelClient
from agents.error_agent import get_error_agent
from prompts.vis_agent_prompts import (
    VALID_MARK_TYPES,
    SYSTEM_PROMPT_CHAT_JSON,
    SYSTEM_PROMPT_GENERATE,
    VISUALIZATION_SPEC_PROMPT
)


class VisAgent:
    """Vis Agent - Generate and validate Vega-Lite specs for V nodes"""

    def __init__(
        self,
        model_client: Optional[ModelClient] = None,
        project_dir: str = None
    ):
        self.model_client = model_client or get_model_client()
        self.project_dir = project_dir

    def _chat_json(self, user_prompt: str, temperature: float = 0.3) -> Dict[str, Any]:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_CHAT_JSON},
            {"role": "user", "content": user_prompt}
        ]
        response = self.model_client.chat(messages, temperature=temperature)
        return self._extract_json(response["content"])

    def _extract_json(self, text: str) -> Dict[str, Any]:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
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
        return {"raw_text": text}

    def _extract_code_block(self, text: str) -> str:
        pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
        matches = re.findall(pattern, text)
        if matches:
            return matches[-1].strip()
        return text.strip()

    def generate_visualization_spec(
        self,
        node: Dict[str, Any],
        input_nodes: List[Dict[str, Any]],
        input_table_paths: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Generate a Vega-Lite spec + metadata for a V node.

        Args:
            node: V node info (id, name, description, chart_type)
            input_nodes: Input d/D nodes
            input_table_paths: Mapping node_id -> CSV path

        Returns:
            Dict: {spec: {...}, metadata: {marktype, used_tables, used_fields, encoding_fields}}
        """
        inputs_desc = []
        for inp in input_nodes:
            nid = inp["id"]
            csv_path = input_table_paths.get(nid, "")
            if csv_path and os.path.exists(csv_path):
                try:
                    import pandas as pd
                    df = pd.read_csv(csv_path, nrows=20)
                    columns = list(df.columns)
                    dtypes = {c: str(df[c].dtype) for c in columns}
                    inputs_desc.append({
                        "id": nid,
                        "name": inp.get("name", nid),
                        "file_path": csv_path,
                        "columns": columns,
                        "dtypes": dtypes,
                        "sample_rows": df.to_dict(orient="records")
                    })
                except Exception as e:
                    inputs_desc.append({"id": nid, "name": inp.get("name", nid), "file_path": csv_path, "error": str(e)})
            else:
                inputs_desc.append({"id": nid, "name": inp.get("name", nid), "file_path": csv_path, "note": "File not found"})

        chart_type = node.get("chart_type", "")

        inputs_json = json.dumps(inputs_desc, ensure_ascii=False, indent=2)

        prompt = VISUALIZATION_SPEC_PROMPT.format(
            node_id=node["id"],
            node_name=node.get("name", ""),
            node_description=node.get("description", ""),
            chart_type=chart_type,
            inputs_json=inputs_json
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_GENERATE},
            {"role": "user", "content": prompt}
        ]

        response = self.model_client.chat(messages, temperature=0.3)
        raw = response["content"]
        parsed = self._extract_json(raw)

        spec = parsed.get("spec", {})
        metadata = parsed.get("metadata", {})

        if not spec and not metadata:
            code = self._extract_code_block(raw)
            try:
                parsed2 = json.loads(code)
                spec = parsed2.get("spec", parsed2)
                metadata = parsed2.get("metadata", {})
            except json.JSONDecodeError:
                spec = {}
                metadata = {}

        return {
            "spec": spec,
            "metadata": metadata,
            "raw_output": raw
        }

    def validate_visualization(
        self,
        spec: Dict[str, Any],
        metadata: Dict[str, Any],
        input_table_paths: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Validate a Vega-Lite spec and its metadata.

        Checks:
        - Spec is non-empty valid JSON
        - marktype is a known Vega-Lite mark
        - All referenced fields exist in the input tables

        Returns:
            Dict: {valid: bool, issues: [{type, detail}]}
        """
        issues = []

        if not spec or not isinstance(spec, dict):
            issues.append({"type": "empty_spec", "detail": "Vega-Lite spec is empty or not a valid object"})
            return {"valid": False, "issues": issues, "syntax_check": {"valid": False, "error": "Empty spec", "error_type": "spec_error"}}

        spec_str = json.dumps(spec)
        try:
            json.loads(spec_str)
        except json.JSONDecodeError as e:
            issues.append({"type": "json_parse_error", "detail": str(e)})
            return {"valid": False, "issues": issues, "syntax_check": {"valid": False, "error": str(e), "error_type": "json_parse_error"}}

        mark = spec.get("mark", "")
        if isinstance(mark, dict):
            mark = mark.get("type", "")
        mark_lower = str(mark).lower() if mark else ""

        if not mark_lower:
            issues.append({"type": "missing_mark", "detail": "No mark type specified in the spec"})
        elif mark_lower not in VALID_MARK_TYPES:
            issues.append({
                "type": "invalid_marktype",
                "detail": f"Mark type '{mark}' is not a valid Vega-Lite mark. Valid types: {', '.join(sorted(VALID_MARK_TYPES))}"
            })

        declared_marktype = metadata.get("marktype", "").lower() if metadata else ""
        if declared_marktype and declared_marktype != mark_lower:
            issues.append({
                "type": "marktype_mismatch",
                "detail": f"Metadata marktype '{declared_marktype}' does not match spec mark '{mark_lower}'"
            })

        used_fields = set()
        encoding = spec.get("encoding", {})
        for channel, enc_def in encoding.items():
            if isinstance(enc_def, dict):
                field = enc_def.get("field", "")
                if field:
                    used_fields.add(field)

        for channel in ("layer", "facet", "repeat"):
            child = spec.get(channel, {})
            if isinstance(child, dict) and "encoding" in child:
                for ch2, ed2 in child["encoding"].items():
                    if isinstance(ed2, dict) and ed2.get("field"):
                        used_fields.add(ed2["field"])

        if metadata:
            meta_fields = set(metadata.get("used_fields", []))
            for f in meta_fields:
                if f and f not in used_fields:
                    issues.append({
                        "type": "metadata_field_not_in_spec",
                        "detail": f"Metadata lists field '{f}' but it is not found in the spec encoding"
                    })

            enc_fields = metadata.get("encoding_fields", {})
            for ch, f in enc_fields.items():
                if f and f not in used_fields:
                    issues.append({
                        "type": "encoding_field_not_in_spec",
                        "detail": f"Metadata says encoding channel '{ch}' uses field '{f}' but it is not found in the spec encoding"
                    })

        all_table_fields = set()
        if input_table_paths:
            try:
                import pandas as pd
                for tpath in input_table_paths.values():
                    if os.path.exists(tpath):
                        df = pd.read_csv(tpath, nrows=1)
                        all_table_fields.update(df.columns)
            except Exception:
                pass

        if all_table_fields:
            for f in used_fields:
                if f not in all_table_fields:
                    issues.append({
                        "type": "field_not_found",
                        "detail": f"Field '{f}' referenced in spec encoding does not exist in the input tables. Available fields: {list(all_table_fields)[:20]}"
                    })

        syntax_check = {"valid": len(issues) == 0, "issues_count": len(issues), "error_type": None}
        if issues:
            syntax_check["error"] = issues[0]["detail"]
            syntax_check["error_type"] = issues[0]["type"]

        return {"valid": len(issues) == 0, "issues": issues, "syntax_check": syntax_check}

    def process_v_node(
        self,
        node: Dict[str, Any],
        input_nodes: List[Dict[str, Any]],
        input_table_paths: Dict[str, str],
        output_dir: str
    ) -> Dict[str, Any]:
        """
        Process a single V node: generate spec, validate, report errors.

        Returns:
            Dict: {node_id, spec, metadata, spec_json, success, syntax_check, validation_issues, source_tag, error_report}
        """
        node_id = node["id"]
        out = {
            "node_id": node_id,
            "node_type": "V",
            "spec": {},
            "metadata": {},
            "spec_json": "",
            "success": False,
            "syntax_check": None,
            "validation_issues": [],
            "source_tag": "vis_generate",
            "error": None
        }

        result = self.generate_visualization_spec(node, input_nodes, input_table_paths)
        spec = result.get("spec", {})
        metadata = result.get("metadata", {})
        spec_json = json.dumps(spec, ensure_ascii=False) if spec else ""

        out["spec"] = spec
        out["metadata"] = metadata
        out["spec_json"] = spec_json

        validation = self.validate_visualization(spec, metadata, input_table_paths)
        out["syntax_check"] = validation.get("syntax_check")
        out["validation_issues"] = validation.get("issues", [])

        if validation.get("valid"):
            out["success"] = True
            spec_path = os.path.join(output_dir, f"{node_id}.json")
            try:
                os.makedirs(output_dir, exist_ok=True)
                with open(spec_path, "w", encoding="utf-8") as f:
                    json.dump(spec, f, ensure_ascii=False, indent=2)
                out["spec_path"] = spec_path
            except Exception as e:
                out["error"] = f"Failed to save spec: {e}"
        else:
            out["error"] = validation["issues"][0]["detail"] if validation["issues"] else "Validation failed"

        has_issues = not out["success"] or len(out["validation_issues"]) > 0
        if has_issues:
            try:
                error_agent = get_error_agent(project_dir=self.project_dir)
                error_context = {
                    "node": node,
                    "input_nodes": input_nodes,
                    "input_table_paths": input_table_paths,
                    "execution_result": {
                        "node_id": node_id,
                        "success": out["success"],
                        "error": out["error"],
                        "syntax_check": out["syntax_check"],
                        "validation_issues": out["validation_issues"],
                        "spec_path": out.get("spec_path")
                    }
                }
                error_result = error_agent.handle_error(error_context, source_tag="vis_generate")
                out["error_report"] = error_result
            except Exception:
                out["error_report"] = {"error": "Failed to report to error_agent"}

        return out


_vis_agent: Optional[VisAgent] = None


def get_vis_agent(project_dir: str = None) -> VisAgent:
    global _vis_agent
    if _vis_agent is None or _vis_agent.project_dir != project_dir:
        _vis_agent = VisAgent(project_dir=project_dir)
    return _vis_agent


def init_vis_agent(
    api_key: str = None,
    base_url: str = None,
    model_name: str = "qwen-turbo",
    project_dir: str = None
) -> VisAgent:
    global _vis_agent
    from model import init_model_client
    init_model_client(api_key=api_key, base_url=base_url)
    _vis_agent = VisAgent(model_client=get_model_client(), project_dir=project_dir)
    _vis_agent.model_client.set_model(model_name)
    return _vis_agent
