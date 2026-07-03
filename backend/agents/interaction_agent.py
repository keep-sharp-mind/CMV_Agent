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
        project_id: str = ""
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
        updated_vis = copy.deepcopy(processed_vis)
        interaction_results = {}

        for i_node in i_nodes:
            i_id = i_node["id"]
            trigger = i_node.get("trigger", "select")
            effect = i_node.get("effect", "filter")
            select_type = "point" if trigger == "select" else "interval"
            sv_ids = i_sources.get(i_id, [])
            tv_ids = i_targets.get(i_id, [])
            if not sv_ids:
                continue

            spec = self._build_interaction_spec(i_id, trigger, effect, select_type, sv_ids, tv_ids, updated_vis, i_node=i_node)

            # 1) Modify source specs: add selection param + opacity condition
            for vid in sv_ids:
                vis = updated_vis.get(vid)
                if vis and vis.get("spec"):
                    mod = self.modify_vega_code_source(copy.deepcopy(vis["spec"]), i_id, spec)
                    vis["spec"] = mod
                    vis["spec_json"] = json.dumps(mod, indent=2, ensure_ascii=False)

            # 2) Modify target specs: dual-layer (bg + fg) with named datasets
            for vid in tv_ids:
                vis = updated_vis.get(vid)
                if vis and vis.get("spec"):
                    mod = self.modify_vega_code_target(copy.deepcopy(vis["spec"]), i_id, spec, tv_id=vid)
                    vis["spec"] = mod
                    vis["spec_json"] = json.dumps(mod, indent=2, ensure_ascii=False)

            # 3) Generate frontend JS
            js = self.generate_js_interaction(spec, view_data_urls, i_id)

            # 4) Build V-id → signal-slot mapping for the frontend
            signal_slots = {}
            for vid in sv_ids:
                signal_slots[vid] = f"sel_{i_id}"

            result = {
                "interaction_spec": spec,
                "js_code": js,
                "success": True,
                "source_v_ids": sv_ids,
                "target_v_ids": tv_ids,
                "signal_slots": signal_slots
            }

            # Validate and attempt error recovery
            validation = self._validate_interaction_result(spec, js, updated_vis, sv_ids, tv_ids)
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
                            spec = fix["interaction_spec"]
                            result["interaction_spec"] = spec
                            result["js_code"] = self.generate_js_interaction(spec, view_data_urls, i_id)
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

    def _build_view_specs_json(self, updated_vis: Dict[str, Any]) -> str:
        """Build a condensed view-specs JSON for the LLM prompt."""
        summaries = []
        for v_id, v_data in updated_vis.items():
            spec = v_data.get("spec", {})
            mark = spec.get("mark", "")
            if isinstance(mark, dict):
                mark = mark.get("type", "")
            meta = v_data.get("metadata", {})
            encoding = spec.get("encoding", {})
            enc_summary = {}
            for ch, enc in encoding.items():
                f = enc.get("field") or enc.get("fieldName", "")
                if f:
                    enc_summary[ch] = f
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

    def _build_interaction_spec(self, i_id, trigger, effect, select_type, sv_ids, tv_ids, updated_vis, i_node=None):
        """
        Generate interaction spec using LLM, with hardcoded fallback.
        """
        llm_spec = None
        view_specs_json = ""
        requirement_text = ""

        if i_node:
            view_specs_json = self._build_view_specs_json(updated_vis)
            requirement_text = self._build_interaction_requirement(i_node)
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
                if parsed and "source_views" in parsed and "controlled_view" in parsed:
                    llm_spec = parsed
            except Exception:
                pass

        if llm_spec:
            return {
                "interaction_id": i_id, "trigger": trigger, "effect": effect,
                "select_type": select_type,
                "source_views": llm_spec.get("source_views", []),
                "controlled_view": llm_spec.get("controlled_view", []),
                "_llm_generated": True
            }

        # Fallback: hardcoded extraction from encoding
        source_views = []
        for vid in sv_ids:
            s = updated_vis.get(vid, {}).get("spec", {})
            pairs = self._encoding_pairs(s)
            source_channels = [ch for ch, f in pairs]
            fields = [f for ch, f in pairs]
            source_views.append({
                "id": vid,
                "select": select_type,
                "source_channels": source_channels,
                "link_field": fields[0] if fields else ""
            })
        controlled_view = []
        for vid in tv_ids:
            s = updated_vis.get(vid, {}).get("spec", {})
            tf = self._encoding_fields(s)
            controlled_view.append({
                "view": vid,
                "field": tf[0] if tf else "",
                "action": effect
            })
        return {
            "interaction_id": i_id, "trigger": trigger, "effect": effect,
            "select_type": select_type, "source_views": source_views,
            "controlled_view": controlled_view
        }

    def modify_vega_code_source(self, spec: Dict, i_id: str, interaction_spec: Dict) -> Dict:
        """Add a Vega-Lite selection parameter + opacity condition for the interaction."""
        sel_name = f"sel_{i_id}"
        stype = interaction_spec.get("select_type", "point")

        param = {"name": sel_name, "select": {"type": stype}}
        if stype == "point":
            param["select"]["on"] = "click"

        spec.setdefault("params", []).append(param)

        # Add conditional opacity on mark
        mark = spec.get("mark")
        if mark:
            if isinstance(mark, str):
                spec["mark"] = {"type": mark}
                mark = spec["mark"]
            mark.setdefault("opacity", {"condition": {"param": sel_name, "value": 1}, "value": 0.3})
        else:
            # Fallback: add to encoding opacity
            enc = spec.setdefault("encoding", {})
            if "opacity" not in enc:
                enc["opacity"] = {"condition": {"param": sel_name, "value": 1}, "value": 0.3}
        return spec

    def modify_vega_code_target(self, spec: Dict, i_id: str, interaction_spec: Dict, tv_id: str = "") -> Dict:
        """Restructure target spec into dual-layer (bg + fg) with named datasets."""
        mark = spec.get("mark", {})
        if isinstance(mark, str):
            mark = {"type": mark}
        encoding = spec.get("encoding", {})

        suffix = f"{i_id}_{tv_id}" if tv_id else i_id
        bg_data = f"bg_{suffix}"
        fg_data = f"fg_{suffix}"

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
            {"id": s["id"], "select": s.get("select", "point"),
             "source_channels": s.get("source_channels", []),
             "link_field": s.get("link_field", "")} for s in sv
        ])
        ctrl_views_json = json.dumps([
            {"view": c["view"], "field": c.get("field", ""),
             "action": c.get("action", "filter")} for c in cv
        ])

        return f"""(function() {{
  var IID = '{i_id}';
  var srcViews = {src_views_json};
  var ctrlViews = {ctrl_views_json};

  function process() {{
    var selMap = {{}};
    var hasSel = false;

    srcViews.forEach(function(sv) {{
      var raw = window['I_Data_' + IID + '_' + sv.id];
      if (raw == null) return;
      hasSel = true;
      var f = sv.link_field;
      if (!f) return;
      if (sv.select === 'point') {{
        if (Array.isArray(raw)) {{
          selMap[f] = raw.map(function(d) {{ return String(d[f] != null ? d[f] : d); }});
        }}
      }} else if (sv.select === 'interval') {{
        var chs = sv.source_channels;
        if (!chs || !chs.length) return;
        var ch = chs[0];
        var range = raw[ch];
        if (Array.isArray(range) && range.length === 2) {{
          selMap[f] = [Number(range[0]), Number(range[1])];
        }}
      }}
    }});
    if (!hasSel) return;

    ctrlViews.forEach(function(cv) {{
      var dv = viewRegistry.get(cv.view + '_data');
      if (!dv || !dv.fullData) return;
      var full = dv.fullData;
      var linkF = cv.field;
      if (!linkF || !selMap[linkF]) return;
      var svals = selMap[linkF];
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
      var suffix = IID + '_' + cv.view;
      target.data('bg_' + suffix, cv.action === 'highlight' ? full : (full.length > 0 ? [full[0]] : []));
      target.data('fg_' + suffix, filtered);
      target.runAsync();
    }});
  }}

  setInterval(process, 250);
  window.addEventListener('interaction-' + IID, process);
}})();"""

    def _validate_interaction_result(self, spec, js_code, updated_vis, sv_ids, tv_ids):
        """Validate an interaction result. Returns {valid, issues, error}."""
        issues = []
        if not spec:
            return {"valid": False, "issues": [{"type": "empty_spec", "detail": "Interaction spec is empty"}], "error": "Empty interaction spec"}

        sv = spec.get("source_views", [])
        cv = spec.get("controlled_view", [])

        if not sv:
            issues.append({"type": "no_source", "detail": "No source views defined"})

        for s in sv:
            if not s.get("link_field"):
                issues.append({"type": "no_link_field", "detail": f"Source {s.get('id')} missing link_field"})
            if s.get("select") not in ("point", "interval", "none"):
                issues.append({"type": "invalid_select", "detail": f"Source {s.get('id')} invalid select type: {s.get('select')}"})

        if not cv:
            issues.append({"type": "no_target", "detail": "No controlled target views"})

        for c in cv:
            if not c.get("view"):
                issues.append({"type": "no_target_view", "detail": "Controlled view missing view id"})
            if c.get("action") not in ("filter", "highlight"):
                issues.append({"type": "invalid_action", "detail": f"Controlled view {c.get('view')} invalid action: {c.get('action')}"})

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
                        urls[v_id] = f"/api/projects/{project_id}/data/{tid}.csv/download"
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
