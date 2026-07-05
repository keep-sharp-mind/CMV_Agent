"""
Interaction Agent - Converts model-generated interaction specs (I nodes)
into working chart interactions. For each I node:
  1) Modifies source V Vega-Lite specs with selection params
  2) Modifies target V Vega-Lite specs into dual-layer (background + foreground)
  3) Generates frontend JS interaction code
"""

import json
import copy
import os
import re
from typing import List, Dict, Any, Optional

from model import get_model_client, ModelClient
from prompts.interaction_agent_prompts import BUILD_INTERACTION_SPEC_PROMPT


class InteractionAgent:
    """Process I (interaction) nodes to create interactive V charts."""

    def __init__(
        self,
        model_client: Optional[ModelClient] = None,
        project_dir: str = None
    ):
        """
        Args:
            model_client: Model client instance for LLM calls.
            project_dir: Project directory for file persistence.
        """
        self.model_client = model_client or get_model_client()
        self.project_dir = project_dir

    def process_interactions(
        self,
        plan_data: Dict[str, Any],
        processed_vis: Dict[str, Any],
        all_table_paths: Dict[str, str] = None,
        project_id: str = "",
        field_semantics: Dict[str, Any] = None,
        field_contracts: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Entry-point: process all I nodes and return updated vis + interaction code.

        Returns:
            {
                "processed_vis": { v_id: {spec, spec_json, ...} },  # specs modified in-place
                "interaction_results": { i_id: {interaction_spec, js_code, ...} }
            }
        """
        nodes = plan_data.get("nodes", {})
        deps = plan_data.get("dependencies", [])
        i_nodes = nodes.get("I", [])
        field_semantics = (
            field_semantics if isinstance(field_semantics, dict) else {}
        )
        if field_contracts is None and self.project_dir:
            try:
                contract_path = os.path.join(
                    self.project_dir, "data_flow_contract.json"
                )
                with open(contract_path, "r", encoding="utf-8") as file:
                    field_contracts = json.load(file)
            except (OSError, json.JSONDecodeError):
                field_contracts = {}
        field_contracts = (
            field_contracts if isinstance(field_contracts, dict) else {}
        )
        if not i_nodes:
            return {"processed_vis": processed_vis, "interaction_results": {}}

        # Group V->I and I->V edges per I node
        i_sources = {i["id"]: [] for i in i_nodes}
        i_targets = {i["id"]: [] for i in i_nodes}
        for dep in deps:
            t = dep.get("type", "")
            if t == "V->I" and dep["to"] in i_sources:
                i_sources[dep["to"]].append(dep["from"])
            elif t == "I->V" and dep["from"] in i_targets:
                i_targets[dep["from"]].append(dep["to"])

        view_data_urls = self._build_view_data_urls(processed_vis, all_table_paths or {}, project_id)
        validation_vis = copy.deepcopy(processed_vis)
        updated_vis = copy.deepcopy(processed_vis)
        interaction_results = {}

        for i_node in i_nodes:
            i_id = i_node["id"]
            from agents.planner_agent import PlannerAgent
            field_contract = PlannerAgent.build_node_contract(
                field_contracts, i_id
            )

            def apply_field_contract(validation_result, candidate_spec):
                contract_issues = PlannerAgent.validate_artifact_contract(
                    i_id,
                    "I",
                    {"interaction_spec": candidate_spec},
                    field_contract
                )
                if not contract_issues:
                    return validation_result
                updated = dict(validation_result)
                updated["valid"] = False
                updated["issues"] = (
                    list(updated.get("issues") or []) + contract_issues
                )
                updated["error"] = contract_issues[0]["detail"]
                return updated

            trigger = i_node.get("trigger", "select")
            effect = i_node.get("effect", "filter")
            select_type = "point" if trigger == "select" else "interval"
            sv_ids = i_sources.get(i_id, [])
            tv_ids = i_targets.get(i_id, [])
            if not field_contract:
                field_contract = {
                    "node_id": i_id,
                    "required_inputs": {},
                    "required_outputs": [],
                    "allowed_predecessors": list(sv_ids),
                    "incoming_edges": [
                        {"from": source, "to": i_id, "type": "V->I"}
                        for source in sv_ids
                    ],
                    "outgoing_edges": [
                        {"from": i_id, "to": target, "type": "I->V"}
                        for target in tv_ids
                    ]
                }
            if not sv_ids:
                continue

            spec = self._build_interaction_spec(
                i_id,
                trigger,
                effect,
                select_type,
                sv_ids,
                tv_ids,
                validation_vis,
                i_node=i_node,
                field_semantics=field_semantics,
                field_contract=field_contract
            )

            js = self.generate_js_interaction(spec, view_data_urls, i_id)
            model_validation = self._validate_interaction_result(
                spec, js, validation_vis, sv_ids, tv_ids, field_semantics
            )
            model_validation = apply_field_contract(model_validation, spec)
            fallback_used = False
            if not model_validation.get("valid"):
                spec = self._build_interaction_spec(
                    i_id,
                    trigger,
                    effect,
                    select_type,
                    sv_ids,
                    tv_ids,
                    validation_vis,
                    i_node=None,
                    field_semantics=field_semantics,
                    field_contract=field_contract
                )
                js = self.generate_js_interaction(
                    spec, view_data_urls, i_id
                )
                validation = self._validate_interaction_result(
                    spec,
                    js,
                    validation_vis,
                    sv_ids,
                    tv_ids,
                    field_semantics
                )
                validation = apply_field_contract(validation, spec)
                fallback_used = True
            else:
                validation = model_validation

            # Invalid I-Specs must never mutate otherwise valid chart specs.
            if validation.get("valid"):
                # 1) Add source selections.
                for vid in sv_ids:
                    vis = updated_vis.get(vid)
                    if vis and vis.get("spec"):
                        mod = self.modify_vega_code_source(
                            copy.deepcopy(vis["spec"]), i_id, spec, vid
                        )
                        vis["spec"] = mod
                        vis["spec_json"] = json.dumps(
                            mod, indent=2, ensure_ascii=False
                        )

                # 2) Convert each target once to stable shared datasets.
                for vid in tv_ids:
                    vis = updated_vis.get(vid)
                    if vis and vis.get("spec"):
                        mod = self.modify_vega_code_target(
                            copy.deepcopy(vis["spec"]),
                            i_id,
                            spec,
                            tv_id=vid
                        )
                        vis["spec"] = mod
                        vis["spec_json"] = json.dumps(
                            mod, indent=2, ensure_ascii=False
                        )

            # 4) Build V-id → signal-slot mapping for the frontend
            signal_slots = {}
            for vid in sv_ids:
                signal_slots[vid] = f"sel_{i_id}"

            result = {
                "interaction_spec": spec,
                "js_code": js,
                "success": validation.get("valid", False),
                "source_v_ids": sv_ids,
                "target_v_ids": tv_ids,
                "signal_slots": signal_slots
            }
            if fallback_used:
                result["fallback_used"] = True
                result["model_validation_issues"] = model_validation.get(
                    "issues", []
                )

            # Validate and attempt error recovery
            if not validation.get("valid"):
                result["validation_issues"] = validation.get("issues", [])
                result["error"] = validation.get("error", "")
                analysis = None
                fix = None
                try:
                    from agents.error_agent import get_error_agent
                    ea = get_error_agent(project_dir=self.project_dir)
                    analysis = ea.analyze_interaction_error(
                        i_node, spec, js,
                        {v: updated_vis[v] for v in sv_ids if v in updated_vis},
                        {v: updated_vis[v] for v in tv_ids if v in updated_vis},
                        {"error": validation.get("error", ""), "validation_issues": validation.get("issues", [])}
                    )
                    result["error_analysis"] = analysis
                    if analysis.get("success"):
                        fix = ea.fix_interaction(
                            i_node, spec, js,
                            {v: updated_vis[v] for v in sv_ids if v in updated_vis},
                            {v: updated_vis[v] for v in tv_ids if v in updated_vis},
                            {"error": validation.get("error", ""), "validation_issues": validation.get("issues", [])},
                            f"Root cause: {analysis.get('root_cause')}. Fix: {analysis.get('suggested_fixes', {}).get('interaction_modifications', '')}",
                            available_fields=", ".join(self._encoding_fields(updated_vis.get(v, {}).get("spec", {})) for v in sv_ids if v in updated_vis)
                        )
                        result["error_recovery"] = fix
                        if fix.get("success") and fix.get("interaction_spec"):
                            fixed_spec = self._enrich_interaction_semantics(
                                fix["interaction_spec"],
                                updated_vis,
                                field_semantics
                            )
                            fixed_validation = self._validate_interaction_result(
                                fixed_spec,
                                "regenerated",
                                updated_vis,
                                sv_ids,
                                tv_ids,
                                field_semantics
                            )
                            fixed_validation = apply_field_contract(
                                fixed_validation, fixed_spec
                            )
                            result["recovery_validation"] = fixed_validation
                            if fixed_validation.get("valid"):
                                spec = fixed_spec
                                result["interaction_spec"] = spec
                                result["js_code"] = self.generate_js_interaction(
                                    spec, view_data_urls, i_id
                                )
                                result["recovered"] = True
                except Exception:
                    result["error_recovery"] = {"error": "Failed to attempt auto-recovery"}

                # Save error record with diagnosis and fix
                try:
                    from agents.error_agent import get_error_agent
                    ea2 = get_error_agent(project_dir=self.project_dir)
                    err_ctx = {
                        "node": i_node,
                        "execution_result": {
                            "error": result.get("error", ""),
                            "validation_issues": result.get("validation_issues", []),
                            "success": result.get("success", False)
                        }
                    }
                    ea2.handle_error(
                        err_ctx, source_tag="interaction_generate",
                        analysis_result=analysis, fix_result=fix
                    )
                except Exception:
                    pass

            interaction_results[i_id] = result

            # Persist per-interaction-node result to interactions/{i_id}.json
            if self.project_dir:
                import os
                i_dir = os.path.join(self.project_dir, "interactions")
                os.makedirs(i_dir, exist_ok=True)
                i_path = os.path.join(i_dir, f"{i_id}.json")
                try:
                    with open(i_path, "w", encoding="utf-8") as f:
                        json.dump(result, f, indent=2, ensure_ascii=False)
                except Exception:
                    pass

        return {
            "processed_vis": updated_vis,
            "interaction_results": interaction_results,
            "view_data_urls": view_data_urls
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_view_field_semantics(
        self,
        view_id: str,
        field: str,
        processed_vis: Dict[str, Any],
        field_semantics: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Resolve semantic records for one field rendered by a view."""
        if not field:
            return []
        view = processed_vis.get(view_id) or {}
        if not isinstance(view, dict):
            view = {}
        metadata = view.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        table_ids = metadata.get("used_tables") or []
        if not isinstance(table_ids, list):
            table_ids = []

        records = []
        search_ids = table_ids or list(field_semantics)
        for node_id in search_ids:
            node_fields = field_semantics.get(node_id) or {}
            if not isinstance(node_fields, dict):
                continue
            semantic = node_fields.get(field)
            if not isinstance(semantic, dict):
                continue
            record = {
                "node_id": node_id,
                "field": field,
                **semantic
            }
            records.append(record)
        return records

    def _view_fields_by_concept(
        self,
        view_id: str,
        processed_vis: Dict[str, Any],
        field_semantics: Dict[str, Any]
    ) -> Dict[str, List[str]]:
        """Map canonical semantic concepts to encoding fields in one view."""
        view = processed_vis.get(view_id) or {}
        spec = view.get("spec", {}) if isinstance(view, dict) else {}
        mapping: Dict[str, List[str]] = {}
        for field in self._encoding_fields(spec):
            for record in self._resolve_view_field_semantics(
                view_id, field, processed_vis, field_semantics
            ):
                concept = record.get("concept")
                if isinstance(concept, str) and concept:
                    mapping.setdefault(concept, [])
                    if field not in mapping[concept]:
                        mapping[concept].append(field)
        return mapping

    def _first_field_concept(
        self,
        view_id: str,
        field: str,
        processed_vis: Dict[str, Any],
        field_semantics: Dict[str, Any]
    ) -> str:
        records = self._resolve_view_field_semantics(
            view_id, field, processed_vis, field_semantics
        )
        concepts = [
            record.get("concept") for record in records
            if isinstance(record.get("concept"), str)
            and record.get("concept")
        ]
        return concepts[0] if concepts else ""

    def _enrich_interaction_semantics(
        self,
        spec: Dict[str, Any],
        processed_vis: Dict[str, Any],
        field_semantics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Fill missing semantic labels without changing chosen fields."""
        for source in spec.get("source_views") or []:
            if not isinstance(source, dict) or source.get("semantic"):
                continue
            source["semantic"] = self._first_field_concept(
                source.get("id", ""),
                source.get("link_field", ""),
                processed_vis,
                field_semantics
            )
        for target in spec.get("controlled_view") or []:
            if not isinstance(target, dict) or target.get("semantic"):
                continue
            target["semantic"] = self._first_field_concept(
                target.get("view", ""),
                target.get("field", ""),
                processed_vis,
                field_semantics
            )
        return spec

    def _build_view_specs_json(
        self,
        updated_vis: Dict[str, Any],
        field_semantics: Dict[str, Any] = None
    ) -> str:
        """Build a condensed view-specs JSON for the LLM prompt."""
        summaries = []
        field_semantics = field_semantics or {}
        for v_id, v_data in updated_vis.items():
            spec = v_data.get("spec", {})
            mark = spec.get("mark", "")
            if isinstance(mark, dict):
                mark = mark.get("type", "")
            meta = v_data.get("metadata", {})
            enc_summary = {}
            for channel, field in self._encoding_pairs(spec):
                enc_summary[channel] = {
                    "field": field,
                    "semantics": self._resolve_view_field_semantics(
                        v_id,
                        field,
                        updated_vis,
                        field_semantics
                    )
                }
            summaries.append({
                "id": v_id,
                "mark": mark or meta.get("marktype", ""),
                "encoding_channels": enc_summary
            })
        return json.dumps(summaries, indent=2, ensure_ascii=False)

    def _build_interaction_requirement(self, i_node: Dict[str, Any]) -> str:
        """Build a natural language description of the interaction requirement."""
        parts = [f"I-Node: {i_node.get('id', '')}"]
        name = i_node.get("name", "")
        if name:
            parts.append(f"Name: {name}")
        desc = i_node.get("description", "")
        if desc:
            parts.append(f"Description: {desc}")
        trigger = i_node.get("trigger", "select")
        effect = i_node.get("effect", "filter")
        parts.append(f"Trigger: {trigger} ({'point click' if trigger == 'select' else 'interval brush'})")
        parts.append(f"Effect on target: {effect}")
        return "\n".join(parts)

    def _build_interaction_spec(
        self,
        i_id,
        trigger,
        effect,
        select_type,
        sv_ids,
        tv_ids,
        updated_vis,
        i_node=None,
        field_semantics=None,
        field_contract=None
    ):
        """
        Generate interaction spec using LLM, with hardcoded fallback.
        """
        llm_spec = None
        view_specs_json = ""
        requirement_text = ""

        if i_node:
            view_specs_json = self._build_view_specs_json(
                updated_vis, field_semantics
            )
            requirement_text = self._build_interaction_requirement(i_node)
            if field_contract:
                requirement_text += (
                    "\n\nStable field contract (must be preserved):\n"
                    + json.dumps(field_contract, ensure_ascii=False, indent=2)
                )
            prompt = BUILD_INTERACTION_SPEC_PROMPT.format(
                view_specs_json=view_specs_json,
                interaction_requirement=requirement_text
            )
            try:
                messages = [
                    {"role": "system", "content": "You are an interaction design engineer for coordinated multi-view systems. Output only valid JSON."},
                    {"role": "user", "content": prompt}
                ]
                response = self.model_client.chat(messages, temperature=0.1)
                raw = response["content"]
                parsed = self._extract_json(raw)
                source_views = parsed.get("source_views") if parsed else None
                controlled_views = (
                    parsed.get("controlled_view") if parsed else None
                )
                if (
                    isinstance(source_views, list)
                    and isinstance(controlled_views, list)
                    and all(isinstance(item, dict) for item in source_views)
                    and all(isinstance(item, dict) for item in controlled_views)
                ):
                    llm_spec = parsed
            except Exception:
                pass

        if llm_spec:
            spec = {
                "interaction_id": i_id, "trigger": trigger, "effect": effect,
                "select_type": select_type,
                "source_views": llm_spec.get("source_views", []),
                "controlled_view": llm_spec.get("controlled_view", []),
                "_llm_generated": True
            }
            return self._enrich_interaction_semantics(
                spec, updated_vis, field_semantics or {}
            )

        # Fallback: hardcoded extraction from encoding
        source_field_orders = {
            vid: self._encoding_fields(
                updated_vis.get(vid, {}).get("spec", {})
            )
            for vid in sv_ids
        }
        target_field_orders = {
            vid: self._encoding_fields(
                updated_vis.get(vid, {}).get("spec", {})
            )
            for vid in tv_ids
        }
        view_ids = list(sv_ids) + list(tv_ids)
        semantic_fields = {
            view_id: self._view_fields_by_concept(
                view_id, updated_vis, field_semantics or {}
            )
            for view_id in view_ids
        }
        participating_concepts = [
            set(mapping)
            for mapping in semantic_fields.values()
            if mapping
        ]
        common_concepts = (
            set.intersection(*participating_concepts)
            if participating_concepts else set()
        )
        chosen_concept = ""
        if sv_ids and common_concepts:
            first_semantics = semantic_fields.get(sv_ids[0], {})
            chosen_concept = next(
                (
                    concept for field in source_field_orders.get(sv_ids[0], [])
                    for concept, fields in first_semantics.items()
                    if concept in common_concepts and field in fields
                ),
                sorted(common_concepts)[0]
            )

        participating_fields = [
            set(fields)
            for fields in list(source_field_orders.values())
            + list(target_field_orders.values())
            if fields
        ]
        common_fields = (
            set.intersection(*participating_fields)
            if participating_fields else set()
        )
        first_source_order = (
            source_field_orders.get(sv_ids[0], []) if sv_ids else []
        )
        shared_link_field = next(
            (field for field in first_source_order if field in common_fields),
            ""
        )

        source_views = []
        for vid in sv_ids:
            s = updated_vis.get(vid, {}).get("spec", {})
            pairs = self._encoding_pairs(s)
            fields = [f for ch, f in pairs]
            semantic_match = (
                semantic_fields.get(vid, {}).get(chosen_concept, [])
                if chosen_concept else []
            )
            link_field = (
                next(
                    (field for field in fields if field in semantic_match),
                    ""
                )
                or shared_link_field
                or next((field for field in fields if field in common_fields), "")
                or (fields[0] if fields else "")
            )
            source_channels = [
                channel for channel, field in pairs if field == link_field
            ] or [channel for channel, _field in pairs]
            source_views.append({
                "id": vid,
                "select": select_type,
                "source_channels": source_channels,
                "link_field": link_field,
                "semantic": chosen_concept or self._first_field_concept(
                    vid, link_field, updated_vis, field_semantics or {}
                )
            })
        controlled_view = []
        for vid in tv_ids:
            target_fields = target_field_orders.get(vid, [])
            semantic_match = (
                semantic_fields.get(vid, {}).get(chosen_concept, [])
                if chosen_concept else []
            )
            target_field = (
                next(
                    (field for field in target_fields if field in semantic_match),
                    ""
                )
                or shared_link_field
                or next(
                    (field for field in target_fields if field in common_fields),
                    ""
                )
                or (target_fields[0] if target_fields else "")
            )
            controlled_view.append({
                "view": vid,
                "field": target_field,
                "action": effect,
                "semantic": chosen_concept or self._first_field_concept(
                    vid, target_field, updated_vis, field_semantics or {}
                )
            })
        spec = {
            "interaction_id": i_id, "trigger": trigger, "effect": effect,
            "select_type": select_type, "source_views": source_views,
            "controlled_view": controlled_view
        }
        return self._enrich_interaction_semantics(
            spec, updated_vis, field_semantics or {}
        )

    def modify_vega_code_source(
        self,
        spec: Dict,
        i_id: str,
        interaction_spec: Dict,
        source_view_id: str = ""
    ) -> Dict:
        """Add a Vega-Lite selection parameter + opacity condition for the interaction."""
        sel_name = f"sel_{i_id}"
        stype = interaction_spec.get("select_type", "point")

        param = {"name": sel_name, "select": {"type": stype}}
        source_config = next((
            item for item in interaction_spec.get("source_views", [])
            if isinstance(item, dict)
            and (not source_view_id or item.get("id") == source_view_id)
        ), {})
        source_channels = source_config.get("source_channels") or []
        if source_channels:
            param["select"]["encodings"] = source_channels
        if stype == "point":
            param["select"]["on"] = "click"

        spec.setdefault("params", []).append(param)

        def add_selection_opacity(unit_spec: Dict[str, Any]) -> None:
            enc = unit_spec.setdefault("encoding", {})
            if "opacity" not in enc:
                enc["opacity"] = {
                    "condition": {"param": sel_name, "value": 1},
                    "value": 0.3
                }

        if isinstance(spec.get("layer"), list):
            for layer in spec["layer"]:
                if isinstance(layer, dict):
                    add_selection_opacity(layer)
        else:
            add_selection_opacity(spec)
        return spec

    def modify_vega_code_target(self, spec: Dict, i_id: str, interaction_spec: Dict, tv_id: str = "") -> Dict:
        """Restructure target spec into dual-layer (bg + fg) with named datasets."""
        suffix = tv_id or i_id
        bg_data = f"bg_{suffix}"
        fg_data = f"fg_{suffix}"
        if bg_data in spec.get("datasets", {}) and fg_data in spec.get(
            "datasets", {}
        ):
            return spec

        mark = spec.get("mark", {})
        if isinstance(mark, str):
            mark = {"type": mark}
        encoding = spec.get("encoding", {})

        bg_mark = {**mark, "opacity": 0.3}
        fg_mark = {**mark}

        layer_spec = {
            "$schema": spec.get("$schema", "https://vega.github.io/schema/vega-lite/v5.json"),
            "title": spec.get("title"),
            "config": spec.get("config"),
            "datasets": {bg_data: [], fg_data: []},
            "layer": [
                {"data": {"name": bg_data}, "mark": bg_mark, "encoding": encoding,
                 "width": spec.get("width"), "height": spec.get("height")},
                {"data": {"name": fg_data}, "mark": fg_mark, "encoding": encoding,
                 "width": spec.get("width"), "height": spec.get("height")}
            ]
        }
        # Keep params if any (includes global selection defs from source modification)
        if spec.get("params"):
            layer_spec["params"] = spec["params"]
        return layer_spec

    def generate_js_interaction(self, interaction_spec: Dict, view_data_urls: Dict[str, str], i_id: str) -> str:
        """Generate self-contained frontend JS to be injected at runtime."""
        sv = interaction_spec.get("source_views", [])
        cv = interaction_spec.get("controlled_view", [])

        src_views_json = json.dumps([
            {"id": s.get("id", ""), "select": s.get("select", "point"),
             "source_channels": s.get("source_channels", []),
             "link_field": s.get("link_field", ""),
             "semantic": s.get("semantic", "")} for s in sv
        ])
        ctrl_views_json = json.dumps([
            {"view": c.get("view", ""), "field": c.get("field", ""),
             "action": c.get("action", "filter"),
             "semantic": c.get("semantic", "")} for c in cv
        ])

        return f"""(function() {{
  var IID = '{i_id}';
  var srcViews = {src_views_json};
  var ctrlViews = {ctrl_views_json};

  function extractPointValues(raw, field) {{
    var values = [];
    function visit(value, acceptScalar) {{
      if (value == null) return;
      if (Array.isArray(value)) {{
        value.forEach(function(item) {{ visit(item, acceptScalar); }});
        return;
      }}
      if (typeof value === 'object') {{
        if (Object.prototype.hasOwnProperty.call(value, field)) {{
          visit(value[field], true);
        }} else {{
          Object.keys(value).forEach(function(key) {{
            visit(value[key], false);
          }});
        }}
        return;
      }}
      if (acceptScalar) values.push(String(value));
    }}
    visit(raw, Array.isArray(raw));
    return values.filter(function(v, i, a) {{ return a.indexOf(v) === i; }});
  }}

  function process() {{
    var selMap = {{}};
    var hasSel = false;

    srcViews.forEach(function(sv) {{
      var raw = window['I_Data_' + IID + '_' + sv.id];
      if (raw == null) return;
      hasSel = true;
      var f = sv.link_field;
      if (!f) return;
      var semanticKey = sv.semantic || f;
      if (sv.select === 'point') {{
        var vals = extractPointValues(raw, f);
        if (vals.length) {{
          selMap[semanticKey] = (selMap[semanticKey] || []).concat(vals).filter(function(v, i, a) {{ return a.indexOf(v) === i; }});
        }}
      }} else if (sv.select === 'interval') {{
        var chs = sv.source_channels;
        if (!chs || !chs.length) return;
        var ch = chs[0];
        var range = raw[ch];
        if (Array.isArray(range) && range.length === 2) {{
          selMap[semanticKey] = [Number(range[0]), Number(range[1])];
        }}
      }}
    }});
    if (!hasSel) return;

    ctrlViews.forEach(function(cv) {{
      var dv = viewRegistry.get(cv.view + '_data');
      if (!dv || !dv.fullData) return;
      var full = dv.fullData;
      var linkF = cv.field;
      var semanticKey = cv.semantic || linkF;
      if (!linkF || !selMap[semanticKey]) return;
      var svals = selMap[semanticKey];
      var numericRange = Array.isArray(svals) && svals.length === 2 && typeof svals[0] === 'number';

      var filtered = full.filter(function(row) {{
        var rv = row[linkF];
        if (rv == null) return false;
        if (numericRange) {{
          var nv = Number(rv);
          return !isNaN(nv) && nv >= svals[0] && nv <= svals[1];
        }}
        if (Array.isArray(svals)) {{
          return svals.some(function(v) {{ return String(v) === String(rv); }});
        }}
        return String(svals) === String(rv);
      }});
      if (filtered.length === 0 && full.length > 0) filtered = [full[0]];

      var target = viewRegistry.get(cv.view);
      if (!target) return;
      target.data('bg_' + cv.view, cv.action === 'highlight' ? full : []);
      target.data('fg_' + cv.view, filtered);
      target.runAsync();
    }});
  }}

  window.addEventListener('interaction-' + IID, process);
}})();"""

    def _validate_interaction_result(
        self,
        spec,
        js_code,
        updated_vis,
        sv_ids,
        tv_ids,
        field_semantics=None
    ):
        """Validate an interaction result. Returns {valid, issues, error}."""
        issues = []
        field_semantics = (
            field_semantics if isinstance(field_semantics, dict) else {}
        )
        if not spec:
            return {"valid": False, "issues": [{"type": "empty_spec", "detail": "Interaction spec is empty"}], "error": "Empty interaction spec"}

        sv = spec.get("source_views", [])
        cv = spec.get("controlled_view", [])

        if not sv:
            issues.append({"type": "no_source", "detail": "No source views defined"})
        actual_source_ids = {
            item.get("id") for item in sv if isinstance(item, dict)
        }
        missing_sources = sorted(set(sv_ids) - actual_source_ids)
        if missing_sources:
            issues.append({
                "type": "missing_source_views",
                "detail": f"I-Spec omits declared V->I sources: {missing_sources}"
            })

        for s in sv:
            source_id = s.get("id")
            source_spec = updated_vis.get(source_id, {}).get("spec", {})
            encoding_pairs = dict(self._encoding_pairs(source_spec))
            if source_id not in updated_vis:
                issues.append({
                    "type": "unknown_source_view",
                    "detail": f"Source view {source_id} does not exist"
                })
            if not s.get("link_field"):
                issues.append({"type": "no_link_field", "detail": f"Source {s.get('id')} missing link_field"})
            elif s.get("link_field") not in self._encoding_fields(
                source_spec
            ):
                issues.append({
                    "type": "invalid_link_field",
                    "detail": (
                        f"Source {source_id} field {s.get('link_field')} "
                        "is not present in its visualization encoding"
                    )
                })
            source_channels = s.get("source_channels") or []
            if not isinstance(source_channels, list) or not source_channels:
                issues.append({
                    "type": "no_source_channels",
                    "detail": f"Source {source_id} has no selection channels"
                })
            else:
                unknown_channels = [
                    channel for channel in source_channels
                    if channel not in encoding_pairs
                ]
                if unknown_channels:
                    issues.append({
                        "type": "invalid_source_channels",
                        "detail": (
                            f"Source {source_id} channels {unknown_channels} "
                            "do not exist in its encoding"
                        )
                    })
                channel_fields = {
                    encoding_pairs[channel]
                    for channel in source_channels
                    if channel in encoding_pairs
                }
                if (
                    s.get("link_field")
                    and channel_fields
                    and s.get("link_field") not in channel_fields
                ):
                    issues.append({
                        "type": "channel_field_mismatch",
                        "detail": (
                            f"Source {source_id} channels select "
                            f"{sorted(channel_fields)}, not link field "
                            f"{s.get('link_field')}"
                        )
                    })
                if s.get("select") == "interval" and any(
                    channel not in ("x", "y") for channel in source_channels
                ):
                    issues.append({
                        "type": "invalid_interval_channel",
                        "detail": (
                            f"Interval selection on {source_id} must use x/y, "
                            f"got {source_channels}"
                        )
                    })
            if s.get("select") not in ("point", "interval", "none"):
                issues.append({"type": "invalid_select", "detail": f"Source {s.get('id')} invalid select type: {s.get('select')}"})

        if not cv:
            issues.append({"type": "no_target", "detail": "No controlled target views"})
        actual_target_ids = {
            item.get("view") for item in cv if isinstance(item, dict)
        }
        missing_targets = sorted(set(tv_ids) - actual_target_ids)
        if missing_targets:
            issues.append({
                "type": "missing_target_views",
                "detail": f"I-Spec omits declared I->V targets: {missing_targets}"
            })

        for c in cv:
            if not c.get("view"):
                issues.append({"type": "no_target_view", "detail": "Controlled view missing view id"})
            elif c.get("view") not in updated_vis:
                issues.append({
                    "type": "unknown_target_view",
                    "detail": f"Controlled view {c.get('view')} does not exist"
                })
            elif c.get("field") not in self._encoding_fields(
                updated_vis.get(c.get("view"), {}).get("spec", {})
            ):
                issues.append({
                    "type": "invalid_target_field",
                    "detail": (
                        f"Controlled view {c.get('view')} field {c.get('field')} "
                        "is not present in its visualization encoding"
                    )
                })
            if c.get("action") not in ("filter", "highlight"):
                issues.append({"type": "invalid_action", "detail": f"Controlled view {c.get('view')} invalid action: {c.get('action')}"})

        source_link_fields = {
            item.get("link_field") for item in sv if item.get("link_field")
        }
        source_concepts = set()
        source_semantic_types = set()
        for source in sv:
            records = self._resolve_view_field_semantics(
                source.get("id", ""),
                source.get("link_field", ""),
                updated_vis,
                field_semantics
            )
            resolved_concepts = {
                record.get("concept") for record in records
                if record.get("concept")
            }
            declared_concept = source.get("semantic")
            if declared_concept and resolved_concepts and declared_concept not in resolved_concepts:
                issues.append({
                    "type": "source_semantic_mismatch",
                    "detail": (
                        f"Source {source.get('id')} field "
                        f"{source.get('link_field')} has semantics "
                        f"{sorted(resolved_concepts)}, not {declared_concept}"
                    )
                })
            source_concepts.update(resolved_concepts)
            if declared_concept:
                source_concepts.add(declared_concept)
            source_semantic_types.update({
                record.get("semantic_type") for record in records
                if record.get("semantic_type") not in (None, "unknown")
            })

        for target in cv:
            records = self._resolve_view_field_semantics(
                target.get("view", ""),
                target.get("field", ""),
                updated_vis,
                field_semantics
            )
            target_concepts = {
                record.get("concept") for record in records
                if record.get("concept")
            }
            declared_concept = target.get("semantic")
            if declared_concept and target_concepts and declared_concept not in target_concepts:
                issues.append({
                    "type": "target_semantic_mismatch",
                    "detail": (
                        f"Target {target.get('view')} field {target.get('field')} "
                        f"has semantics {sorted(target_concepts)}, "
                        f"not {declared_concept}"
                    )
                })
            if declared_concept:
                target_concepts.add(declared_concept)

            if source_concepts and target_concepts:
                if not (source_concepts & target_concepts):
                    issues.append({
                        "type": "semantic_link_mismatch",
                        "detail": (
                            f"Target {target.get('view')}.{target.get('field')} "
                            f"semantics {sorted(target_concepts)} are unrelated "
                            f"to source semantics {sorted(source_concepts)}"
                        )
                    })
            elif (
                target.get("field")
                and source_link_fields
                and target.get("field") not in source_link_fields
            ):
                # Without a semantic catalog, preserve the safe legacy rule.
                issues.append({
                    "type": "link_field_mismatch",
                    "detail": (
                        f"Target field {target.get('field')} does not match "
                        f"source link fields {sorted(source_link_fields)}, and "
                        "no semantic mapping is available"
                    )
                })

            target_types = {
                record.get("semantic_type") for record in records
                if record.get("semantic_type") not in (None, "unknown")
            }
            if (
                source_semantic_types
                and target_types
                and not (source_semantic_types & target_types)
            ):
                issues.append({
                    "type": "semantic_type_mismatch",
                    "detail": (
                        f"Source semantic types {sorted(source_semantic_types)} "
                        f"are incompatible with target types {sorted(target_types)}"
                    )
                })

        if not js_code:
            issues.append({"type": "no_js", "detail": "No JS code generated"})

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "error": issues[0]["detail"] if issues else ""
        }

    def _encoding_fields(self, spec: Dict) -> List[str]:
        if not spec:
            return []
        fields = []
        # Handle dual-layer specs (after modify_vega_code_target)
        if "layer" in spec:
            for layer in spec.get("layer", []):
                for ch, enc in layer.get("encoding", {}).items():
                    f = enc.get("field") or enc.get("fieldName", "")
                    if f and f not in fields:
                        fields.append(f)
        else:
            for ch, enc in spec.get("encoding", {}).items():
                f = enc.get("field") or enc.get("fieldName", "")
                if f and f not in fields:
                    fields.append(f)
        return fields

    def _encoding_pairs(self, spec: Dict) -> List[tuple]:
        pairs = []
        encoding = {}
        if "layer" in spec:
            for layer in spec.get("layer", []):
                encoding = layer.get("encoding", {})
                break
        else:
            encoding = spec.get("encoding", {})
        for ch, enc in encoding.items():
            f = enc.get("field") or enc.get("fieldName", "")
            if f:
                pairs.append((ch, f))
        return pairs

    def _build_view_data_urls(self, processed_vis, all_table_paths, project_id=""):
        urls = {}
        for v_id, vis_data in processed_vis.items():
            for tid in (vis_data.get("metadata") or {}).get("used_tables", []):
                if tid in all_table_paths:
                    if project_id:
                        base_url = os.environ.get(
                            "DATA_SERVICE_URL", "http://localhost:5000/data"
                        ).rstrip("/")
                        urls[v_id] = f"{base_url}/{project_id}/{tid}.csv"
                    else:
                        urls[v_id] = all_table_paths[tid]
                    break
        return urls

    @staticmethod
    def _clean_json_text(text: str) -> str:
        """Clean NaN/Infinity values from LLM JSON output before parsing."""
        cleaned = re.sub(r'\bNaN\b', 'null', text)
        cleaned = re.sub(r'\bInfinity\b', 'null', cleaned)
        cleaned = re.sub(r'\b-Infinity\b', 'null', cleaned)
        return cleaned

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict]:
        """Extract and parse a JSON object from LLM output text."""
        # Try direct JSON parse
        cleaned = InteractionAgent._clean_json_text(text.strip())
        if cleaned.startswith("{"):
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

        # Try to extract JSON from markdown code block
        m = re.search(r'```(?:json)?\s*\n?(\{.*?\})\s*\n?```', text, re.DOTALL)
        if m:
            cleaned = InteractionAgent._clean_json_text(m.group(1))
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

        # Try to extract first { ... } block
        m = re.search(r'(\{.*\})', text, re.DOTALL)
        if m:
            cleaned = InteractionAgent._clean_json_text(m.group(1))
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

        return None


def get_interaction_agent(project_dir: str = None) -> InteractionAgent:
    return InteractionAgent(model_client=get_model_client(), project_dir=project_dir)
