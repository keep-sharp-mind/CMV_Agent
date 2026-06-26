"""
Agent Core Logic - Control Agent behavior
"""

import os
from typing import List, Dict, Any, Optional, Callable
from model import get_model_client, ModelClient
from agents.plan_agent import get_plan_agent
from agents.data_agent import get_data_agent
from agents.vis_agent import get_vis_agent


class Message:
    """Message class"""

    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


class Conversation:
    """Conversation management"""

    def __init__(self):
        self.messages: List[Dict[str, str]] = []
        self.system_prompt: Optional[str] = None

    def set_system_prompt(self, prompt: str):
        """Set system prompt"""
        self.system_prompt = prompt
        # Rebuild message list
        self._rebuild_messages()

    def _rebuild_messages(self):
        """Rebuild message list"""
        if self.system_prompt:
            # Insert user history messages after system prompt
            new_messages = [{"role": "system", "content": self.system_prompt}]
            # 保留非system的消息
            for msg in self.messages:
                if msg["role"] != "system":
                    new_messages.append(msg)
            self.messages = new_messages

    def add_user_message(self, content: str):
        """添加用户消息"""
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str):
        """添加助手消息"""
        self.messages.append({"role": "assistant", "content": content})

    def get_messages(self) -> List[Dict[str, str]]:
        """Get message list"""
        return self.messages.copy()

    def clear(self):
        """Clear conversation history"""
        system_msg = None
        if self.messages and self.messages[0]["role"] == "system":
            system_msg = self.messages[0]["content"]
        self.messages = []
        if system_msg:
            self.messages.append({"role": "system", "content": system_msg})


