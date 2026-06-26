"""
Data Agent - Agent responsible for generating and executing data processing code
for D (data processing) nodes in the dependency graph.
"""

import os
import json
import re
import math
import traceback
from typing import List, Dict, Any, Optional
from model import get_model_client, ModelClient
from agents.error_agent import get_error_agent
from prompts.data_agent_prompts import (
    SYSTEM_PROMPT_CHAT_JSON,
    SYSTEM_PROMPT_GENERATE,
    PROCESSING_CODE_PROMPT
)


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
        input_table_paths: Dict[str, str]
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
            inputs_json=inputs_json
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
                        col_info["value_range"] = {
                            "type": "numeric",
                            "min": float(non_null.min()),
                            "max": float(non_null.max())
                        }
                    else:
                        col_info["value_range"] = {"type": "numeric", "min": None, "max": None}
                else:
                    unique_vals = result_df[col].dropna().unique().tolist()
                    col_info["value_range"] = {
                        "type": "text",
                        "unique_count": len(unique_vals),
                        "sample_values": unique_vals[:20]
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

    def process_d_node(
        self,
        node: Dict[str, Any],
        input_nodes: List[Dict[str, Any]],
        input_table_paths: Dict[str, str],
        output_dir: str
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

        code, path_var_map = self.generate_processing_code(node, input_nodes, input_table_paths)

        result = self.execute_processing_code(code, output_path, path_variables=path_var_map)

        out = {
            "node_id": node_id,
            "node_type": "D",
            "code": code,
            "output_path": output_path if result.get("success") else None,
            "columns": result.get("columns", []),
            "row_count": result.get("row_count", 0),
            "success": result.get("success", False),
            "error": result.get("error"),
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
                error_context = self._build_error_context(
                    node, input_nodes, input_table_paths, out
                )
                error_result = error_agent.handle_error(error_context, source_tag="data_generate")
                out["error_report"] = error_result
            except Exception:
                out["error_report"] = {"error": "Failed to report to error_agent"}

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
