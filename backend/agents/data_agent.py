"""
Data Agent - Agent responsible for generating and executing data processing code
for D (data processing) nodes in the dependency graph.
"""

import os
import json
import re
import math
import time
import traceback
from typing import List, Dict, Any, Optional
from model import get_model_client, ModelClient
from agents.error_agent import get_error_agent
from prompts.data_agent_prompts import (
    SYSTEM_PROMPT_CHAT_JSON,
    SYSTEM_PROMPT_GENERATE,
    PROCESSING_CODE_PROMPT,
    FIELD_SEMANTICS_PROMPT
)


def _clean_json_text(text: str) -> str:
    """Replace NaN/Infinity with null for compliant JSON parsing."""
    import re
    return re.sub(r'\bNaN\b|\bInfinity\b|\b-Infinity\b', 'null', text)


def _canonicalize_concept(field_name: str) -> str:
    """Create a conservative fallback concept when semantic inference fails."""
    concept = re.sub(r"[^a-zA-Z0-9]+", "_", str(field_name)).strip("_").lower()
    for suffix in ("_type", "_value", "_name"):
        if concept.endswith(suffix) and len(concept) > len(suffix):
            concept = concept[:-len(suffix)]
            break
    return concept or "unknown"


def build_initial_field_semantics(
    d_nodes: List[Dict[str, Any]],
    database_schema: List[Dict[str, Any]]
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Build the raw-table semantic catalog used by subsequent D nodes."""
    table_map = {}
    for database in database_schema or []:
        if not isinstance(database, dict):
            continue
        db_name = database.get("db_name", "")
        for table in database.get("tables") or []:
            if not isinstance(table, dict):
                continue
            table_name = table.get("table_name", "")
            table_map[table_name] = table
            if db_name:
                table_map[f"{db_name}.{table_name}"] = table

    catalog = {}
    for node in d_nodes or []:
        node_id = node.get("id")
        if not node_id:
            continue
        source_table = str(node.get("source_table", ""))
        table = table_map.get(source_table) or table_map.get(
            source_table.rsplit(".", 1)[-1]
        ) or {}
        field_map = {}
        for column in table.get("columns") or []:
            if isinstance(column, dict):
                field_name = column.get("column_name")
                data_type = str(column.get("data_type", "")).lower()
            else:
                field_name = str(column)
                data_type = ""
            if not isinstance(field_name, str) or not field_name:
                continue
            semantic_type = "unknown"
            if any(token in data_type for token in ("int", "float", "double", "number")):
                semantic_type = "quantitative"
            elif any(token in data_type for token in ("date", "time")):
                semantic_type = "temporal"
            elif any(token in data_type for token in ("bool",)):
                semantic_type = "boolean"
            elif data_type:
                semantic_type = "categorical"
            field_map[field_name] = {
                "concept": _canonicalize_concept(field_name),
                "entity_scope": None,
                "description": f"Raw field '{field_name}' from {source_table or node_id}",
                "semantic_type": semantic_type,
                "unit": None,
                "source_fields": [{"node_id": node_id, "field": field_name}],
                "confidence": 0.5,
                "inferred_by": "schema_fallback"
            }
        catalog[node_id] = field_map
    return catalog


class DataAgent:
    """Data Agent - Generate and execute data processing code for D nodes"""

    def __init__(
        self,
        model_client: Optional[ModelClient] = None,
        project_dir: str = None
    ):
        """
        Initialize Data Agent

        Args:
            model_client: Model client instance
            project_dir: Project directory for storing intermediate tables
        """
        self.model_client = model_client or get_model_client()
        self.project_dir = project_dir

    def _check_code_syntax(self, code: str) -> Dict[str, Any]:
        """
        Check Python code for syntax errors before execution.

        Args:
            code: Python code string

        Returns:
            Dict: {valid: bool, error: str|None, error_type: str|None}
        """
        try:
            compile(code, "<generated_code>", "exec")
            return {"valid": True, "error": None, "error_type": None}
        except SyntaxError as e:
            return {
                "valid": False,
                "error": f"SyntaxError at line {e.lineno}: {e.msg}",
                "error_type": "syntax_error"
            }
        except Exception as e:
            return {
                "valid": False,
                "error": str(e),
                "error_type": "compile_error"
            }

    def _validate_result_dataframe(
        self, result_df: "pd.DataFrame"
    ) -> List[Dict[str, Any]]:
        """
        Validate the result DataFrame for illegal values (NaN, Inf, empty, etc.)

        Args:
            result_df: pandas DataFrame to validate

        Returns:
            List of issue dicts, each with {type, columns, count, detail}
        """
        import pandas as pd

        issues = []

        if result_df is None or len(result_df) == 0:
            issues.append({
                "type": "empty_result",
                "columns": [],
                "count": 0,
                "detail": "Result DataFrame is empty (0 rows)"
            })
            return issues

        for col in result_df.columns:
            col_data = result_df[col]

            nan_count = int(col_data.isna().sum())
            if nan_count > 0:
                issues.append({
                    "type": "nan_values",
                    "columns": [col],
                    "count": nan_count,
                    "detail": f"Column '{col}' has {nan_count} NaN/null values (out of {len(col_data)} rows)"
                })

            if pd.api.types.is_numeric_dtype(col_data):
                inf_mask = col_data.apply(lambda x: isinstance(x, (int, float)) and math.isinf(x))
                inf_count = int(inf_mask.sum())
                if inf_count > 0:
                    issues.append({
                        "type": "inf_values",
                        "columns": [col],
                        "count": inf_count,
                        "detail": f"Column '{col}' has {inf_count} Inf/-Inf values"
                    })

        return issues

    def _chat_json(self, user_prompt: str, temperature: float = 0.3) -> Dict[str, Any]:
        """
        Call the model and parse JSON output

        Args:
            user_prompt: User prompt
            temperature: Temperature parameter

        Returns:
            Dict: Parsed JSON object
        """
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_CHAT_JSON},
            {"role": "user", "content": user_prompt}
        ]

        response = self.model_client.chat(messages, temperature=temperature)
        content = response["content"]

        return self._extract_json(content)

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """
        Extract JSON object from text

        Args:
            text: Text that may contain JSON

        Returns:
            Dict: Parsed JSON object
        """
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

    def _extract_python_code(self, text: str) -> str:
        """
        Extract Python code from text (looking for ```python blocks)

        Args:
            text: Text that may contain Python code

        Returns:
            str: Extracted Python code
        """
        pattern = r"```python\s*([\s\S]*?)\s*```"
        matches = re.findall(pattern, text)
        if matches:
            return matches[-1].strip()

        pattern = r"```\s*([\s\S]*?)\s*```"
        matches = re.findall(pattern, text)
        if matches:
            return matches[-1].strip()

        return text.strip()

    def generate_processing_code(
        self,
        node: Dict[str, Any],
        input_nodes: List[Dict[str, Any]],
        input_table_paths: Dict[str, str],
        field_contract: Optional[Dict[str, Any]] = None
    ) -> tuple:
        """
        Generate Python code for a D node's data processing task

        Args:
            node: D node info (id, name, description, task)
            input_nodes: List of input node info (d or D nodes)
            input_table_paths: Dict mapping node id -> CSV file path

        Returns:
            tuple: (code: str, path_var_map: Dict[str, str])
                where path_var_map maps variable name -> file path
        """
        inputs_desc = []
        path_var_lines = []
        path_var_map = {}

        for inp in input_nodes:
            node_id = inp["id"]
            csv_path = input_table_paths.get(node_id, "")
            var_name = f"INPUT_TABLE_PATH_{node_id}"
            path_var_lines.append(f'{var_name} = r"{csv_path}"')
            path_var_map[var_name] = csv_path

            if csv_path and os.path.exists(csv_path):
                try:
                    import pandas as pd
                    df = pd.read_csv(csv_path, nrows=3)
                    columns = list(df.columns)
                    dtypes = {col: str(df[col].dtype) for col in columns}
                    inputs_desc.append({
                        "id": node_id,
                        "name": inp.get("name", node_id),
                        "path_variable": var_name,
                        "columns": columns,
                        "dtypes": dtypes,
                        "sample_rows": df.to_dict(orient="records")
                    })
                except Exception as e:
                    inputs_desc.append({
                        "id": node_id,
                        "name": inp.get("name", node_id),
                        "path_variable": var_name,
                        "error": str(e)
                    })
            else:
                inputs_desc.append({
                    "id": node_id,
                    "name": inp.get("name", node_id),
                    "path_variable": var_name,
                    "note": "File not found or path not provided"
                })

        inputs_json = json.dumps(inputs_desc, ensure_ascii=False, indent=2)
        path_variables_code = "\n".join(path_var_lines)

        prompt = PROCESSING_CODE_PROMPT.format(
            node_id=node["id"],
            node_name=node.get("name", ""),
            node_description=node.get("description", ""),
            node_task=node.get("task", ""),
            path_variables=path_variables_code,
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
        code = self._extract_python_code(response["content"])

        return code, path_var_map

    def execute_processing_code(
        self,
        code: str,
        output_path: str,
        path_variables: Dict[str, str] = None
    ) -> Dict[str, Any]:
        """
        Execute generated Python code and save the result as CSV.
        Includes syntax pre-check and result validation (NaN/Inf/empty).

        Args:
            code: Python code to execute
            output_path: Path to save the result CSV

        Returns:
            Dict: {
                success: bool,
                columns: [...],
                row_count: int,
                error: str|None,
                syntax_check: {valid, error, error_type},
                validation_issues: [{type, columns, count, detail}]
            }
        """
        syntax_check = self._check_code_syntax(code)
        if not syntax_check["valid"]:
            return {
                "success": False,
                "columns": [],
                "row_count": 0,
                "error": syntax_check["error"],
                "syntax_check": syntax_check,
                "validation_issues": []
            }

        try:
            import pandas as pd

            local_vars = {"pd": pd}

            if path_variables:
                for var_name, path in path_variables.items():
                    local_vars[var_name] = path

            exec(code, {"__builtins__": __builtins__, "pd": pd}, local_vars)

            if "result_df" not in local_vars:
                return {
                    "success": False,
                    "columns": [],
                    "row_count": 0,
                    "error": "Code did not produce a 'result_df' variable",
                    "syntax_check": syntax_check,
                    "validation_issues": []
                }

            result_df = local_vars["result_df"]

            if not isinstance(result_df, pd.DataFrame):
                return {
                    "success": False,
                    "columns": [],
                    "row_count": 0,
                    "error": f"result_df is not a DataFrame, got {type(result_df)}",
                    "syntax_check": syntax_check,
                    "validation_issues": []
                }

            validation_issues = self._validate_result_dataframe(result_df)

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            result_df.to_csv(output_path, index=False, encoding="utf-8-sig")

            columns_info = []
            for col in result_df.columns:
                col_dtype = str(result_df[col].dtype)
                col_info = {
                    "column_name": col,
                    "data_type": col_dtype,
                    "is_nullable": bool(result_df[col].isna().any()),
                    "is_primary_key": False
                }

                numeric_types = ("int", "float", "Int64", "Float64")
                if any(t in col_dtype.lower() for t in numeric_types):
                    non_null = result_df[col].dropna()
                    if len(non_null) > 0:
                        try:
                            col_info["value_range"] = {
                                "type": "numeric",
                                "min": float(non_null.min()),
                                "max": float(non_null.max())
                            }
                        except TypeError:
                            col_info["value_range"] = {"type": "numeric", "min": None, "max": None}
                    else:
                        col_info["value_range"] = {"type": "numeric", "min": None, "max": None}
                else:
                    try:
                        unique_vals = result_df[col].dropna().unique().tolist()
                        col_info["value_range"] = {
                            "type": "text",
                            "unique_count": len(unique_vals),
                            "sample_values": str(unique_vals)[:200]
                        }
                    except TypeError:
                        col_info["value_range"] = {
                            "type": "text",
                            "unique_count": 0,
                            "sample_values": []
                        }

                columns_info.append(col_info)

            return {
                "success": True,
                "columns": columns_info,
                "row_count": len(result_df),
                "syntax_check": syntax_check,
                "validation_issues": validation_issues
            }

        except Exception as e:
            tb = traceback.format_exc()
            return {
                "success": False,
                "columns": [],
                "row_count": 0,
                "error": str(e),
                "error_traceback": tb,
                "syntax_check": syntax_check,
                "validation_issues": []
            }

    def _build_error_context(
        self,
        node: Dict[str, Any],
        input_nodes: List[Dict[str, Any]],
        input_table_paths: Dict[str, str],
        execution_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Build structured error context for error_agent.

        Args:
            node: The D node being processed
            input_nodes: Input node list
            input_table_paths: Input CSV paths
            execution_result: Result from execute_processing_code

        Returns:
            Dict with formatted error info
        """
        return {
            "node": node,
            "input_nodes": input_nodes,
            "input_table_paths": input_table_paths,
            "execution_result": {
                "node_id": execution_result.get("node_id"),
                "success": execution_result.get("success"),
                "error": execution_result.get("error"),
                "error_traceback": execution_result.get("error_traceback"),
                "syntax_check": execution_result.get("syntax_check"),
                "validation_issues": execution_result.get("validation_issues", []),
                "columns": execution_result.get("columns"),
                "row_count": execution_result.get("row_count"),
                "output_path": execution_result.get("output_path")
            }
        }

    def infer_output_field_semantics(
        self,
        node: Dict[str, Any],
        code: str,
        output_path: str,
        columns: List[Dict[str, Any]],
        previous_semantics: Dict[str, Any]
    ) -> tuple:
        """Infer canonical semantics after the output table is successfully built."""
        output_fields = []
        for column in columns or []:
            value = (
                column.get("column_name")
                if isinstance(column, dict)
                else column
            )
            if isinstance(value, str) and value:
                output_fields.append(value)

        output_profile = {
            "columns": columns or [],
            "sample_rows": []
        }
        if output_path and os.path.isfile(output_path):
            try:
                import pandas as pd
                sample = pd.read_csv(output_path, nrows=5)
                output_profile["sample_rows"] = sample.to_dict(orient="records")
            except Exception as exc:
                output_profile["sample_error"] = str(exc)

        prompt = FIELD_SEMANTICS_PROMPT.format(
            node_id=node.get("id", ""),
            node_name=node.get("name", ""),
            node_description=node.get("description", ""),
            node_task=node.get("task", ""),
            code=code,
            previous_semantics_json=json.dumps(
                previous_semantics or {},
                ensure_ascii=False,
                indent=2,
                default=str
            ),
            output_profile_json=json.dumps(
                output_profile,
                ensure_ascii=False,
                indent=2,
                default=str
            )
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a data semantics and lineage expert. "
                    "Output only valid JSON."
                )
            },
            {"role": "user", "content": prompt}
        ]

        raw_response = ""
        error = None
        parsed_fields = {}
        try:
            response = self.model_client.chat(messages, temperature=0.2)
            raw_response = response["content"]
            parsed = self._extract_json(raw_response)
            if isinstance(parsed, dict):
                candidate = parsed.get("fields") or {}
                if isinstance(candidate, dict):
                    parsed_fields = candidate
        except Exception as exc:
            error = str(exc)

        normalized = {}
        for field_name in output_fields:
            candidate = parsed_fields.get(field_name) or {}
            if not isinstance(candidate, dict):
                candidate = {}
            concept = candidate.get("concept")
            if not isinstance(concept, str) or not concept.strip():
                concept = _canonicalize_concept(field_name)
            concept = _canonicalize_concept(concept)
            semantic_type = candidate.get("semantic_type", "unknown")
            if semantic_type not in {
                "categorical", "quantitative", "temporal", "identifier",
                "boolean", "text", "unknown"
            }:
                semantic_type = "unknown"
            source_fields = candidate.get("source_fields") or []
            if not isinstance(source_fields, list):
                source_fields = []
            source_fields = [
                item for item in source_fields
                if isinstance(item, dict)
                and isinstance(item.get("node_id"), str)
                and isinstance(item.get("field"), str)
            ]
            normalized[field_name] = {
                "concept": concept,
                "entity_scope": candidate.get("entity_scope"),
                "description": candidate.get("description")
                or f"Output field '{field_name}' of {node.get('id', '')}",
                "semantic_type": semantic_type,
                "unit": candidate.get("unit"),
                "source_fields": source_fields,
                "confidence": candidate.get("confidence", 0.5),
                "inferred_by": "llm" if field_name in parsed_fields else "fallback"
            }

        return normalized, {
            "success": bool(parsed_fields) and not error,
            "error": error,
            "raw_response": raw_response
        }

    def process_d_node(
        self,
        node: Dict[str, Any],
        input_nodes: List[Dict[str, Any]],
        input_table_paths: Dict[str, str],
        output_dir: str,
        field_semantics_catalog: Optional[Dict[str, Any]] = None,
        field_contract: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process a single D node: generate code, execute, save result.
        Validates output and reports errors to error_agent when issues are found.

        Args:
            node: D node dictionary
            input_nodes: List of input node info
            input_table_paths: Dict mapping node id -> CSV file path
            output_dir: Directory to save output CSV

        Returns:
            Dict: {
                node_id: str,
                code: str,
                output_path: str,
                columns: [...],
                row_count: int,
                success: bool,
                error: str|None,
                syntax_check: {valid, error, error_type},
                validation_issues: [{type, columns, count, detail}]
            }
        """
        node_id = node["id"]
        output_path = os.path.join(output_dir, f"{node_id}.csv")

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
        candidate_output_path = (
            output_path + ".candidate" if field_contract else output_path
        )

        try:
            code, path_var_map = self.generate_processing_code(
                node, input_nodes, input_table_paths, field_contract
            )
        except TypeError as exc:
            if "generate_processing_code" not in str(exc):
                raise
            code, path_var_map = self.generate_processing_code(
                node, input_nodes, input_table_paths
            )

        result = self.execute_processing_code(
            code, candidate_output_path, path_variables=path_var_map
        )

        def apply_output_quality(execution):
            if not execution.get("success"):
                return execution
            task_text = " ".join([
                str(node.get("name", "")),
                str(node.get("description", "")),
                str(node.get("task", ""))
            ]).lower()
            analytical_terms = (
                "performance", "effectiveness", "quality", "variance",
                "trend", "relationship", "correlation", "average",
                "distribution", "comparison"
            )
            if not any(term in task_text for term in analytical_terms):
                return execution
            numeric_columns = []
            for column in execution.get("columns") or []:
                if not isinstance(column, dict):
                    continue
                value_range = column.get("value_range") or {}
                if value_range.get("type") != "numeric":
                    continue
                name = str(column.get("column_name") or "")
                if any(token in name.lower() for token in ("_id", "index", "identifier")):
                    continue
                numeric_columns.append((name, value_range))
            if numeric_columns and all(
                item.get("min") == item.get("max")
                for _, item in numeric_columns
            ):
                issue = {
                    "type": "constant_analytical_output",
                    "columns": [name for name, _ in numeric_columns],
                    "count": len(numeric_columns),
                    "detail": (
                        f"{node_id} produced only constant analytical numeric "
                        f"fields: {[name for name, _ in numeric_columns]}. "
                        "This cannot support the requested comparison or relationship."
                    )
                }
                execution["validation_issues"] = (
                    list(execution.get("validation_issues") or []) + [issue]
                )
            return execution

        result = apply_output_quality(result)

        def apply_field_contract(execution, candidate_code):
            if not field_contract or not execution.get("success"):
                return execution
            from agents.planner_agent import PlannerAgent
            contract_issues = PlannerAgent.validate_artifact_contract(
                node_id,
                "D",
                {
                    "code": candidate_code,
                    "columns": execution.get("columns", [])
                },
                field_contract
            )
            if contract_issues:
                execution["validation_issues"] = (
                    list(execution.get("validation_issues") or [])
                    + contract_issues
                )
                execution["field_contract"] = field_contract
            return execution

        result = apply_field_contract(result, code)

        out = {
            "node_id": node_id,
            "node_type": "D",
            "code": code,
            "output_path": output_path if result.get("success") else None,
            "columns": result.get("columns", []),
            "row_count": result.get("row_count", 0),
            "success": result.get("success", False),
            "error": result.get("error"),
            "error_traceback": result.get("error_traceback"),
            "syntax_check": result.get("syntax_check"),
            "validation_issues": result.get("validation_issues", []),
            "source_tag": "data_generate"
        }

        has_issues = (
            not result.get("success", False)
            or len(result.get("validation_issues", [])) > 0
        )
        if has_issues:
            try:
                error_agent = get_error_agent(project_dir=self.project_dir)
                initial_result = dict(result)
                current_result = dict(result)
                current_code = code
                recovery_attempts = []
                analysis = None
                fix_result = None

                def is_clean(execution):
                    return bool(
                        execution.get("success")
                        and not (execution.get("validation_issues") or [])
                    )

                # Retry up to five times. Each failed regenerated result becomes
                # the next evidence packet for ErrorAgent diagnosis.
                for attempt_number in range(1, 6):
                    diagnosis_input = dict(current_result)
                    if recovery_attempts:
                        diagnosis_input["previous_recovery_attempts"] = [
                            {
                                "attempt": item.get("attempt"),
                                "status": item.get("status"),
                                "root_cause": (item.get("diagnosis") or {}).get("root_cause"),
                                "fix_strategy": (item.get("diagnosis") or {}).get("fix_strategy"),
                                "suggested_fixes": (item.get("diagnosis") or {}).get("suggested_fixes"),
                                "fix_error": (item.get("fix") or {}).get("error"),
                                "execution_error": (item.get("execution_result") or {}).get("error"),
                                "validation_issues": (item.get("execution_result") or {}).get("validation_issues", [])
                            }
                            for item in recovery_attempts
                        ]
                    diagnosis_started = time.perf_counter()
                    try:
                        analysis = error_agent.analyze_data_error(
                            node, current_code, input_nodes, input_table_paths, diagnosis_input
                        )
                    except Exception as exc:
                        analysis = {
                            "success": False,
                            "root_cause": "diagnosis_failure",
                            "explanation": str(exc),
                            "diagnosis_source": "exception"
                        }
                    diagnosis_duration_ms = int((time.perf_counter() - diagnosis_started) * 1000)

                    attempt = {
                        "attempt": attempt_number,
                        "input_code": current_code,
                        "input_execution_result": current_result,
                        "diagnosis": analysis,
                        "diagnosis_duration_ms": diagnosis_duration_ms,
                        "phase_timings": {
                            "diagnosis_ms": diagnosis_duration_ms
                        }
                    }
                    out["error_analysis"] = analysis

                    if not analysis.get("success"):
                        attempt["status"] = "diagnosis_failed"
                        recovery_attempts.append(attempt)
                        break

                    suggested_fixes = analysis.get("suggested_fixes") or {}
                    diagnosis_text = (
                        f"Root cause: {analysis.get('root_cause')}. "
                        f"Fix strategy: {analysis.get('fix_strategy')}. "
                        f"Evidence: {analysis.get('evidence', [])}. "
                        f"Explanation: {analysis.get('explanation', '')}. "
                        f"Code changes: {suggested_fixes.get('code_modifications', '')}. "
                        f"Data changes: {suggested_fixes.get('data_modifications', '')}. "
                        f"Previous failed attempts: {json.dumps(diagnosis_input.get('previous_recovery_attempts', []), ensure_ascii=False, default=str)}. "
                        "If a previous modification failed, choose a materially different repair strategy instead of repeating it."
                    )

                    regeneration_started = time.perf_counter()
                    try:
                        fix_result = error_agent.fix_data(
                            node,
                            current_code,
                            input_nodes,
                            input_table_paths,
                            current_result,
                            diagnosis_text
                        )
                    except Exception as exc:
                        fix_result = {
                            "success": False,
                            "code": current_code,
                            "error": str(exc)
                        }
                    fix_generation_duration_ms = int((time.perf_counter() - regeneration_started) * 1000)

                    attempt["fix"] = fix_result
                    attempt["fix_generation_duration_ms"] = fix_generation_duration_ms
                    attempt["phase_timings"]["fix_generation_ms"] = fix_generation_duration_ms
                    out["error_recovery"] = fix_result
                    fixed_code = fix_result.get("code")

                    if not fixed_code:
                        attempt["status"] = "fix_generation_failed"
                        attempt["regeneration_duration_ms"] = int((time.perf_counter() - regeneration_started) * 1000)
                        attempt["phase_timings"]["regeneration_ms"] = attempt["regeneration_duration_ms"]
                        recovery_attempts.append(attempt)
                        break

                    current_code = fixed_code
                    if not fix_result.get("success"):
                        current_result = {
                            "node_id": node_id,
                            "success": False,
                            "error": fix_result.get("error", "Generated fix was rejected"),
                            "syntax_check": fix_result.get("syntax_check"),
                            "validation_issues": []
                        }
                        attempt["execution_result"] = current_result
                        attempt["status"] = "fix_rejected"
                        attempt["regeneration_duration_ms"] = int((time.perf_counter() - regeneration_started) * 1000)
                        attempt["phase_timings"]["regeneration_ms"] = attempt["regeneration_duration_ms"]
                        recovery_attempts.append(attempt)
                        continue

                    execution_started = time.perf_counter()
                    current_result = self.execute_processing_code(
                        current_code,
                        candidate_output_path,
                        path_variables=path_var_map
                    )
                    current_result = apply_output_quality(current_result)
                    current_result = apply_field_contract(
                        current_result, current_code
                    )
                    execution_duration_ms = int((time.perf_counter() - execution_started) * 1000)
                    attempt["execution_result"] = current_result
                    attempt["execution_duration_ms"] = execution_duration_ms
                    attempt["regeneration_duration_ms"] = int((time.perf_counter() - regeneration_started) * 1000)
                    attempt["phase_timings"]["execution_ms"] = execution_duration_ms
                    attempt["phase_timings"]["regeneration_ms"] = attempt["regeneration_duration_ms"]
                    attempt["status"] = "recovered" if is_clean(current_result) else "retry_failed"
                    recovery_attempts.append(attempt)

                    if is_clean(current_result):
                        break

                recovered = is_clean(current_result)
                final_validation_issues = current_result.get("validation_issues") or []
                final_error = current_result.get("error")
                if not final_error and final_validation_issues:
                    final_error = "; ".join(
                        issue.get("detail", issue.get("type", "validation error"))
                        for issue in final_validation_issues
                    )

                out.update({
                    "code": current_code,
                    "output_path": output_path if recovered else None,
                    "columns": current_result.get("columns", []),
                    "row_count": current_result.get("row_count", 0),
                    "success": recovered,
                    "error": None if recovered else final_error,
                    "error_traceback": current_result.get("error_traceback"),
                    "syntax_check": current_result.get("syntax_check"),
                    "validation_issues": [] if recovered else final_validation_issues,
                    "recovered": recovered,
                    "recovery_attempts": recovery_attempts,
                    "original_error": initial_result.get("error"),
                    "original_error_traceback": initial_result.get("error_traceback"),
                    "original_validation_issues": initial_result.get("validation_issues", [])
                })

                error_context = self._build_error_context(
                    node, input_nodes, input_table_paths, current_result
                )
                error_context["original_execution_result"] = self._build_error_context(
                    node, input_nodes, input_table_paths, initial_result
                )["execution_result"]
                error_context["recovery_attempts"] = recovery_attempts
                error_result = error_agent.handle_error(
                    error_context, source_tag="data_generate",
                    analysis_result=analysis, fix_result=fix_result
                )
                out["error_report"] = error_result
            except Exception as exc:
                out["error_report"] = {
                    "error": "Failed to report to error_agent",
                    "detail": str(exc)
                }

        if field_contract:
            if out.get("success") and os.path.isfile(candidate_output_path):
                os.replace(candidate_output_path, output_path)
            elif os.path.isfile(candidate_output_path):
                os.remove(candidate_output_path)

        if out.get("success") and field_semantics_catalog is not None:
            semantics, semantic_status = self.infer_output_field_semantics(
                node,
                out.get("code", code),
                out.get("output_path", output_path),
                out.get("columns", []),
                field_semantics_catalog
            )
            out["field_semantics"] = semantics
            out["field_semantics_status"] = semantic_status

        return out


_data_agent: Optional[DataAgent] = None


def get_data_agent(project_dir: str = None) -> DataAgent:
    """Get or create the global Data Agent instance"""
    global _data_agent
    if _data_agent is None or _data_agent.project_dir != project_dir:
        _data_agent = DataAgent(project_dir=project_dir)
    return _data_agent


def init_data_agent(
    api_key: str = None,
    base_url: str = None,
    model_name: str = "qwen-turbo",
    project_dir: str = None
) -> DataAgent:
    """Initialize the global Data Agent"""
    global _data_agent
    from model import init_model_client

    init_model_client(api_key=api_key, base_url=base_url)
    _data_agent = DataAgent(
        model_client=get_model_client(),
        project_dir=project_dir
    )
    _data_agent.model_client.set_model(model_name)
    return _data_agent
