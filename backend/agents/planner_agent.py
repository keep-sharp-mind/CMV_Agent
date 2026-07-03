"""
Planner Agent - Maintains a global data-flow table for all plan nodes.
For each node, computes:
  - in_fields:  fields consumed from upstream nodes (qualified as "node_id.field")
  - out_fields: fields this node produces that downstream nodes need
"""

from typing import List, Dict, Any, Optional, Set, Tuple


class PlannerAgent:
    """Analyzes field-level data flow across all plan nodes."""

    def __init__(self, project_dir: str = None):
        self.project_dir = project_dir

    def analyze_data_flow(
        self,
        plan_data: Dict[str, Any],
        database_schema: List[Dict[str, Any]],
        processed_vis: Dict[str, Any],
        processed_nodes: Dict[str, Any]
    ) -> Dict[str, Dict[str, List[str]]]:
        """
        Entry-point: compute in_fields / out_fields for every node.

        Returns:
            {
                "V1": { "in_fields": ["D1.species","D1.sepal_length"],
                        "out_fields": ["species"] },
                "D1": { "in_fields": ["d1.species","d1.sepal_length"],
                        "out_fields": ["species","sepal_length"] },
                ...
            }
        """
        nodes = plan_data.get("nodes", {})
        deps = plan_data.get("dependencies", [])

        d_nodes = nodes.get("d", [])
        D_nodes = nodes.get("D", [])
        V_nodes = nodes.get("V", [])
        I_nodes = nodes.get("I", [])

        all_nodes = d_nodes + D_nodes + V_nodes + I_nodes
        node_map: Dict[str, dict] = {n["id"]: n for n in all_nodes}

        # ---- 1. Build adjacency & edge maps ----
        fwd: Dict[str, List[dict]] = {n["id"]: [] for n in all_nodes}
        bwd: Dict[str, List[dict]] = {n["id"]: [] for n in all_nodes}
        for dep in deps:
            f, t = dep["from"], dep["to"]
            if f in fwd:
                fwd[f].append(dep)
            if t in bwd:
                bwd[t].append(dep)

        # ---- 2. Determine fields per edge ----
        edge_fields: Dict[Tuple[str, str], List[str]] = {}

        # Phase A: D->V edges → from V encoding in processed_vis
        v_req: Dict[str, Set[str]] = {}
        for dep in deps:
            if dep.get("type") == "D->V":
                v_id = dep["to"]
                fields = self._get_v_required_fields(v_id, processed_vis)
                v_req[v_id] = fields
                edge_fields[(dep["from"], v_id)] = list(fields)

        # Phase B: V->I edges → link field from V encoding
        v_link_fields: Dict[str, str] = {}
        for dep in deps:
            if dep.get("type") == "V->I":
                flds = self._get_v_required_fields(dep["from"], processed_vis)
                lf = list(flds)[0] if flds else ""
                edge_fields[(dep["from"], dep["to"])] = [lf] if lf else []
                v_link_fields[dep["to"]] = lf

        # Phase C: I->V edges → forward the same link field
        for dep in deps:
            if dep.get("type") == "I->V":
                lf = v_link_fields.get(dep["from"], "")
                edge_fields[(dep["from"], dep["to"])] = [lf] if lf else []

        # Phase D: D->D & D->V backward propagation
        d_ids = [n["id"] for n in D_nodes]
        D_downstream_req: Dict[str, Set[str]] = {}
        for dep in deps:
            t = dep.get("type", "")
            if t == "D->V":
                d_id = dep["from"]
                D_downstream_req.setdefault(d_id, set()).update(v_req.get(dep["to"], set()))
            elif t == "D->D":
                # downstream D node's requirements will be its upstream D's requirements
                pass

        # Topological order for D nodes (forward)
        d_adj: Dict[str, List[str]] = {d: [] for d in d_ids}
        d_indeg: Dict[str, int] = {d: 0 for d in d_ids}
        for dep in deps:
            if dep.get("type") == "D->D":
                f, t = dep["from"], dep["to"]
                if f in d_adj and t in d_adj:
                    d_adj[f].append(t)
                    d_indeg[t] = d_indeg.get(t, 0) + 1

        d_queue = [d for d in d_ids if d_indeg.get(d, 0) == 0]
        d_topo = []
        while d_queue:
            cur = d_queue.pop(0)
            d_topo.append(cur)
            for nb in d_adj.get(cur, []):
                d_indeg[nb] -= 1
                if d_indeg[nb] == 0:
                    d_queue.append(nb)

        # Backward propagate field requirements
        for d_id in reversed(d_topo):
            needed = D_downstream_req.get(d_id, set())
            # Also include fields from D->D edges pointing to this node
            for dep in deps:
                if dep.get("to") == d_id and dep.get("type") == "D->D":
                    needed.update(D_downstream_req.get(dep["from"], set()))
            D_downstream_req[d_id] = needed

            # Set edge fields for D->D edges where this is the source
            for dep in deps:
                if dep.get("from") == d_id and dep.get("type") == "D->D":
                    edge_fields[(d_id, dep["to"])] = list(needed)

        # Phase E: d->D edges → columns from source table (or subset needed by D)
        # Build source-table → columns map
        table_cols = self._build_table_column_map(database_schema)
        for dep in deps:
            if dep.get("type") == "d->D":
                d_node = node_map.get(dep["from"], {})
                src = d_node.get("source_table", "")
                all_cols = table_cols.get(src, [])
                # Filter to only what downstream D needs, if known
                d_id = dep["to"]
                needed = D_downstream_req.get(d_id, set())
                if needed:
                    edge_fields[(dep["from"], dep["to"])] = [c for c in all_cols if c in needed]
                else:
                    edge_fields[(dep["from"], dep["to"])] = all_cols

        # ---- 3. Aggregate in/out fields per node ----
        result: Dict[str, Dict[str, List[str]]] = {}

        # Also include d-node output columns even if no edges
        for n in d_nodes:
            sid = n.get("source_table", "")
            cols = table_cols.get(sid, [])
            # out_fields from outgoing edges
            out_f = set()
            for dep in fwd.get(n["id"], []):
                key = (n["id"], dep["to"])
                out_f.update(edge_fields.get(key, []))
            # If no outgoing edges but we have columns, show all
            if not out_f and cols:
                out_f = set(cols)
            result[n["id"]] = {"in_fields": [], "out_fields": sorted(out_f)}

        for n in D_nodes:
            nid = n["id"]
            # out_fields: from processed results if available, else from downstream needs
            out_f = set()
            dn = processed_nodes.get(nid, {})
            if dn and dn.get("columns"):
                # Use actual output columns from processed node
                out_f = set(dn["columns"])
            else:
                for dep in fwd.get(nid, []):
                    key = (nid, dep["to"])
                    out_f.update(edge_fields.get(key, []))
                if not out_f:
                    out_f = D_downstream_req.get(nid, set())
            # in_fields: from incoming edges
            in_f = []
            for dep in bwd.get(nid, []):
                key = (dep["from"], nid)
                for fld in edge_fields.get(key, []):
                    q = f"{dep['from']}.{fld}"
                    if q not in in_f:
                        in_f.append(q)
            result[nid] = {"in_fields": in_f, "out_fields": sorted(out_f)}

        for n in V_nodes:
            nid = n["id"]
            in_f = []
            for dep in bwd.get(nid, []):
                key = (dep["from"], nid)
                for fld in edge_fields.get(key, []):
                    q = f"{dep['from']}.{fld}"
                    if q not in in_f:
                        in_f.append(q)
            out_f = set()
            for dep in fwd.get(nid, []):
                key = (nid, dep["to"])
                out_f.update(edge_fields.get(key, []))
            result[nid] = {"in_fields": in_f, "out_fields": sorted(out_f)}

        for n in I_nodes:
            nid = n["id"]
            in_f = []
            for dep in bwd.get(nid, []):
                key = (dep["from"], nid)
                for fld in edge_fields.get(key, []):
                    q = f"{dep['from']}.{fld}"
                    if q not in in_f:
                        in_f.append(q)
            out_f = set()
            for dep in fwd.get(nid, []):
                key = (nid, dep["to"])
                out_f.update(edge_fields.get(key, []))
            result[nid] = {"in_fields": in_f, "out_fields": sorted(out_f)}

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_v_required_fields(v_id: str, processed_vis: Dict) -> Set[str]:
        """Extract field names a V node uses from its spec / metadata."""
        vis = processed_vis.get(v_id, {})
        fields: Set[str] = set()
        meta = vis.get("metadata") or {}
        used = meta.get("used_fields", [])
        if used:
            fields.update(used)
        spec = vis.get("spec") or {}
        encoding = spec.get("encoding") or {}
        for _ch, enc in encoding.items():
            f = enc.get("field") or enc.get("fieldName", "")
            if f:
                fields.add(f)
        # Also check encoding_fields in metadata
        ef = meta.get("encoding_fields") or {}
        for _ch, f in ef.items():
            if f:
                fields.add(f)
        return fields

    @staticmethod
    def _build_table_column_map(database_schema: List[Dict]) -> Dict[str, List[str]]:
        """Map table names (qualified or short) to column lists."""
        col_map: Dict[str, List[str]] = {}
        for db in database_schema:
            for tbl in db.get("tables", []):
                tname = tbl["table_name"]
                cols = [c["column_name"] for c in tbl.get("columns", [])]
                # Store both short name and qualified name
                col_map[tname] = cols
                qname = f"{db['db_name']}.{tname}"
                col_map[qname] = cols
        return col_map


def get_planner_agent(project_dir: str = None) -> PlannerAgent:
    return PlannerAgent(project_dir=project_dir)
