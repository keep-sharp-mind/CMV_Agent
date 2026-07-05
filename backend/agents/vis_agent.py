"""
Vis Agent - Agent responsible for generating and validating Vega-Lite
visualization specifications for V (visualization) nodes.
"""

import os
import json
import re
import copy
import traceback
import math
from typing import List, Dict, Any, Optional
from model import get_model_client, ModelClient
from agents.error_agent import get_error_agent
from prompts.vis_agent_prompts import (
    VALID_MARK_TYPES,
    SYSTEM_PROMPT_CHAT_JSON,
    SYSTEM_PROMPT_GENERATE,
    VISUALIZATION_SPEC_PROMPT
)


def _clean_json_text(text: str) -> str:
    """Replace NaN/Infinity with null for compliant JSON parsing."""
    return re.sub(r'\bNaN\b|\bInfinity\b|\b-Infinity\b', 'null', text)


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
        cleaned = _clean_json_text(text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
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
        return {"raw_text": text}

    def _extract_code_block(self, text: str) -> str:
        pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
        matches = re.findall(pattern, text)
        if matches:
            return matches[-1].strip()
        return text.strip()

    @staticmethod
    def _apply_quantitative_axis_domains(
        spec: Dict[str, Any],
        field_profiles: Dict[str, Any]
    ) -> None:
        """Use observed numeric ranges for x/y axes instead of zero-based defaults."""
        if not isinstance(spec, dict):
            return

        encoding = spec.get("encoding") or {}
        for channel in ("x", "y"):
            definition = encoding.get(channel)
            if not isinstance(definition, dict):
                continue
            if str(definition.get("type", "")).lower() != "quantitative":
                continue
            if definition.get("aggregate") or definition.get("bin"):
                continue
            field = definition.get("field")
            profile = field_profiles.get(field) or {}
            minimum = profile.get("min")
            maximum = profile.get("max")
            if not isinstance(minimum, (int, float)) or not isinstance(
                maximum, (int, float)
            ):
                continue
            if not math.isfinite(minimum) or not math.isfinite(maximum):
                continue
            span = maximum - minimum
            padding = span * 0.05 if span > 0 else max(abs(minimum) * 0.05, 1.0)
            scale = dict(definition.get("scale") or {})
            scale.update({
                "zero": False,
                "nice": True,
                "domain": [minimum - padding, maximum + padding]
            })
            definition["scale"] = scale

        for key in ("layer", "hconcat", "vconcat", "concat"):
            children = spec.get(key) or []
            if isinstance(children, list):
                for child in children:
                    VisAgent._apply_quantitative_axis_domains(
                        child, field_profiles
                    )
        nested_spec = spec.get("spec")
        if isinstance(nested_spec, dict):
            VisAgent._apply_quantitative_axis_domains(
                nested_spec, field_profiles
            )

    def convert_view_spec(
        self,
        node_id: str,
        spec: Dict[str, Any],
        project_id: str,
        input_table_paths: Dict[str, str],
        metadata: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Convert and enhance a spec into a complete Vega-Lite spec.
        Handles table→data.url conversion, mark enhancements, opacity auto-complete.

        The data URL is set to: /api/projects/{project_id}/data/{table_id}.csv/download
        which maps to the download_csv_data endpoint in app.py.
        """
        if not spec:
            return spec

        vega_lite = copy.deepcopy(spec)
        metadata = metadata or {}

        # Determine the CSV filename to use for data URL
        csv_filename = ""
        if 'table' in vega_lite:
            csv_filename = vega_lite['table']
            del vega_lite['table']
        elif 'data' in vega_lite and isinstance(vega_lite['data'], dict):
            if 'url' in vega_lite['data']:
                csv_filename = os.path.basename(vega_lite['data']['url'].rstrip('.csv')) + '.csv'
            elif 'values' in vega_lite['data']:
                # Try used_tables from metadata first (most reliable)
                used_tables = metadata.get('used_tables', [])
                if used_tables:
                    csv_filename = f"{used_tables[0]}.csv"
                else:
                    # Fallback: first input table that exists on disk
                    for tid in input_table_paths:
                        csv_filename = f"{tid}.csv"
                        break
                del vega_lite['data']

        if not csv_filename and input_table_paths:
            for tid in input_table_paths:
                csv_filename = f"{tid}.csv"
                break
        if csv_filename:
            csv_filename = csv_filename if csv_filename.endswith('.csv') else f"{csv_filename}.csv"
            base_url = os.environ.get(
                "DATA_SERVICE_URL", "http://localhost:5000/data"
            ).rstrip("/")
            vega_lite['data'] = {'url': f'{base_url}/{project_id}/{csv_filename}'}

        vega_lite.update({
            'description': node_id,
            'height': 'container',
            'width': 'container',
            "autosize": {
                "type": "fit",
                "contains": "padding"
            },
            '$schema': vega_lite.get('$schema', 'https://vega.github.io/schema/vega-lite/v6.json'),
            'config': {
                'background': 'rgba(0, 0, 0, 0)',
                'padding': 10,
                **vega_lite.get('config', {})
            }
        })

        field_profiles = metadata.get("input_field_profiles") or {}
        if isinstance(field_profiles, dict):
            self._apply_quantitative_axis_domains(
                vega_lite, field_profiles
            )

        if 'transform' not in vega_lite:
            vega_lite['transform'] = []
        if 'params' not in vega_lite:
            vega_lite['params'] = []
        if 'encoding' not in vega_lite:
            vega_lite['encoding'] = {}

        raw_mark = vega_lite.get('markType', vega_lite.get('mark', 'point'))
        mark_type = raw_mark['type'] if isinstance(raw_mark, dict) else raw_mark

        # Boxplot
        if mark_type == 'boxplot':
            encoding = vega_lite['encoding']
            if 'x' in encoding and 'color' in encoding:
                color_field = encoding['color'].get('field')
                x_type = encoding['x'].get('type')
                if color_field:
                    if x_type == 'quantitative':
                        encoding['yOffset'] = encoding['color']
                    else:
                        encoding['xOffset'] = encoding['color']
            vega_lite['mark'] = {
                'type': 'boxplot',
                'extent': 'min-max',
                'rule': {'color': '#000000'},
                **(raw_mark if isinstance(raw_mark, dict) else {})
            }

        # Area
        elif mark_type == 'area':
            vega_lite['mark'] = {
                'type': 'area',
                'interpolate': 'monotone',
                'line': True,
                **(raw_mark if isinstance(raw_mark, dict) else {})
            }
            if 'x' in vega_lite['encoding']:
                x_field = vega_lite['encoding']['x'].get('field')
                if x_field:
                    vega_lite['transform'].append({"sort": [{"field": x_field}]})

        # Geoshape → point
        elif mark_type == 'geoshape':
            vega_lite['mark'] = {
                'type': 'point',
                'tooltip': True,
                **(raw_mark if isinstance(raw_mark, dict) else {})
            }

        else:
            vega_lite['mark'] = raw_mark

        # Color legend
        if "color" in vega_lite["encoding"] and isinstance(vega_lite["encoding"]["color"], dict):
            if "legend" not in vega_lite["encoding"]["color"] or vega_lite["encoding"]["color"]["legend"] is None:
                vega_lite["encoding"]["color"]["legend"] = {}
            vega_lite["encoding"]["color"]["legend"].setdefault("orient", "bottom")

        return vega_lite

    def generate_visualization_spec(
        self,
        node: Dict[str, Any],
        input_nodes: List[Dict[str, Any]],
        input_table_paths: Dict[str, str],
        field_contract: Optional[Dict[str, Any]] = None
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
        input_field_profiles = {}
        for inp in input_nodes:
            nid = inp["id"]
            csv_path = input_table_paths.get(nid, "")
            if csv_path and os.path.exists(csv_path):
                try:
                    import pandas as pd
                    df = pd.read_csv(csv_path)
                    columns = list(df.columns)
                    dtypes = {c: str(df[c].dtype) for c in columns}
                    field_profiles = {}
                    for column in columns:
                        series = df[column].dropna()
                        profile = {
                            "data_type": dtypes[column],
                            "non_null_count": int(series.size),
                            "unique_count": int(series.nunique())
                        }
                        if pd.api.types.is_numeric_dtype(df[column]):
                            if not series.empty:
                                profile.update({
                                    "min": float(series.min()),
                                    "max": float(series.max()),
                                    "q01": float(series.quantile(0.01)),
                                    "q99": float(series.quantile(0.99))
                                })
                        else:
                            profile["sample_values"] = [
                                str(value) for value in series.unique()[:10]
                            ]
                        field_profiles[column] = profile
                        input_field_profiles.setdefault(column, profile)
                    inputs_desc.append({
                        "id": nid,
                        "name": inp.get("name", nid),
                        "file_path": csv_path,
                        "columns": columns,
                        "dtypes": dtypes,
                        "field_profiles": field_profiles,
                        "sample_rows": df.head(20).to_dict(orient="records")
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
            inputs_json=inputs_json,
            field_contract_json=json.dumps(
                field_contract or {}, ensure_ascii=False, indent=2
            )
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

        if isinstance(metadata, dict):
            metadata["input_field_profiles"] = input_field_profiles

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
        quantitative_axes = []
        for channel, enc_def in encoding.items():
            if isinstance(enc_def, dict):
                field = enc_def.get("field", "")
                if field:
                    used_fields.add(field)
                    if (
                        channel in ("x", "y")
                        and str(enc_def.get("type", "")).lower() == "quantitative"
                        and not enc_def.get("aggregate")
                        and not enc_def.get("bin")
                    ):
                        quantitative_axes.append((channel, field))

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

        # A quantitative axis with one distinct value creates a visually valid
        # but analytically meaningless flat chart (for example every y equals 1).
        if quantitative_axes and input_table_paths:
            try:
                import pandas as pd
                used_tables = set((metadata or {}).get("used_tables") or [])
                candidate_paths = [
                    path for table_id, path in input_table_paths.items()
                    if not used_tables or table_id in used_tables
                ]
                for channel, field in quantitative_axes:
                    distinct = set()
                    for path in candidate_paths:
                        if not os.path.exists(path):
                            continue
                        frame = pd.read_csv(path, usecols=lambda name: name == field)
                        if field in frame:
                            distinct.update(frame[field].dropna().unique().tolist())
                        if len(distinct) > 1:
                            break
                    if len(distinct) <= 1:
                        issues.append({
                            "type": "constant_quantitative_axis",
                            "detail": (
                                f"Quantitative {channel}-axis field '{field}' has "
                                f"only {len(distinct)} distinct non-null value(s). "
                                "Choose a genuinely varying metric or a more "
                                "appropriate chart; do not render a flat plot."
                            )
                        })
            except Exception:
                pass

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
        output_dir: str,
        project_id: str = "",
        field_contract: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process a single V node: generate spec, validate, report errors.

        Returns:
            Dict: {node_id, spec, metadata, spec_json, success, syntax_check, validation_issues, source_tag, error_report}
        """
        node_id = node["id"]
        if field_contract is None and self.project_dir:
            try:
                from agents.planner_agent import PlannerAgent
                contract_path = os.path.join(
                    self.project_dir, "data_flow_contract.json"
                )
                with open(contract_path, "r", encoding="utf-8") as file:
                    field_contract = PlannerAgent.build_node_contract(
                        json.load(file), node_id
                    )
            except (OSError, json.JSONDecodeError):
                field_contract = {}
        if not field_contract:
            field_contract = {
                "node_id": node_id,
                "required_inputs": {},
                "required_outputs": [],
                "allowed_predecessors": [
                    item.get("id") for item in input_nodes if item.get("id")
                ],
                "incoming_edges": [],
                "outgoing_edges": []
            }

        def apply_field_contract(validation_result, candidate_spec, candidate_metadata):
            if not field_contract:
                return validation_result
            from agents.planner_agent import PlannerAgent
            contract_issues = PlannerAgent.validate_artifact_contract(
                node_id,
                "V",
                {"spec": candidate_spec, "metadata": candidate_metadata},
                field_contract
            )
            if contract_issues:
                validation_result = dict(validation_result)
                validation_result["valid"] = False
                validation_result["issues"] = (
                    list(validation_result.get("issues") or [])
                    + contract_issues
                )
                syntax_check = dict(
                    validation_result.get("syntax_check") or {"valid": True}
                )
                syntax_check.update({
                    "valid": False,
                    "error": contract_issues[0]["detail"],
                    "error_type": "field_contract_violation"
                })
                validation_result["syntax_check"] = syntax_check
            return validation_result

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

        try:
            result = self.generate_visualization_spec(
                node, input_nodes, input_table_paths, field_contract
            )
        except TypeError as exc:
            if "generate_visualization_spec" not in str(exc):
                raise
            result = self.generate_visualization_spec(
                node, input_nodes, input_table_paths
            )
        spec = result.get("spec", {})
        metadata = result.get("metadata", {})
        spec_json = json.dumps(spec, ensure_ascii=False, indent=2) if spec else ""

        # Apply convert_view_spec to add table→data.url, mark enhancements, etc.
        if project_id:
            spec = self.convert_view_spec(node_id, spec, project_id, input_table_paths, metadata=metadata)
            spec_json = json.dumps(spec, ensure_ascii=False, indent=2)

        out["spec"] = spec
        out["metadata"] = metadata
        out["spec_json"] = spec_json

        validation = self.validate_visualization(spec, metadata, input_table_paths)
        validation = apply_field_contract(validation, spec, metadata)
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

                # Attempt auto-recovery: analyze error → fix spec → re-validate
                analysis = None
                fix_result = None
                try:
                    analysis = error_agent.analyze_vis_error(
                        node, spec, input_nodes, input_table_paths, error_context["execution_result"]
                    )
                    out["error_analysis"] = analysis

                    if analysis.get("success"):
                        fix_result = error_agent.fix_vis_spec(
                            node, spec, input_nodes, input_table_paths,
                            error_context["execution_result"],
                            f"Root cause: {analysis.get('root_cause')}. Fix strategy: {analysis.get('fix_strategy')}. Suggestion: {analysis.get('suggested_fixes', {}).get('vis_modifications', '')}."
                        )
                        out["error_recovery"] = fix_result

                        if fix_result.get("success") and fix_result.get("spec"):
                            fixed_spec = fix_result["spec"]
                            fixed_metadata = fix_result.get("metadata", {})
                            re_validation = self.validate_visualization(fixed_spec, fixed_metadata, input_table_paths)
                            re_validation = apply_field_contract(
                                re_validation, fixed_spec, fixed_metadata
                            )

                            if re_validation.get("valid"):
                                if project_id:
                                    fixed_spec = self.convert_view_spec(node_id, fixed_spec, project_id, input_table_paths, metadata=fixed_metadata)
                                out["spec"] = fixed_spec
                                out["metadata"] = fixed_metadata
                                out["spec_json"] = json.dumps(fixed_spec, ensure_ascii=False, indent=2)
                                out["success"] = True
                                out["error"] = None
                                out["validation_issues"] = []
                                out["syntax_check"] = re_validation.get("syntax_check")
                                out["recovered"] = True
                                spec_path = os.path.join(output_dir, f"{node_id}.json")
                                try:
                                    os.makedirs(output_dir, exist_ok=True)
                                    with open(spec_path, "w", encoding="utf-8") as f:
                                        json.dump(fixed_spec, f, ensure_ascii=False, indent=2)
                                    out["spec_path"] = spec_path
                                except Exception as e:
                                    out["error"] = f"Failed to save spec: {e}"
                except Exception:
                    out["error_recovery"] = {"error": "Failed to attempt auto-recovery"}

                # Save error record with diagnosis and fix results
                try:
                    error_result = error_agent.handle_error(
                        error_context, source_tag="vis_generate",
                        analysis_result=analysis, fix_result=fix_result
                    )
                    out["error_report"] = error_result
                except Exception:
                    out["error_report"] = {"error": "Failed to report to error_agent"}
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
