import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agents.data_agent import DataAgent
from agents.error_agent import ErrorAgent


class FakeModelClient:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error

    def chat(self, messages, temperature=0.3):
        if self.error:
            raise self.error
        return {"content": self.responses.pop(0)}


class StubDataAgent(DataAgent):
    def generate_processing_code(self, node, input_nodes, input_table_paths):
        code = (
            "import pandas as pd\n"
            "source_df = pd.read_csv(INPUT_TABLE_PATH_d1)\n"
            "result_df = source_df[['missing_column']]"
        )
        return code, {"INPUT_TABLE_PATH_d1": input_table_paths["d1"]}


class DataErrorRecoveryTests(unittest.TestCase):
    def test_output_field_semantics_use_canonical_concepts(self):
        response = json.dumps({
            "fields": {
                "argentina_formation": {
                    "concept": "formation",
                    "entity_scope": "Argentina",
                    "description": "Formation used by Argentina",
                    "semantic_type": "categorical",
                    "unit": None,
                    "source_fields": [{
                        "node_id": "d1",
                        "field": "formation_type"
                    }],
                    "confidence": 0.98
                },
                "brazil_formation": {
                    "concept": "formation",
                    "entity_scope": "Brazil",
                    "description": "Formation used by Brazil",
                    "semantic_type": "categorical",
                    "unit": None,
                    "source_fields": [{
                        "node_id": "d2",
                        "field": "formation_type"
                    }],
                    "confidence": 0.98
                }
            }
        })
        agent = DataAgent(model_client=FakeModelClient([response]))

        semantics, status = agent.infer_output_field_semantics(
            {
                "id": "D1",
                "name": "formation matchup",
                "task": "compare formations"
            },
            "result_df = merged",
            "",
            [
                {"column_name": "argentina_formation"},
                {"column_name": "brazil_formation"}
            ],
            {
                "d1": {"formation_type": {"concept": "formation"}},
                "d2": {"formation_type": {"concept": "formation"}}
            }
        )

        self.assertTrue(status["success"])
        self.assertEqual(
            "formation", semantics["argentina_formation"]["concept"]
        )
        self.assertEqual(
            "formation", semantics["brazil_formation"]["concept"]
        )
        self.assertNotEqual(
            semantics["argentina_formation"]["entity_scope"],
            semantics["brazil_formation"]["entity_scope"]
        )

    def test_local_diagnosis_survives_model_failure(self):
        agent = ErrorAgent(model_client=FakeModelClient(error=RuntimeError("offline")))
        result = agent.analyze_data_error(
            {"id": "D1", "name": "test", "task": "select a value column"},
            "result_df = source_df[['missing_column']]",
            [],
            {},
            {
                "success": False,
                "error": "KeyError: \"['missing_column'] not in index\"",
                "syntax_check": {"valid": True},
                "validation_issues": []
            }
        )

        self.assertTrue(result["success"])
        self.assertEqual("column_name", result["root_cause"])
        self.assertEqual("local_fallback", result["diagnosis_source"])
        self.assertIn("offline", result["llm_error"])

    def test_fix_data_normalizes_legacy_output_variable(self):
        response = json.dumps({
            "code": "import pandas as pd\nD1_result = pd.DataFrame({'value': [1]})",
            "metadata": {"output_columns": ["value"]}
        })
        agent = ErrorAgent(model_client=FakeModelClient([response]))
        result = agent.fix_data(
            {"id": "D1", "name": "test"},
            "broken code",
            [],
            {},
            {"success": False, "error": "missing result_df"},
            "Assign the final frame to result_df."
        )

        self.assertTrue(result["success"])
        self.assertIn("result_df = D1_result", result["code"])
        compile(result["code"], "<test_fix>", "exec")

    def test_recovery_record_contains_original_error_and_diagnosis(self):
        diagnosis_response = json.dumps({
            "root_cause": "column_name",
            "fix_strategy": "modify_code",
            "suggested_fixes": {
                "code_modifications": "Use the existing value column.",
                "data_modifications": None
            },
            "evidence": ["missing_column is absent; value is available"],
            "explanation": "The generated code selected a non-existent field."
        })
        fix_response = json.dumps({
            "code": (
                "import pandas as pd\n"
                "source_df = pd.read_csv(INPUT_TABLE_PATH_d1)\n"
                "result_df = source_df[['value']].copy()"
            ),
            "metadata": {
                "used_tables": ["d1"],
                "used_fields": ["value"],
                "output_columns": ["value"]
            }
        })

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = os.path.join(temp_dir, "input.csv")
            Path(input_path).write_text("value\n1\n2\n", encoding="utf-8")
            error_agent = ErrorAgent(
                model_client=FakeModelClient([diagnosis_response, fix_response]),
                project_dir=temp_dir
            )
            data_agent = StubDataAgent(
                model_client=error_agent.model_client,
                project_dir=temp_dir
            )

            with patch("agents.data_agent.get_error_agent", return_value=error_agent):
                result = data_agent.process_d_node(
                    {"id": "D1", "name": "select value", "task": "select value"},
                    [{"id": "d1", "name": "input"}],
                    {"d1": input_path},
                    os.path.join(temp_dir, "data_tables")
                )

            self.assertTrue(result["success"])
            self.assertTrue(result["recovered"])
            self.assertEqual(1, len(result["recovery_attempts"]))

            record_path = result["error_report"]["record_path"]
            with open(record_path, "r", encoding="utf-8") as record_file:
                record = json.load(record_file)

            self.assertIn("missing_column", record["original_error"]["error"])
            self.assertEqual("column_name", record["diagnosis"]["root_cause"])
            self.assertEqual(1, record["recovery_status"]["attempt_count"])
            self.assertTrue(record["recovery_status"]["recovered"])
            self.assertEqual("recovered", record["recovery_attempts"][0]["status"])
            self.assertIn("result_df", record["fix"]["fixed_code"])

    def test_second_attempt_uses_new_execution_error(self):
        first_diagnosis = json.dumps({
            "root_cause": "column_name",
            "fix_strategy": "modify_code",
            "suggested_fixes": {"code_modifications": "Use value.", "data_modifications": None},
            "evidence": ["missing_column is absent"],
            "explanation": "Wrong column."
        })
        first_fix = json.dumps({
            "code": (
                "import pandas as pd\n"
                "source_df = pd.read_csv(INPUT_TABLE_PATH_d1)\n"
                "result_df = source_df.assign(ratio=1 / 0)"
            )
        })
        second_diagnosis = json.dumps({
            "root_cause": "runtime_error",
            "fix_strategy": "modify_code",
            "suggested_fixes": {
                "code_modifications": "Remove the zero divisor.",
                "data_modifications": None
            },
            "evidence": ["ZeroDivisionError"],
            "explanation": "The first repair introduced division by zero."
        })
        second_fix = json.dumps({
            "code": (
                "import pandas as pd\n"
                "source_df = pd.read_csv(INPUT_TABLE_PATH_d1)\n"
                "result_df = source_df.assign(ratio=1)"
            )
        })

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = os.path.join(temp_dir, "input.csv")
            Path(input_path).write_text("value\n1\n2\n", encoding="utf-8")
            error_agent = ErrorAgent(
                model_client=FakeModelClient([
                    first_diagnosis, first_fix, second_diagnosis, second_fix
                ]),
                project_dir=temp_dir
            )
            data_agent = StubDataAgent(
                model_client=error_agent.model_client,
                project_dir=temp_dir
            )

            with patch("agents.data_agent.get_error_agent", return_value=error_agent):
                result = data_agent.process_d_node(
                    {"id": "D1", "name": "select value", "task": "select value"},
                    [{"id": "d1", "name": "input"}],
                    {"d1": input_path},
                    os.path.join(temp_dir, "data_tables")
                )

            self.assertTrue(result["recovered"])
            self.assertEqual(2, len(result["recovery_attempts"]))
            self.assertEqual("retry_failed", result["recovery_attempts"][0]["status"])
            self.assertIn(
                "division by zero",
                result["recovery_attempts"][1]["input_execution_result"]["error"]
            )
            self.assertEqual("recovered", result["recovery_attempts"][1]["status"])


if __name__ == "__main__":
    unittest.main()
