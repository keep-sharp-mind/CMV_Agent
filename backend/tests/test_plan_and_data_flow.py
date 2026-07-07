import sys
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agents.plan_agent import PlanAgent
from agents.planner_agent import PlannerAgent
from agents.interaction_agent import InteractionAgent
from agents.vis_agent import VisAgent
import app as backend_app


class PlanDependencyValidationTests(unittest.TestCase):
    def setUp(self):
        self.agent = PlanAgent(model_client=object())
        self.nodes = {
            "d": [{"id": "d1"}],
            "D": [{"id": "D1"}, {"id": "D2"}],
            "V": [{"id": "V1"}, {"id": "V2"}],
            "I": [{"id": "I1"}]
        }

    def test_d_node_with_only_outgoing_edge_is_rejected(self):
        dependencies = [
            {"from": "d1", "to": "D1", "type": "d->D"},
            {"from": "D1", "to": "V1", "type": "D->V"},
            {"from": "D2", "to": "V2", "type": "D->V"},
            {"from": "V1", "to": "I1", "type": "V->I"},
            {"from": "I1", "to": "V2", "type": "I->V"}
        ]

        errors = self.agent._validate_dependencies(self.nodes, dependencies)

        self.assertTrue(any(
            error["rule"] == "non_d_has_predecessor"
            and error["nodes"] == ["D2"]
            for error in errors
        ))

    def test_valid_graph_satisfies_all_predecessor_contracts(self):
        dependencies = [
            {"from": "d1", "to": "D1", "type": "d->D"},
            {"from": "d1", "to": "D2", "type": "d->D"},
            {"from": "D1", "to": "V1", "type": "D->V"},
            {"from": "D2", "to": "V2", "type": "D->V"},
            {"from": "V1", "to": "I1", "type": "V->I"},
            {"from": "I1", "to": "V2", "type": "I->V"}
        ]

        self.assertEqual(
            [],
            self.agent._validate_dependencies(self.nodes, dependencies)
        )

    def test_invalid_edge_type_and_unknown_endpoint_are_reported(self):
        dependencies = [
            {"from": "d1", "to": "D1", "type": "D->D"},
            {"from": "missing", "to": "D2", "type": "d->D"}
        ]

        errors = self.agent._validate_dependencies(self.nodes, dependencies)
        rules = {error["rule"] for error in errors}

        self.assertIn("edge_type_matches_nodes", rules)
        self.assertIn("known_edge_endpoints", rules)

    def test_unavailable_metric_task_is_rejected(self):
        nodes = {
            "d": [{"id": "d1"}],
            "D": [{
                "id": "D1",
                "task": "Calculate performance metrics not provided in the input table"
            }],
            "V": [{"id": "V1"}],
            "I": []
        }
        dependencies = [
            {"from": "d1", "to": "D1", "type": "d->D"},
            {"from": "D1", "to": "V1", "type": "D->V"}
        ]

        errors = self.agent._validate_dependencies(nodes, dependencies)

        self.assertTrue(any(
            error["rule"] == "data_feasibility" for error in errors
        ))


