"""
Plan Agent - Agent specifically responsible for generating plans
Implemented through two prompts:
1. Refine requirements: Break down the overall goal into several refined requirements
2. Split nodes: Break down refined requirements into D, V, I node types and build dependency graph
"""

import json
import os
import re
from typing import List, Dict, Any, Optional
from model import get_model_client, ModelClient
from prompts.plan_agent_prompts import (
    SYSTEM_PROMPT,
    GENERATE_GOAL_PROMPT,
    REFINE_REQUIREMENTS_PROMPT,
    NODES_AND_DEPENDENCIES_PROMPT
)


class PlanAgent:
    """Plan Agent - Generate analysis plans"""

    def __init__(
        self,
        model_client: Optional[ModelClient] = None,
        system_prompt: Optional[str] = None
    ):
        """
        Initialize Plan Agent

        Args:
            model_client: Model client instance
            system_prompt: System prompt
        """
        self.model_client = model_client or get_model_client()
        self.system_prompt = system_prompt or SYSTEM_PROMPT

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
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        response = self.model_client.chat(messages, temperature=temperature)
        content = response["content"]

        # Try to extract JSON from content
        return self._extract_json(content)

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """
        Extract JSON object from text

        Args:
            text: Text that may contain JSON

        Returns:
            Dict: Parsed JSON object
        """
        # Try direct parsing
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to extract ```json ... ``` blocks
        pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
        matches = re.findall(pattern, text)
        for match in matches:
            try:
                return json.loads(match.strip())
            except json.JSONDecodeError:
                continue

        # Try to extract from first { to last }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        # All attempts failed, return raw text
        return {"raw_text": text}

    def _format_database_schema(self, database_schema: List[Dict[str, Any]]) -> str:
        """
        Format database schema to text

        Args:
            database_schema: Database schema information

        Returns:
            str: Formatted text
        """
        lines = []
        for db in database_schema:
            lines.append(f"Database: {db['db_name']}")
            for table in db.get("tables", []):
                lines.append(f"  Table: {table['table_name']} ({table.get('row_count', 0)} rows)")
                for col in table.get("columns", []):
                    col_info = f"    - {col['column_name']} ({col['data_type']})"
                    vr = col.get("value_range", {})
                    if vr.get("type") == "numeric":
                        col_info += f" [min: {vr.get('min')}, max: {vr.get('max')}]"
                    elif vr.get("type") == "string":
                        samples = vr.get("sample_values", [])[:5]
                        if samples:
                            col_info += f" [samples: {', '.join(samples)}]"
                    lines.append(col_info)
            lines.append("")
        return "\n".join(lines)

    def generate_goal(
        self,
        database_schema: List[Dict[str, Any]],
        context: str = ""
    ) -> str:
        """
        Generate a high-level project goal based on database schema

        Args:
            database_schema: Database schema information
            context: Additional context

        Returns:
            str: Generated project goal
        """
        schema_text = self._format_database_schema(database_schema)
        context_section = f"Additional Context: {context}" if context else ""

        prompt = GENERATE_GOAL_PROMPT.format(
            schema_text=schema_text,
            context_section=context_section
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt}
        ]

        response = self.model_client.chat(messages, temperature=0.5)
        goal = response["content"].strip()

        # Remove possible quotes
        goal = goal.strip('"').strip("'").strip()

        return goal

    def _generate_refined_requirements(
        self,
        goal: str,
        database_schema: List[Dict[str, Any]],
        context: str = ""
    ) -> List[Dict[str, str]]:
        """
        Step 1: Refine requirements, break down the overall goal into several refined requirements

        Args:
            goal: Project goal
            database_schema: Database schema information
            context: Additional context

        Returns:
            List[Dict]: List of refined requirements, each containing id, name, description
        """
        schema_text = self._format_database_schema(database_schema)
        context_section = f"Additional Context: {context}" if context else ""

        prompt = REFINE_REQUIREMENTS_PROMPT.format(
            goal=goal,
            schema_text=schema_text,
            context_section=context_section
        )

        result = self._chat_json(prompt, temperature=0.4)
        requirements = result.get("requirements", [])

        if not requirements:
            # fallback
            requirements = [
                {"id": "R1", "name": "Basic statistical analysis", "description": "Perform basic statistical analysis of the data"}
            ]

        return requirements

    def _generate_nodes_and_dependencies(
        self,
        goal: str,
        requirements: List[Dict[str, str]],
        database_schema: List[Dict[str, Any]],
        context: str = ""
    ) -> Dict[str, Any]:
        """
        Step 2: Split refined requirements into D, V, I node types and build dependency graph

        Args:
            goal: Project goal
            requirements: List of refined requirements
            database_schema: Database schema information
            context: Additional context

        Returns:
            Dict: Contains nodes and dependencies
        """
        schema_text = self._format_database_schema(database_schema)
        context_section = f"Additional Context: {context}" if context else ""
        req_text = "\n".join([
            f"- {r['id']}: {r['name']} - {r['description']}"
            for r in requirements
        ])

        # Collect input table names (lowercase d)
        input_tables = []
        for db in database_schema:
            for table in db.get("tables", []):
                input_tables.append({
                    "db_name": db["db_name"],
                    "table_name": table["table_name"],
                    "columns": [c["column_name"] for c in table.get("columns", [])]
                })

        input_tables_text = "\n".join([
            f"- d{idx+1}: {t['db_name']}.{t['table_name']} (input data table)"
            for idx, t in enumerate(input_tables)
        ])

        prompt = NODES_AND_DEPENDENCIES_PROMPT.format(
            goal=goal,
            req_text=req_text,
            input_tables_text=input_tables_text,
            schema_text=schema_text,
            context_section=context_section
        )

        result = self._chat_json(prompt, temperature=0.3)

        # Ensure structure is complete
        nodes = result.get("nodes", {})
        dependencies = result.get("dependencies", [])

        # Ensure d nodes exist (supplement with input table names)
        if not nodes.get("d"):
            d_nodes = []
            for idx, t in enumerate(input_tables):
                d_nodes.append({
                    "id": f"d{idx+1}",
                    "name": t["table_name"],
                    "description": "Input data table",
                    "source_table": f"{t['db_name']}.{t['table_name']}"
                })
            nodes["d"] = d_nodes

        # Validate and fix I node dependencies
        dependencies = self._fix_i_node_dependencies(dependencies, nodes)

        # Validate dependency graph rules
        validation_errors = self._validate_dependencies(nodes, dependencies)

        return {
            "nodes": nodes,
            "dependencies": dependencies,
            "validation_errors": validation_errors
        }

    def _fix_i_node_dependencies(
        self,
        dependencies: List[Dict[str, Any]],
        nodes: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Validate and fix I node dependencies to ensure correct edge direction.

        Rules:
        - I nodes must have ONLY incoming V->I edges
        - I nodes must have ONLY outgoing I->V edges
        - V<->I bidirectional edges are illegal
        - I->I connections are illegal

        Args:
            dependencies: List of dependency edges
            nodes: All nodes (d, D, V, I)

        Returns:
            List: Fixed dependencies
        """
        v_ids = {v["id"] for v in nodes.get("V", [])}
        i_ids = {i["id"] for i in nodes.get("I", [])}

        if not i_ids:
            return dependencies

        # Build edge maps for each I node
        i_incoming = {i_id: [] for i_id in i_ids}  # V->I edges
        i_outgoing = {i_id: [] for i_id in i_ids}  # I->V edges

        valid_deps = []

        for dep in dependencies:
            from_node = dep.get("from", "")
            to_node = dep.get("to", "")
            dep_type = dep.get("type", "")

            # Skip I->I connections (illegal)
            if from_node in i_ids and to_node in i_ids:
                continue

            # Track V->I edges
            if from_node in v_ids and to_node in i_ids and dep_type == "V->I":
                i_incoming[to_node].append(from_node)
                valid_deps.append(dep)

            # Track I->V edges
            elif from_node in i_ids and to_node in v_ids and dep_type == "I->V":
                # Skip if the same V is both trigger and target (illegal)
                if from_node in i_incoming and to_node in i_incoming.get(from_node, []):
                    continue
                i_outgoing[from_node].append(to_node)
                valid_deps.append(dep)

            # Any non-I edge (d->D, D->D, d->V, D->V, etc.) is preserved
            else:
                valid_deps.append(dep)

        # For each I node, ensure it has at least 1 incoming and 1 outgoing edge
        # If missing, try to create valid connections
        for i_id in i_ids:
            if not i_incoming[i_id]:
                # I node has no trigger source, try to find a V that isn't already its target
                available_v = [v for v in v_ids if v not in i_outgoing.get(i_id, [])]
                if available_v:
                    # Use the first available V as trigger source
                    trigger_v = available_v[0]
                    i_incoming[i_id].append(trigger_v)
                    valid_deps.append({
                        "from": trigger_v,
                        "to": i_id,
                        "type": "V->I"
                    })

            if not i_outgoing[i_id]:
                # I node has no affected target, try to find a V that isn't already its source
                available_v = [v for v in v_ids if v not in i_incoming.get(i_id, [])]
                if available_v:
                    # Use the first available V as affected target
                    target_v = available_v[0]
                    i_outgoing[i_id].append(target_v)
                    valid_deps.append({
                        "from": i_id,
                        "to": target_v,
                        "type": "I->V"
                    })

        return valid_deps

    def _validate_dependencies(
        self,
        nodes: Dict[str, Any],
        dependencies: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Validate dependency graph for logical errors.
        Rules:
          1. Each V must have exactly one D incoming edge
          2. No cycles (direct or indirect)
          3. No isolated nodes (except d type)
          4. No bidirectional edges, D->I, I->D, or V->D edges

        Args:
            nodes: All nodes grouped by type {d, D, V, I}
            dependencies: List of edges [{from, to, type}]

        Returns:
            List of error dicts: [{rule, severity, message, nodes}]
        """
        errors = []

        all_node_ids = set()
        node_type_map = {}
        for ntype, nlist in nodes.items():
            for n in nlist:
                nid = n["id"]
                all_node_ids.add(nid)
                node_type_map[nid] = ntype

        # Build adjacency maps
        outgoing = {}  # node -> [(to, type)]
        incoming = {}  # node -> [(from, type)]
        edge_pairs = set()  # set of (from, to)

        for dep in dependencies:
            f = dep.get("from", "")
            t = dep.get("to", "")
            etype = dep.get("type", "")
            if f not in outgoing:
                outgoing[f] = []
            outgoing[f].append((t, etype))
            if t not in incoming:
                incoming[t] = []
            incoming[t].append((f, etype))
            edge_pairs.add((f, t))

        # --- Rule 1: Each V must have exactly one D incoming ---
        for vnode in nodes.get("V", []):
            vid = vnode["id"]
            d_incoming = [src for src, _ in incoming.get(vid, []) if node_type_map.get(src) in ("d", "D")]
            if len(d_incoming) != 1:
                errors.append({
                    "rule": "single_d_input",
                    "severity": "error",
                    "message": f"V node '{vid}' has {len(d_incoming)} data input(s) (expected exactly 1 D/d). Found: {d_incoming if d_incoming else 'none'}",
                    "nodes": [vid]
                })

        # --- Rule 2: No cycles (DFS with white/gray/black) ---
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {nid: WHITE for nid in all_node_ids}
        parent = {}

        def dfs_cycle(start):
            """DFS to detect cycles, returns cycle path if found"""
            stack = [(start, iter(outgoing.get(start, [])))]
            color[start] = GRAY
            parent[start] = None

            while stack:
                node, children = stack[-1]
                try:
                    child, _ = next(children)
                    if child not in color:
                        # child is not in the graph at all, skip
                        continue
                    if color[child] == GRAY:
                        # Found a cycle - reconstruct path
                        cycle = [child]
                        for n in reversed([s[0] for s in stack]):
                            cycle.append(n)
                            if n == child:
                                break
                        cycle.reverse()
                        return cycle
                    if color[child] == WHITE:
                        color[child] = GRAY
                        parent[child] = node
                        stack.append((child, iter(outgoing.get(child, []))))
                except StopIteration:
                    color[node] = BLACK
                    stack.pop()
            return None

        for nid in all_node_ids:
            if color[nid] == WHITE:
                cycle = dfs_cycle(nid)
                if cycle:
                    errors.append({
                        "rule": "no_cycle",
                        "severity": "error",
                        "message": f"Cycle detected: {' -> '.join(cycle)}",
                        "nodes": cycle
                    })
                    # stop at first cycle found

        # --- Rule 3: No isolated nodes (except d type) ---
        connected_nodes = set()
        for dep in dependencies:
            connected_nodes.add(dep.get("from", ""))
            connected_nodes.add(dep.get("to", ""))

        for ntype, nlist in nodes.items():
            if ntype == "d":
                continue
            for n in nlist:
                nid = n["id"]
                if nid not in connected_nodes:
                    errors.append({
                        "rule": "no_isolated_node",
                        "severity": "error",
                        "message": f"Node '{nid}' ({ntype}) is isolated (no connections to any other node)",
                        "nodes": [nid]
                    })

        # --- Rule 4: Invalid edge types ---
        invalid_type_map = {
            "D->I": "D->I",
            "I->D": "I->D",
            "V->D": "V->D",
            "I->D": "I->D",
        }

        # Check for bidirectional edges (exclude V<->I which is intentional interaction)
        bidirectional_found = set()
        for f, t in edge_pairs:
            ftype = node_type_map.get(f, "?")
            ttype = node_type_map.get(t, "?")
            # Skip V<->I pairs — intentional interaction pattern
            if {ftype, ttype} == {"V", "I"}:
                continue
            if (t, f) in edge_pairs and (f, t) not in bidirectional_found and (t, f) not in bidirectional_found:
                bidirectional_found.add((f, t))
                errors.append({
                    "rule": "bidirectional_edge",
                    "severity": "error",
                    "message": f"Bidirectional edge detected: '{f}' ({ftype}) <-> '{t}' ({ttype})",
                    "nodes": [f, t]
                })

        for dep in dependencies:
            etype = dep.get("type", "")
            f = dep.get("from", "")
            t = dep.get("to", "")
            if etype in invalid_type_map:
                errors.append({
                    "rule": "invalid_edge_type",
                    "severity": "error",
                    "message": f"Invalid edge type '{etype}' from '{f}' to '{t}'",
                    "nodes": [f, t]
                })

        return errors

    @staticmethod
    def _cleanup_project_data(project_dir: str) -> None:
        """Remove all generated data files so a retry starts fresh."""
        import shutil
        targets = [
            "plan.json",
            "data_result.json",
            "data_tables",
            "vis_specs",
            "errors",
        ]
        for name in targets:
            path = os.path.join(project_dir, name)
            if os.path.isfile(path):
                os.remove(path)
            elif os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)

    def generate_plan(
        self,
        goal: str,
        database_schema: List[Dict[str, Any]],
        context: str = "",
        project_dir: str = ""
    ) -> Dict[str, Any]:
        """
        Generate a complete analysis plan based on goal and database schema.
        Includes two steps: refine requirements + split D/V/I nodes and dependency graph.
        If dependency validation fails, retries up to 5 times through error_agent.

        Args:
            goal: Project goal
            database_schema: Database schema information
            context: Additional context
            project_dir: Project directory (for cleaning up stale data on retry)

        Returns:
            Dict: Complete plan containing goal, refined_requirements, nodes, dependencies
        """
        # Clean up any stale generated data from previous run
        if project_dir:
            self._cleanup_project_data(project_dir)

        # Step 1: Refine requirements
        refined_requirements = self._generate_refined_requirements(
            goal, database_schema, context
        )

        # Step 2: Generate D/V/I nodes and dependency graph
        nodes_and_deps = self._generate_nodes_and_dependencies(
            goal, refined_requirements, database_schema, context
        )

        validation_errors = nodes_and_deps.get("validation_errors", [])

        # Step 3: Retry loop — two-step fix through error_agent
        if validation_errors:
            from agents.error_agent import get_error_agent
            error_agent = get_error_agent()

            req_text = "\n".join([
                f"- {r['id']}: {r['name']} - {r['description']}"
                for r in refined_requirements
            ])

            max_retries = 5
            retry_count = 0

            while validation_errors and retry_count < max_retries:
                # Step A: Analyze — determine root cause
                analysis = error_agent.analyze_plan_errors(
                    requirements_text=req_text,
                    validation_errors=validation_errors,
                    dependencies=nodes_and_deps["dependencies"],
                    nodes=nodes_and_deps["nodes"]
                )

                if not analysis.get("success"):
                    break

                diagnosis_text = (
                    f"Root cause: {analysis.get('root_cause', 'unknown')}\n"
                    f"Suggestions: {analysis.get('suggestions', '')}\n"
                    f"Affected nodes: {analysis.get('affected_nodes', [])}\n"
                    f"Explanation: {analysis.get('explanation', '')}"
                )

                needs_req_change = analysis.get("needs_requirement_change", False)

                # Step B: Apply fix based on diagnosis
                if needs_req_change:
                    # Fix requirements first
                    req_fix = error_agent.fix_requirements(
                        goal=goal,
                        current_requirements=refined_requirements,
                        nodes=nodes_and_deps["nodes"],
                        validation_errors=validation_errors,
                        diagnosis_text=diagnosis_text
                    )

                    if not req_fix.get("success"):
                        break

                    refined_requirements = req_fix["requirements"]
                    req_text = "\n".join([
                        f"- {r['id']}: {r['name']} - {r['description']}"
                        for r in refined_requirements
                    ])

                    # Regenerate nodes + dependencies from new requirements
                    nodes_and_deps = self._generate_nodes_and_dependencies(
                        goal, refined_requirements, database_schema, context
                    )
                else:
                    # Fix only the dependency graph
                    dep_fix = error_agent.fix_dependencies(
                        requirements_text=req_text,
                        nodes=nodes_and_deps["nodes"],
                        current_dependencies=nodes_and_deps["dependencies"],
                        validation_errors=validation_errors,
                        diagnosis_text=diagnosis_text
                    )

                    if not dep_fix.get("success"):
                        break

                    nodes_and_deps["dependencies"] = dep_fix["dependencies"]

                    # Re-run I-node fix
                    nodes_and_deps["dependencies"] = self._fix_i_node_dependencies(
                        nodes_and_deps["dependencies"], nodes_and_deps["nodes"]
                    )

                # Re-validate
                validation_errors = self._validate_dependencies(
                    nodes_and_deps["nodes"], nodes_and_deps["dependencies"]
                )
                nodes_and_deps["validation_errors"] = validation_errors

                retry_count += 1

        return {
            "goal": goal,
            "refined_requirements": refined_requirements,
            "nodes": nodes_and_deps["nodes"],
            "dependencies": nodes_and_deps["dependencies"],
            "validation_errors": nodes_and_deps.get("validation_errors", [])
        }


# Global Plan Agent instance
_plan_agent: Optional[PlanAgent] = None


def get_plan_agent() -> PlanAgent:
    """Get the global Plan Agent instance"""
    global _plan_agent
    if _plan_agent is None:
        _plan_agent = PlanAgent()
    return _plan_agent


def init_plan_agent(
    api_key: str = None,
    base_url: str = None,
    model_name: str = "qwen-turbo"
) -> PlanAgent:
    """Initialize the global Plan Agent"""
    global _plan_agent
    from model import init_model_client

    init_model_client(api_key=api_key, base_url=base_url)
    _plan_agent = PlanAgent(model_client=get_model_client())
    _plan_agent.model_client.set_model(model_name)
    return _plan_agent