class CMVAgent:
    """CMV Agent - Core Agent class"""

    def __init__(
        self,
        model_client: Optional[ModelClient] = None,
        system_prompt: Optional[str] = None
    ):
        """
        Initialize Agent

        Args:
            model_client: Model client instance
            system_prompt: System prompt
        """
        self.model_client = model_client or get_model_client()
        self.conversation = Conversation()
        if system_prompt:
            self.conversation.set_system_prompt(system_prompt)
        else:
            # Default system prompt
            self.conversation.set_system_prompt(
                "You are CMV Agent, a helpful AI assistant. "
                "You are designed to help users with various tasks including "
                "answering questions, writing code, analysis, and more."
            )

    def set_model(self, model_name: str) -> bool:
        """Set model"""
        return self.model_client.set_model(model_name)

    def get_available_models(self) -> Dict[str, List[str]]:
        """Get available models"""
        return self.model_client.get_available_models()

    def chat(self, user_input: str, temperature: float = 0.7) -> Dict[str, Any]:
        """
        Process user input and return response

        Args:
            user_input: User input
            temperature: Temperature parameter

        Returns:
            Dict: Dictionary containing response content and metadata
        """
        # Add user message
        self.conversation.add_user_message(user_input)

        # Get response
        messages = self.conversation.get_messages()
        response = self.model_client.chat(messages, temperature=temperature)

        # Add assistant message to conversation history
        self.conversation.add_assistant_message(response["content"])

        return {
            "content": response["content"],
            "model": response["model"],
            "usage": response["usage"]
        }

    def chat_stream(
        self,
        user_input: str,
        temperature: float = 0.7,
        callback: Optional[Callable[[str], None]] = None
    ) -> str:
        """
        Process user input in streaming mode

        Args:
            user_input: User input
            temperature: Temperature parameter
            callback: Optional callback function for processing each incremental output

        Returns:
            str: Complete response content
        """
        # Add user message
        self.conversation.add_user_message(user_input)

        # Get streaming response
        messages = self.conversation.get_messages()
        full_response = ""

        for chunk in self.model_client.chat_stream(messages, temperature=temperature):
            full_response += chunk
            if callback:
                callback(chunk)

        # Add assistant message to conversation history
        self.conversation.add_assistant_message(full_response)

        return full_response

    def clear_conversation(self):
        """Clear conversation history"""
        self.conversation.clear()

    def get_conversation_history(self) -> List[Dict[str, str]]:
        """Get conversation history"""
        return self.conversation.get_messages()

    def reset(self, system_prompt: Optional[str] = None):
        """
        Reset Agent

        Args:
            system_prompt: New system prompt
        """
        if system_prompt:
            self.conversation.set_system_prompt(system_prompt)
        else:
            self.conversation.clear()

    def generate_goal(
        self, database_schema: List[Dict[str, Any]], context: str = ""
    ) -> Dict[str, Any]:
        """
        Generate a high-level project goal based on database schema
        Implemented by calling plan_agent

        Args:
            database_schema: Database schema information
            context: Additional context

        Returns:
            Dict: Contains generated goal information
        """
        plan_agent = get_plan_agent()
        goal = plan_agent.generate_goal(database_schema, context)
        return {"goal": goal}

    def plan(
        self,
        goal: str,
        database_schema: List[Dict[str, Any]],
        context: str = "",
        project_dir: str = ""
    ) -> Dict[str, Any]:
        """
        Generate analysis plan
        Implemented by calling plan_agent

        Args:
            goal: Project goal
            database_schema: Database schema information
            context: Additional context
            project_dir: Project directory (for cleaning up stale data on retry)

        Returns:
            Dict: Generated plan
        """
        plan_agent = get_plan_agent()
        plan_result = plan_agent.generate_plan(goal, database_schema, context, project_dir)
        return plan_result

    def process_data(
        self,
        plan_data: Dict[str, Any],
        database_schema: List[Dict[str, Any]],
        project_dir: str
    ) -> Dict[str, Any]:
        """
        Process all D (data processing) nodes in dependency order.
        Generates Python code for each D node, executes it, and saves intermediate tables as CSV.

        Args:
            plan_data: Plan data containing nodes and dependencies
            database_schema: Database schema information
            project_dir: Project directory for saving intermediate tables

        Returns:
            Dict: {
                processed_nodes: { node_id: {code, output_path, columns, row_count, success, error} },
                d_table_paths: { node_id: csv_path }
            }
        """
        nodes = plan_data.get("nodes", {})
        dependencies = plan_data.get("dependencies", [])
        d_nodes = nodes.get("d", [])
        D_nodes = nodes.get("D", [])

        if not D_nodes:
            return {"processed_nodes": {}, "d_table_paths": {}}

        data_dir = os.path.join(project_dir, "data_tables")
        os.makedirs(data_dir, exist_ok=True)

        d_table_paths = {}
        for d_node in d_nodes:
            node_id = d_node["id"]
            source_table = d_node.get("source_table", "")
            csv_path = self._find_d_node_csv_path(d_node, database_schema, project_dir)
            if csv_path:
                d_table_paths[node_id] = csv_path

        adj = {d["id"]: [] for d in D_nodes}
        in_degree = {d["id"]: 0 for d in D_nodes}
        d_node_map = {d["id"]: d for d in D_nodes}

        for dep in dependencies:
            dep_type = dep.get("type", "")
            from_node = dep.get("from", "")
            to_node = dep.get("to", "")
            if dep_type in ("d->D", "D->D") and to_node in d_node_map:
                if from_node in d_node_map:
                    adj[from_node].append(to_node)
                    in_degree[to_node] += 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        topo_order = []
        while queue:
            curr = queue.pop(0)
            topo_order.append(curr)
            for neighbor in adj.get(curr, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        data_agent = get_data_agent(project_dir=project_dir)
        processed_nodes = {}
        all_table_paths = dict(d_table_paths)

        for node_id in topo_order:
            node = d_node_map[node_id]

            input_node_ids = []
            for dep in dependencies:
                if dep.get("to") == node_id and dep.get("type") in ("d->D", "D->D"):
                    input_node_ids.append(dep.get("from"))

            input_nodes = []
            input_table_paths = {}
            for in_id in input_node_ids:
                for dn in d_nodes + D_nodes:
                    if dn["id"] == in_id:
                        input_nodes.append(dn)
                        break
                if in_id in all_table_paths:
                    input_table_paths[in_id] = all_table_paths[in_id]

            # Fallback: if dependency graph has no data edges (e.g. LLM omitted them),
            # provide ALL available table paths so the D node can still work.
            if not input_table_paths and all_table_paths:
                input_table_paths = dict(all_table_paths)
                input_nodes = []
                for nid in input_table_paths:
                    for dn in d_nodes + D_nodes:
                        if dn["id"] == nid:
                            input_nodes.append(dn)
                            break

            result = data_agent.process_d_node(
                node, input_nodes, input_table_paths, data_dir
            )

            processed_nodes[node_id] = result
            if result.get("success") and result.get("output_path"):
                all_table_paths[node_id] = result["output_path"]

        return {
            "processed_nodes": processed_nodes,
            "d_table_paths": d_table_paths,
            "all_table_paths": all_table_paths
        }

    def process_visualizations(
        self,
        plan_data: Dict[str, Any],
        database_schema: List[Dict[str, Any]],
        project_dir: str,
        all_table_paths: Dict[str, str] = None
    ) -> Dict[str, Any]:
        """
        Process all V (visualization) nodes after data processing.
        Generates Vega-Lite specs, validates them, and saves results.

        Args:
            plan_data: Plan data containing nodes and dependencies
            database_schema: Database schema info
            project_dir: Project directory
            all_table_paths: Mapping from node_id to CSV path (from data processing)

        Returns:
            Dict: { processed_vis: { node_id: {...} }, vis_table_paths: {...} }
        """
        nodes = plan_data.get("nodes", {})
        dependencies = plan_data.get("dependencies", [])
        d_nodes = nodes.get("d", [])
        D_nodes = nodes.get("D", [])
        V_nodes = nodes.get("V", [])

        if not V_nodes:
            return {"processed_vis": {}, "vis_table_paths": {}}

        d_node_map = {n["id"]: n for n in d_nodes}
        D_node_map = {n["id"]: n for n in D_nodes}
        all_node_map = {**d_node_map, **D_node_map}

        vis_dir = os.path.join(project_dir, "vis_specs")
        os.makedirs(vis_dir, exist_ok=True)

        all_table_paths = all_table_paths or {}

        vis_agent = get_vis_agent(project_dir=project_dir)
        processed_vis = {}

        for v_node in V_nodes:
            v_id = v_node["id"]

            input_node_ids = []
            for dep in dependencies:
                if dep.get("to") == v_id and dep.get("type") in ("d->V", "D->V"):
                    input_node_ids.append(dep.get("from"))

            input_nodes = []
            input_table_paths = {}
            for in_id in input_node_ids:
                if in_id in all_node_map:
                    input_nodes.append(all_node_map[in_id])
                if in_id in all_table_paths:
                    input_table_paths[in_id] = all_table_paths[in_id]
                else:
                    csv_path = self._find_d_node_csv_path(
                        d_node_map.get(in_id, {}), database_schema, project_dir
                    )
                    if csv_path:
                        input_table_paths[in_id] = csv_path

            result = vis_agent.process_v_node(
                v_node, input_nodes, input_table_paths, vis_dir
            )
            processed_vis[v_id] = result

        return {"processed_vis": processed_vis}

    def _find_d_node_csv_path(
        self,
        d_node: Dict[str, Any],
        database_schema: List[Dict[str, Any]],
        project_dir: str
    ) -> Optional[str]:
        """
        Find the CSV file path for a d (input table) node.
        Looks in the project's databases directory.
        """
        source_table = d_node.get("source_table", "")
        if not source_table:
            return None

        db_dir = os.path.join(project_dir, "databases")
        if os.path.exists(db_dir):
            for fname in os.listdir(db_dir):
                fpath = os.path.join(db_dir, fname)
                if fname.endswith(".csv"):
                    base_name = os.path.splitext(fname)[0]
                    if base_name in source_table or source_table.endswith(f".{base_name}"):
                        return fpath

        return None


# Global Agent instance
_agent: Optional[CMVAgent] = None


def get_agent() -> CMVAgent:
    """Get the global Agent instance"""
    global _agent
    if _agent is None:
        _agent = CMVAgent()
    return _agent


def init_agent(
    api_key: str = None,
    base_url: str = None,
    model_name: str = "qwen-turbo",
    system_prompt: str = None
) -> CMVAgent:
    """Initialize the global Agent"""
    global _agent
    from model import init_model_client

    # Initialize model client
    init_model_client(api_key=api_key, base_url=base_url)

    # Create Agent
    _agent = CMVAgent(
        model_client=get_model_client(),
        system_prompt=system_prompt
    )

    # Set model
    if model_name:
        _agent.set_model(model_name)

    return _agent