class PlannerDataFlowTests(unittest.TestCase):
    def test_transitive_predecessor_fields_are_collected(self):
        plan = {
            "nodes": {
                "d": [{
                    "id": "d1",
                    "name": "source",
                    "source_table": "demo.source"
                }],
                "D": [
                    {"id": "D1", "task": "aggregate score by team"},
                    {"id": "D2", "task": "calculate ratio from team totals"}
                ],
                "V": [{"id": "V1"}, {"id": "V2"}],
                "I": [{"id": "I1"}]
            },
            "dependencies": [
                {"from": "d1", "to": "D1", "type": "d->D"},
                {"from": "D1", "to": "D2", "type": "D->D"},
                {"from": "D2", "to": "V1", "type": "D->V"},
                {"from": "D2", "to": "V2", "type": "D->V"},
                {"from": "V1", "to": "I1", "type": "V->I"},
                {"from": "I1", "to": "V2", "type": "I->V"}
            ]
        }
        schema = [{
            "db_name": "demo",
            "tables": [{
                "table_name": "source",
                "columns": [
                    {"column_name": "team"},
                    {"column_name": "score"},
                    {"column_name": "unused"}
                ]
            }]
        }]
        processed_nodes = {
            "D1": {
                "code": (
                    "source = pd.read_csv(INPUT_TABLE_PATH_d1)\n"
                    "result_df = source.groupby('team')['score'].sum()"
                ),
                "columns": [
                    {"column_name": "team"},
                    {"column_name": "total"}
                ]
            },
            "D2": {
                "code": (
                    "totals = pd.read_csv(INPUT_TABLE_PATH_D1)\n"
                    "result_df = totals[['team', 'total']].copy()\n"
                    "result_df['ratio'] = result_df['total'] / result_df['total'].sum()"
                ),
                "columns": [
                    {"column_name": "team"},
                    {"column_name": "ratio"}
                ]
            }
        }
        processed_vis = {
            "V1": {
                "metadata": {"used_fields": ["team"]},
                "spec": {
                    "layer": [{
                        "mark": "bar",
                        "encoding": {
                            "x": {"field": "team"},
                            "y": {"field": "ratio"}
                        }
                    }],
                    "transform": [{
                        "calculate": "datum.ratio * 100",
                        "as": "percentage"
                    }]
                }
            },
            "V2": {
                "spec": {
                    "mark": "point",
                    "encoding": {
                        "x": {"field": "team"},
                        "y": {"field": "ratio"}
                    }
                }
            }
        }

        flow = PlannerAgent().analyze_data_flow(
            plan, schema, processed_vis, processed_nodes
        )

        self.assertEqual(
            ["d1.score", "d1.team"],
            flow["D1"]["direct_in_fields"]
        )
        self.assertNotIn("d1.unused", flow["D1"]["in_fields"])
        self.assertEqual(
            {"D1": ["team", "total"]},
            flow["D2"]["predecessor_fields"]
        )
        self.assertEqual(
            {"D1": ["team", "total"], "d1": ["score", "team"]},
            flow["D2"]["ancestor_fields"]
        )
        self.assertTrue({
            "D2.ratio",
            "D2.team",
            "D1.total",
            "D1.team",
            "d1.score",
            "d1.team"
        }.issubset(set(flow["V1"]["transitive_in_fields"])))
        self.assertEqual(
            ["D2.ratio", "D2.team"],
            flow["V1"]["in_fields"]
        )
        self.assertEqual(["D2", "I1"], flow["V2"]["predecessors"])
        self.assertTrue({"V1", "D2", "D1", "d1"}.issubset(
            set(flow["I1"]["ancestors"])
        ))

    def test_nested_vega_fields_are_extracted(self):
        fields = PlannerAgent._get_v_required_fields("V1", {
            "V1": {
                "spec": {
                    "facet": {"field": "region"},
                    "spec": {
                        "transform": [
                            {"filter": "datum['score'] > 0"},
                            {"aggregate": [{"op": "sum", "field": "value"}],
                             "groupby": ["team"]}
                        ],
                        "encoding": {"x": {"field": "date"}}
                    }
                }
            }
        })

        self.assertEqual(
            {"region", "score", "value", "team", "date"},
            fields
        )

    def test_multi_input_d_edges_are_analyzed_independently(self):
        plan = {
            "nodes": {
                "d": [
                    {"id": "d1", "source_table": "demo.left"},
                    {"id": "d2", "source_table": "demo.right"}
                ],
                "D": [{"id": "D1"}],
                "V": [{"id": "V1"}],
                "I": []
            },
            "dependencies": [
                {"from": "d1", "to": "D1", "type": "d->D"},
                {"from": "d2", "to": "D1", "type": "d->D"},
                {"from": "D1", "to": "V1", "type": "D->V"}
            ]
        }
        schema = [{
            "db_name": "demo",
            "tables": [
                {"table_name": "left", "columns": [
                    {"column_name": "id"},
                    {"column_name": "left_value"},
                    {"column_name": "left_unused"}
                ]},
                {"table_name": "right", "columns": [
                    {"column_name": "id"},
                    {"column_name": "right_value"},
                    {"column_name": "right_unused"}
                ]}
            ]
        }]
        processed_nodes = {
            "D1": {
                "code": (
                    "left = pd.read_csv(INPUT_TABLE_PATH_d1)\n"
                    "right = pd.read_csv(INPUT_TABLE_PATH_d2)\n"
                    "merged = pd.merge(left, right, on='id')\n"
                    "result_df = merged[['left_value', 'right_value']]"
                ),
                "columns": [
                    {"column_name": "left_value"},
                    {"column_name": "right_value"}
                ]
            }
        }
        processed_vis = {
            "V1": {
                "spec": {"encoding": {
                    "x": {"field": "left_value"},
                    "y": {"field": "right_value"}
                }}
            }
        }

        flow = PlannerAgent().analyze_data_flow(
            plan, schema, processed_vis, processed_nodes
        )

        self.assertEqual(["id", "left_value"], flow["d1"]["out_fields"])
        self.assertEqual(["id", "right_value"], flow["d2"]["out_fields"])
        self.assertEqual(
            ["d1.id", "d1.left_value", "d2.id", "d2.right_value"],
            flow["D1"]["in_fields"]
        )
        self.assertEqual(
            ["left_value", "right_value"],
            flow["D1"]["out_fields"]
        )
        self.assertEqual(
            ["D1.left_value", "D1.right_value"],
            flow["V1"]["in_fields"]
        )

    def test_generated_code_recovers_undeclared_predecessor_fields(self):
        plan = {
            "nodes": {
                "d": [{"id": "d1", "source_table": "demo.source"}],
                "D": [{"id": "D1", "task": "select team and score"}],
                "V": [],
                "I": []
            },
            "dependencies": []
        }
        schema = [{
            "db_name": "demo",
            "tables": [{
                "table_name": "source",
                "columns": [
                    {"column_name": "team"},
                    {"column_name": "score"},
                    {"column_name": "unused"}
                ]
            }]
        }]
        processed_nodes = {
            "D1": {
                "code": (
                    "source = pd.read_csv(INPUT_TABLE_PATH_d1)\n"
                    "result_df = source[['team', 'score']]"
                ),
                "columns": [{"column_name": "team"}, {"column_name": "score"}]
            }
        }

        flow = PlannerAgent().analyze_data_flow(
            plan, schema, {}, processed_nodes
        )

        self.assertEqual([], flow["D1"]["predecessors"])
        self.assertEqual(["d1"], flow["D1"]["undeclared_predecessors"])
        self.assertEqual([], flow["D1"]["in_fields"])

    def test_list_shaped_column_names_are_flattened(self):
        plan = {
            "nodes": {
                "d": [{"id": "d1", "source_table": "demo.source"}],
                "D": [{"id": "D1", "task": "select fields"}],
                "V": [],
                "I": []
            },
            "dependencies": [
                {"from": "d1", "to": "D1", "type": "d->D"}
            ]
        }
        schema = [{
            "db_name": "demo",
            "tables": [{
                "table_name": "source",
                "columns": [{"column_name": ["team", "score"]}]
            }]
        }]
        processed_nodes = {
            "D1": {
                "code": (
                    "source = pd.read_csv(INPUT_TABLE_PATH_d1)\n"
                    "result_df = source[['team', 'score']]"
                ),
                "columns": [{"column_name": ["team", "score"]}]
            }
        }

        flow = PlannerAgent().analyze_data_flow(
            plan, schema, {}, processed_nodes
        )

        self.assertEqual([], flow["D1"]["out_fields"])
        self.assertEqual(
            ["d1.score", "d1.team"],
            flow["D1"]["in_fields"]
        )
        self.assertEqual(["score", "team"], flow["d1"]["out_fields"])

    def test_interaction_uses_explicit_link_and_controlled_fields(self):
        plan = {
            "nodes": {
                "d": [{"id": "d1", "source_table": "demo.source"}],
                "D": [{"id": "D1"}],
                "V": [{"id": "V1"}, {"id": "V2"}],
                "I": [{"id": "I1"}]
            },
            "dependencies": [
                {"from": "d1", "to": "D1", "type": "d->D"},
                {"from": "D1", "to": "V1", "type": "D->V"},
                {"from": "D1", "to": "V2", "type": "D->V"},
                {"from": "V1", "to": "I1", "type": "V->I"},
                {"from": "I1", "to": "V2", "type": "I->V"}
            ]
        }
        schema = [{
            "db_name": "demo",
            "tables": [{
                "table_name": "source",
                "columns": [
                    {"column_name": "team"},
                    {"column_name": "score"}
                ]
            }]
        }]
        processed_nodes = {
            "D1": {
                "code": (
                    "source = pd.read_csv(INPUT_TABLE_PATH_d1)\n"
                    "result_df = source[['team', 'score']]"
                ),
                "columns": [
                    {"column_name": "team"},
                    {"column_name": "score"}
                ]
            }
        }
        processed_vis = {
            "V1": {
                "spec": {
                    "encoding": {
                        "x": {"field": "team"},
                        "y": {"field": "score"}
                    }
                }
            },
            "V2": [{
                "encoding": {
                    "x": {"field": "team"},
                    "y": {"field": "score"}
                }
            }]
        }
        interactions = {
            "I1": {
                "interaction_spec": {
                    "source_views": [{
                        "id": "V1",
                        "link_field": ["team"],
                        "source_channels": ["x"]
                    }],
                    "controlled_view": [{
                        "view": "V2",
                        "field": "team",
                        "action": "filter"
                    }]
                }
            }
        }

        flow = PlannerAgent().analyze_data_flow(
            plan,
            schema,
            processed_vis,
            processed_nodes,
            interactions
        )

        self.assertEqual(["V1.team"], flow["I1"]["direct_in_fields"])
        self.assertIn("I1.team", flow["V2"]["direct_in_fields"])
        self.assertEqual(["team"], flow["I1"]["out_fields"])
        self.assertEqual(["score", "team"], flow["D1"]["out_fields"])
        self.assertEqual(["team"], flow["V1"]["out_fields"])
        self.assertEqual([], flow["V2"]["out_fields"])

        # Every edge field must appear on both endpoints: unqualified on the
        # predecessor and qualified on the successor.
        for source_id, source_flow in flow.items():
            for edge in source_flow["outgoing_edges"]:
                target_flow = flow[edge["to"]]
                for field in edge["fields"]:
                    self.assertIn(field, source_flow["out_fields"])
                    self.assertIn(
                        f"{source_id}.{field}",
                        target_flow["in_fields"]
                    )

    def test_v_to_i_fields_wait_for_interaction_artifact(self):
        plan = {
            "nodes": {
                "d": [{"id": "d1", "source_table": "demo.source"}],
                "D": [{"id": "D1"}],
                "V": [{"id": "V1"}, {"id": "V2"}],
                "I": [{"id": "I1"}]
            },
            "dependencies": [
                {"from": "d1", "to": "D1", "type": "d->D"},
                {"from": "D1", "to": "V1", "type": "D->V"},
                {"from": "D1", "to": "V2", "type": "D->V"},
                {"from": "V1", "to": "I1", "type": "V->I"},
                {"from": "I1", "to": "V2", "type": "I->V"}
            ]
        }
        schema = [{
            "db_name": "demo",
            "tables": [{
                "table_name": "source",
                "columns": [{"column_name": "team"}, {"column_name": "score"}]
            }]
        }]
        processed_nodes = {
            "D1": {
                "code": "result_df = pd.read_csv(INPUT_TABLE_PATH_d1)[['team', 'score']]",
                "columns": [{"column_name": "team"}, {"column_name": "score"}]
            }
        }
        processed_vis = {
            "V1": {"spec": {"encoding": {"x": {"field": "team"}}}},
            "V2": {"spec": {"encoding": {"x": {"field": "team"}}}}
        }

        flow = PlannerAgent().analyze_data_flow(
            plan, schema, processed_vis, processed_nodes, interaction_results={}
        )

        self.assertEqual([], flow["V1"]["out_fields"])
        self.assertEqual([], flow["I1"]["in_fields"])
        self.assertEqual([], flow["I1"]["out_fields"])
        self.assertEqual(["team"], flow["V1"]["predicted_out_fields"])
        self.assertEqual(["V1.team"], flow["I1"]["predicted_in_fields"])
        self.assertEqual(["team"], flow["I1"]["predicted_out_fields"])


class SaveDataFlowIntegrationTests(unittest.TestCase):
    def test_save_data_flow_accepts_list_vis_and_interaction_artifact(self):
        plan = {
            "nodes": {
                "d": [{"id": "d1", "source_table": "demo.source"}],
                "D": [{"id": "D1"}],
                "V": [{"id": "V1"}, {"id": "V2"}],
                "I": [{"id": "I1"}]
            },
            "dependencies": [
                {"from": "d1", "to": "D1", "type": "d->D"},
                {"from": "D1", "to": "V1", "type": "D->V"},
                {"from": "D1", "to": "V2", "type": "D->V"},
                {"from": "V1", "to": "I1", "type": "V->I"},
                {"from": "I1", "to": "V2", "type": "I->V"}
            ]
        }
        schema = [{
            "db_name": "demo",
            "tables": [{
                "table_name": "source",
                "columns": [{"column_name": ["team", "score"]}]
            }]
        }]
        data_result = {
            "processed_nodes": {
                "D1": {
                    "code": (
                        "source = pd.read_csv(INPUT_TABLE_PATH_d1)\n"
                        "result_df = source[['team', 'score']]"
                    ),
                    "columns": [{"column_name": ["team", "score"]}]
                }
            },
            "processed_vis": []
        }
        vis_result = {
            "processed_vis": [
                {
                    "node_id": "V1",
                    "spec": {"encoding": {
                        "x": {"field": "team"},
                        "y": {"field": "score"}
                    }}
                },
                {
                    "node_id": "V2",
                    "spec": {"encoding": {
                        "x": {"field": "team"},
                        "y": {"field": "score"}
                    }}
                }
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            interaction_dir = os.path.join(temp_dir, "interactions")
            os.makedirs(interaction_dir)
            Path(os.path.join(interaction_dir, "I1.json")).write_text(
                json.dumps({
                    "interaction_spec": {
                        "source_views": [{
                            "id": "V1",
                            "link_field": ["team"]
                        }],
                        "controlled_view": [{
                            "view": "V2",
                            "field": ["team"]
                        }]
                    }
                }),
                encoding="utf-8"
            )

            class FakeProjectStore:
                def __init__(self):
                    self.saved = {}

                def load_project_file(self, project_id, filename):
                    return {
                        "data_result.json": data_result,
                        "vis_result.json": vis_result
                    }.get(filename)

                def get_project_path(self, project_id, filename=None):
                    return (
                        os.path.join(temp_dir, filename)
                        if filename else temp_dir
                    )

                def save_project_file(self, project_id, filename, content):
                    self.saved[filename] = content

            store = FakeProjectStore()
            with patch.object(backend_app, "_build_db_schema", return_value=schema):
                flow = backend_app._save_data_flow(store, "project-1", plan)

            self.assertIn("I1.team", flow["V2"]["direct_in_fields"])
            self.assertEqual(["V1.team"], flow["I1"]["direct_in_fields"])
            self.assertEqual(flow, store.saved["data_flow.json"])


class InteractionFieldContractTests(unittest.TestCase):
    def test_default_data_urls_use_the_flask_csv_route(self):
        interaction_agent = InteractionAgent(model_client=object())
        vis_agent = VisAgent(model_client=object())
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DATA_SERVICE_URL", None)
            urls = interaction_agent._build_view_data_urls(
                {"V1": {"metadata": {"used_tables": ["D1"]}}},
                {"D1": "ignored.csv"},
                "project-1"
            )
            spec = vis_agent.convert_view_spec(
                "V1",
                {"table": "D1", "mark": "bar", "encoding": {}},
                "project-1",
                {"D1": "ignored.csv"},
                {"used_tables": ["D1"]}
            )

        expected = "http://localhost:5000/data/project-1/D1.csv"
        self.assertEqual(expected, urls["V1"])
        self.assertEqual(expected, spec["data"]["url"])

    def test_multiple_interactions_do_not_rewrap_shared_target(self):
        class FailingModel:
            def chat(self, messages, temperature=0.1):
                raise RuntimeError("force deterministic fallback")

        agent = InteractionAgent(model_client=FailingModel())
        plan = {
            "nodes": {"I": [
                {"id": "I1", "trigger": "select", "effect": "filter"},
                {"id": "I2", "trigger": "select", "effect": "filter"}
            ]},
            "dependencies": [
                {"from": "V1", "to": "I1", "type": "V->I"},
                {"from": "I1", "to": "V3", "type": "I->V"},
                {"from": "V2", "to": "I2", "type": "V->I"},
                {"from": "I2", "to": "V3", "type": "I->V"}
            ]
        }
        views = {
            view_id: {
                "spec": {
                    "mark": "bar",
                    "encoding": {"x": {"field": "team"}}
                }
            }
            for view_id in ("V1", "V2", "V3")
        }

        result = agent.process_interactions(plan, views)
        target = result["processed_vis"]["V3"]["spec"]

        self.assertTrue(result["interaction_results"]["I1"]["success"])
        self.assertTrue(result["interaction_results"]["I2"]["success"])
        self.assertEqual({"bg_V3", "fg_V3"}, set(target["datasets"]))
        self.assertEqual(2, len(target["layer"]))
        self.assertEqual(
            "team", target["layer"][0]["encoding"]["x"]["field"]
        )

    def test_invalid_model_spec_falls_back_before_mutating_views(self):
        class InvalidSpecModel:
            def chat(self, messages, temperature=0.1):
                return {"content": json.dumps({
                    "source_views": [{
                        "id": "V9",
                        "select": "point",
                        "source_channels": ["x"],
                        "link_field": "missing"
                    }],
                    "controlled_view": [{
                        "view": "V9",
                        "field": "missing",
                        "action": "filter"
                    }]
                })}

        agent = InteractionAgent(model_client=InvalidSpecModel())
        plan = {
            "nodes": {"I": [{
                "id": "I1", "trigger": "select", "effect": "filter"
            }]},
            "dependencies": [
                {"from": "V1", "to": "I1", "type": "V->I"},
                {"from": "I1", "to": "V2", "type": "I->V"}
            ]
        }
        views = {
            "V1": {"spec": {
                "mark": "bar", "encoding": {"x": {"field": "team"}}
            }},
            "V2": {"spec": {
                "mark": "bar", "encoding": {"x": {"field": "team"}}
            }}
        }

        result = agent.process_interactions(plan, views)
        interaction = result["interaction_results"]["I1"]

        self.assertTrue(interaction["success"])
        self.assertTrue(interaction["fallback_used"])
        self.assertEqual(
            "V1", interaction["interaction_spec"]["source_views"][0]["id"]
        )
        self.assertEqual(
            "V2", interaction["interaction_spec"]["controlled_view"][0]["view"]
        )
        self.assertNotIn("layer", views["V2"]["spec"])
        self.assertEqual(
            "team",
            result["processed_vis"]["V2"]["spec"]["layer"][0]
            ["encoding"]["x"]["field"]
        )

    def test_correct_model_spec_is_converted_to_runtime_artifacts(self):
        class SpecModel:
            def chat(self, messages, temperature=0.1):
                return {"content": json.dumps({
                    "source_views": [{
                        "id": "V1",
                        "select": "point",
                        "source_channels": ["x"],
                        "link_field": "argentina_formation",
                        "semantic": "formation"
                    }],
                    "controlled_view": [{
                        "view": "V2",
                        "field": "brazil_formation",
                        "action": "filter",
                        "semantic": "formation"
                    }]
                })}

        agent = InteractionAgent(model_client=SpecModel())
        plan = {
            "nodes": {"I": [{
                "id": "I1",
                "description": "Link formations",
                "trigger": "select",
                "effect": "filter"
            }]},
            "dependencies": [
                {"from": "V1", "to": "I1", "type": "V->I"},
                {"from": "I1", "to": "V2", "type": "I->V"}
            ]
        }
        views = {
            "V1": {
                "metadata": {"used_tables": ["D1"]},
                "spec": {
                    "mark": "bar",
                    "encoding": {"x": {"field": "argentina_formation"}}
                }
            },
            "V2": {
                "metadata": {"used_tables": ["D2"]},
                "spec": {
                    "mark": "bar",
                    "encoding": {"x": {"field": "brazil_formation"}}
                }
            }
        }
        semantics = {
            "D1": {"argentina_formation": {
                "concept": "formation", "semantic_type": "categorical"
            }},
            "D2": {"brazil_formation": {
                "concept": "formation", "semantic_type": "categorical"
            }}
        }

        result = agent.process_interactions(
            plan, views, field_semantics=semantics
        )
        interaction = result["interaction_results"]["I1"]
        source_spec = result["processed_vis"]["V1"]["spec"]
        target_spec = result["processed_vis"]["V2"]["spec"]

        self.assertTrue(interaction["success"])
        self.assertNotIn("validation_issues", interaction)
        self.assertEqual("sel_I1", interaction["signal_slots"]["V1"])
        self.assertEqual("sel_I1", source_spec["params"][0]["name"])
        self.assertEqual(["x"], source_spec["params"][0]["select"]["encodings"])
        self.assertEqual(
            "sel_I1",
            source_spec["encoding"]["opacity"]["condition"]["param"]
        )
        self.assertEqual(2, len(target_spec["layer"]))
        self.assertIn("bg_V2", target_spec["datasets"])
        self.assertIn("fg_V2", target_spec["datasets"])
        self.assertIn("sv.semantic || f", interaction["js_code"])
        self.assertIn("cv.semantic || linkF", interaction["js_code"])

    def test_semantically_related_different_field_names_can_link(self):
        class FailingModel:
            def chat(self, messages, temperature=0.1):
                raise RuntimeError("force fallback")

        agent = InteractionAgent(model_client=FailingModel())
        views = {
            "V1": {
                "metadata": {"used_tables": ["D1"]},
                "spec": {"encoding": {
                    "x": {"field": "argentina_formation"}
                }}
            },
            "V2": {
                "metadata": {"used_tables": ["D2"]},
                "spec": {"encoding": {
                    "x": {"field": "brazil_formation"}
                }}
            }
        }
        semantics = {
            "D1": {
                "argentina_formation": {
                    "concept": "formation",
                    "entity_scope": "Argentina",
                    "semantic_type": "categorical"
                }
            },
            "D2": {
                "brazil_formation": {
                    "concept": "formation",
                    "entity_scope": "Brazil",
                    "semantic_type": "categorical"
                }
            }
        }

        spec = agent._build_interaction_spec(
            "I1",
            "select",
            "filter",
            "point",
            ["V1"],
            ["V2"],
            views,
            i_node={"id": "I1", "description": "link team formations"},
            field_semantics=semantics
        )
        validation = agent._validate_interaction_result(
            spec,
            "valid js",
            views,
            ["V1"],
            ["V2"],
            semantics
        )
        js_code = agent.generate_js_interaction(spec, {}, "I1")

        self.assertTrue(validation["valid"], validation)
        self.assertEqual(
            "argentina_formation",
            spec["source_views"][0]["link_field"]
        )
        self.assertEqual(
            "brazil_formation",
            spec["controlled_view"][0]["field"]
        )
        self.assertEqual("formation", spec["source_views"][0]["semantic"])
        self.assertEqual("formation", spec["controlled_view"][0]["semantic"])
        self.assertIn("semanticKey", js_code)

    def test_fallback_uses_shared_field_for_both_interaction_edges(self):
        class FailingModel:
            def chat(self, messages, temperature=0.1):
                raise RuntimeError("force fallback")

        agent = InteractionAgent(model_client=FailingModel())
        views = {
            "V1": {"spec": {"encoding": {
                "x": {"field": "score"},
                "color": {"field": "team"}
            }}},
            "V2": {"spec": {"encoding": {
                "x": {"field": "region"},
                "color": {"field": "team"}
            }}}
        }

        spec = agent._build_interaction_spec(
            "I1",
            "select",
            "filter",
            "point",
            ["V1"],
            ["V2"],
            views,
            i_node={"id": "I1", "description": "link by team"}
        )

        self.assertEqual("team", spec["source_views"][0]["link_field"])
        self.assertEqual(["color"], spec["source_views"][0]["source_channels"])
        self.assertEqual("team", spec["controlled_view"][0]["field"])
        validation = agent._validate_interaction_result(
            spec, "valid js", views, ["V1"], ["V2"]
        )
        self.assertTrue(validation["valid"], validation)

    def test_validation_rejects_mismatched_edge_fields(self):
        agent = InteractionAgent(model_client=object())
        views = {
            "V1": {"spec": {"encoding": {"x": {"field": "team"}}}},
            "V2": {"spec": {"encoding": {"x": {"field": "region"}}}}
        }
        spec = {
            "source_views": [{
                "id": "V1",
                "select": "point",
                "source_channels": ["x"],
                "link_field": "team"
            }],
            "controlled_view": [{
                "view": "V2",
                "field": "region",
                "action": "filter"
            }]
        }

        validation = agent._validate_interaction_result(
            spec, "valid js", views, ["V1"], ["V2"]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(
            issue["type"] == "link_field_mismatch"
            for issue in validation["issues"]
        ))


class FieldContractTests(unittest.TestCase):
    def setUp(self):
        self.flow = {
            "D1": {
                "predecessor_fields": {"d1": ["country", "value"]},
                "out_fields": ["country", "total"],
                "incoming_edges": [{"from": "d1", "to": "D1", "type": "d->D"}],
                "outgoing_edges": [{"from": "D1", "to": "V1", "type": "D->V", "fields": ["country", "total"]}]
            },
            "V1": {
                "predecessor_fields": {"D1": ["country", "total"]},
                "out_fields": ["country"],
                "incoming_edges": [{"from": "D1", "to": "V1", "type": "D->V"}],
                "outgoing_edges": [{"from": "V1", "to": "I1", "type": "V->I", "fields": ["country"]}]
            }
        }

    def test_d_contract_rejects_cascade_break(self):
        contract = PlannerAgent.build_node_contract(self.flow, "D1")
        issues = PlannerAgent.validate_artifact_contract(
            "D1",
            "D",
            {
                "code": '# INPUT_FIELDS: {"d1": ["country"], "D9": ["x"]}',
                "columns": [{"column_name": "country"}]
            },
            contract
        )
        details = " ".join(issue["detail"] for issue in issues)
        self.assertIn("undeclared predecessors", details)
        self.assertIn("value", details)
        self.assertIn("total", details)

    def test_v_contract_accepts_compatible_regeneration(self):
        contract = PlannerAgent.build_node_contract(self.flow, "V1")
        issues = PlannerAgent.validate_artifact_contract(
            "V1",
            "V",
            {
                "metadata": {
                    "used_tables": ["D1"],
                    "used_fields": ["country", "total"],
                    "input_fields_by_table": {
                        "D1": ["country", "total"]
                    }
                }
            },
            contract
        )
        self.assertEqual([], issues)


class VisualizationLayoutTests(unittest.TestCase):
    def test_quantitative_axis_uses_observed_domain_with_padding(self):
        spec = {
            "mark": "point",
            "encoding": {
                "x": {"field": "score", "type": "quantitative"}
            }
        }

        VisAgent._apply_quantitative_axis_domains(
            spec,
            {"score": {"min": 88.0, "max": 97.0}}
        )

        scale = spec["encoding"]["x"]["scale"]
        self.assertFalse(scale["zero"])
        self.assertAlmostEqual(87.55, scale["domain"][0])
        self.assertAlmostEqual(97.45, scale["domain"][1])

    def test_aggregate_axis_keeps_vega_lite_auto_domain(self):
        spec = {
            "mark": "bar",
            "encoding": {
                "y": {
                    "field": "score",
                    "type": "quantitative",
                    "aggregate": "mean"
                }
            }
        }

        VisAgent._apply_quantitative_axis_domains(
            spec,
            {"score": {"min": 88.0, "max": 97.0}}
        )

        self.assertNotIn("scale", spec["encoding"]["y"])

    def test_constant_quantitative_axis_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "D5.csv")
            Path(path).write_text(
                "formation_type,average_performance_outcome\n"
                "4-4-2,1\n4-2-4,1\n3-4-3,1\n",
                encoding="utf-8"
            )
            validation = VisAgent(model_client=object()).validate_visualization(
                {
                    "mark": "point",
                    "encoding": {
                        "x": {"field": "formation_type", "type": "nominal"},
                        "y": {
                            "field": "average_performance_outcome",
                            "type": "quantitative"
                        }
                    }
                },
                {
                    "marktype": "point",
                    "used_tables": ["D5"],
                    "used_fields": [
                        "formation_type", "average_performance_outcome"
                    ],
                    "encoding_fields": {
                        "x": "formation_type",
                        "y": "average_performance_outcome"
                    }
                },
                {"D5": path}
            )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(
            issue["type"] == "constant_quantitative_axis"
            for issue in validation["issues"]
        ))


if __name__ == "__main__":
    unittest.main()
