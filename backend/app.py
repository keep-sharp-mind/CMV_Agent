"""
Flask应用 - 与前端通信
"""

import json
import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename
from agent import get_agent, init_agent, CMVAgent
from project import get_project_store, CMVProject
from database_parser import parse_uploaded_database, get_project_databases

app = Flask(__name__)
CORS(app)  # 允许跨域请求

# 文件上传配置
ALLOWED_EXTENSIONS = {"db", "sqlite", "sqlite3", "csv"}
MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH


def get_or_init_agent() -> CMVAgent:
    """获取或初始化Agent"""
    agent = get_agent()
    if agent is None:
        # Initialize from environment variables or default config
        init_agent(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_API_BASE"),
            model_name=os.getenv("DEFAULT_MODEL", "qwen-turbo")
        )
        agent = get_agent()
    return agent


@app.route("/api/chat", methods=["POST"])
def chat():
    """
    Handle chat requests

    Request Body:
        {
            "message": "User input content",
            "temperature": 0.7  // optional
        }

    Response:
        {
            "success": true,
            "data": {
                "content": "Assistant reply",
                "model": "qwen-turbo",
                "usage": {...}
            }
        }
    """
    try:
        data = request.get_json()
        message = data.get("message", "")
        temperature = data.get("temperature", 0.7)

        if not message:
            return jsonify({
                "success": False,
                "error": "Message is required"
            }), 400

        agent = get_or_init_agent()
        result = agent.chat(message, temperature=temperature)

        return jsonify({
            "success": True,
            "data": result
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    """
    Handle streaming chat requests

    Request Body:
        {
            "message": "User input content",
            "temperature": 0.7  // optional
        }

    Response: Server-Sent Events
    """
    from flask import Response

    try:
        data = request.get_json()
        message = data.get("message", "")
        temperature = data.get("temperature", 0.7)

        if not message:
            return jsonify({
                "success": False,
                "error": "Message is required"
            }), 400

        agent = get_or_init_agent()

        def generate():
            full_response = ""
            for chunk in agent.model_client.chat_stream(
                agent.conversation.get_messages() + [{"role": "user", "content": message}],
                temperature=temperature
            ):
                full_response += chunk
                yield f"data: {chunk}\n\n"

            # Add the complete response to conversation history
            agent.conversation.add_user_message(message)
            agent.conversation.add_assistant_message(full_response)

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no"
            }
        )

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/models", methods=["GET"])
def list_models():
    """
    Get available model list

    Response:
        {
            "success": true,
            "data": {
                "qwen": ["qwen-turbo", "qwen-plus", "qwen-max"]
            }
        }
    """
    try:
        agent = get_or_init_agent()
        models = agent.get_available_models()

        return jsonify({
            "success": True,
            "data": models
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/model/set", methods=["POST"])
def set_model():
    """
    Set the current model

    Request Body:
        {
            "model": "qwen-turbo"
        }

    Response:
        {
            "success": true,
            "data": {"model": "qwen-turbo"}
        }
    """
    try:
        data = request.get_json()
        model_name = data.get("model")

        if not model_name:
            return jsonify({
                "success": False,
                "error": "Model name is required"
            }), 400

        agent = get_or_init_agent()
        success = agent.set_model(model_name)

        if success:
            return jsonify({
                "success": True,
                "data": {"model": model_name}
            })
        else:
            return jsonify({
                "success": False,
                "error": f"Model {model_name} not supported"
            }), 400

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/conversation/history", methods=["GET"])
def get_history():
    """
    Get conversation history

    Response:
        {
            "success": true,
            "data": [
                {"role": "system", "content": "..."},
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "..."}
            ]
        }
    """
    try:
        agent = get_or_init_agent()
        history = agent.get_conversation_history()

        return jsonify({
            "success": True,
            "data": history
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/conversation/clear", methods=["POST"])
def clear_conversation():
    """
    Clear conversation history

    Response:
        {
            "success": true
        }
    """
    try:
        agent = get_or_init_agent()
        agent.clear_conversation()

        return jsonify({
            "success": True
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/reset", methods=["POST"])
def reset_agent():
    """
    重置Agent

    Request Body (optional):
        {
            "system_prompt": "新的系统提示"
        }

    Response:
        {
            "success": true
        }
    """
    try:
        data = request.get_json() or {}
        system_prompt = data.get("system_prompt")

        agent = get_or_init_agent()
        agent.reset(system_prompt=system_prompt)

        return jsonify({
            "success": True
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/health", methods=["GET"])
def health_check():
    """Health check"""
    return jsonify({
        "success": True,
        "status": "healthy",
        "message": "CMV Agent is running"
    })


# ========== Project Management API ==========

@app.route("/api/projects", methods=["GET"])
def list_projects():
    """
    获取项目列表

    Response:
        {
            "success": true,
            "data": [
                {"id": "...", "name": "...", "goal": "...", "created_at": "...", "updated_at": "..."},
                ...
            ]
        }
    """
    try:
        project_store = get_project_store()
        projects = project_store.list_projects()

        return jsonify({
            "success": True,
            "data": [p.to_dict() for p in projects]
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/projects", methods=["POST"])
def create_project():
    """
    创建新项目

    Request Body:
        {
            "name": "项目名称",
            "goal": "项目目标"  // 可选
        }

    Response:
        {
            "success": true,
            "data": {"id": "...", "name": "...", ...}
        }
    """
    try:
        data = request.get_json()
        name = data.get("name", "").strip()
        goal = data.get("goal", "").strip()

        if not name:
            return jsonify({
                "success": False,
                "error": "Project name is required"
            }), 400

        project_store = get_project_store()
        project = project_store.create_project(name=name, goal=goal)

        return jsonify({
            "success": True,
            "data": project.to_dict()
        }), 201

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/projects/<project_id>", methods=["GET"])
def get_project(project_id):
    """
    Get project details

    Response:
        {
            "success": true,
            "data": {"id": "...", "name": "...", ...}
        }
    """
    try:
        project_store = get_project_store()
        project = project_store.get_project(project_id)

        if not project:
            return jsonify({
                "success": False,
                "error": "Project not found"
            }), 404

        return jsonify({
            "success": True,
            "data": project.to_dict()
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/projects/<project_id>", methods=["PUT"])
def update_project(project_id):
    """
    Update project

    Request Body:
        {
            "name": "New name",  // optional
            "goal": "New goal"    // optional
        }

    Response:
        {
            "success": true,
            "data": {"id": "...", "name": "...", ...}
        }
    """
    try:
        data = request.get_json()
        name = data.get("name")
        goal = data.get("goal")

        project_store = get_project_store()
        project = project_store.update_project(project_id, name=name, goal=goal)

        if not project:
            return jsonify({
                "success": False,
                "error": "Project not found"
            }), 404

        return jsonify({
            "success": True,
            "data": project.to_dict()
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/projects/<project_id>", methods=["DELETE"])
def delete_project(project_id):
    """
    Delete project

    Response:
        {
            "success": true
        }
    """
    try:
        project_store = get_project_store()
        success = project_store.delete_project(project_id)

        if not success:
            return jsonify({
                "success": False,
                "error": "Project not found"
            }), 404

        return jsonify({
            "success": True
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ========== Database Management API ==========

def allowed_file(filename):
    """Check if file extension is allowed"""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/api/projects/<project_id>/databases", methods=["GET"])
def list_databases(project_id):
    """
    Get project database list

    Response:
        {
            "success": true,
            "data": [
                {
                    "db_name": "...",
                    "tables": [...],
                    "uploaded_at": "..."
                },
                ...
            ]
        }
    """
    try:
        project_store = get_project_store()
        project = project_store.get_project(project_id)

        if not project:
            return jsonify({
                "success": False,
                "error": "Project not found"
            }), 404

        databases = get_project_databases(project_store, project_id)

        return jsonify({
            "success": True,
            "data": [db.to_dict() for db in databases]
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/projects/<project_id>/databases", methods=["POST"])
def upload_database(project_id):
    """
    上传数据库文件

    Request: multipart/form-data
        file: 数据库文件

    Response:
        {
            "success": true,
            "data": {
                "db_name": "...",
                "tables": [...],
                "uploaded_at": "..."
            }
        }
    """
    try:
        project_store = get_project_store()
        project = project_store.get_project(project_id)

        if not project:
            return jsonify({
                "success": False,
                "error": "Project not found"
            }), 404

        if "file" not in request.files:
            return jsonify({
                "success": False,
                "error": "No file provided"
            }), 400

        file = request.files["file"]

        if file.filename == "":
            return jsonify({
                "success": False,
                "error": "No file selected"
            }), 400

        if not allowed_file(file.filename):
            return jsonify({
                "success": False,
                "error": "Invalid file type. Only .db, .sqlite, .sqlite3, .csv files are allowed"
            }), 400

        filename = secure_filename(file.filename)
        file_data = file.read()

        db_info = parse_uploaded_database(
            file_data=file_data,
            filename=filename,
            project_id=project_id,
            project_store=project_store
        )

        return jsonify({
            "success": True,
            "data": db_info.to_dict()
        }), 201

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/projects/<project_id>/databases/<db_name>", methods=["DELETE"])
def delete_database(project_id, db_name):
    """
    Delete database from project

    Response:
        {
            "success": true
        }
    """
    try:
        project_store = get_project_store()
        project = project_store.get_project(project_id)

        if not project:
            return jsonify({
                "success": False,
                "error": "Project not found"
            }), 404

        # 从database.json中移除
        db_file_path = project_store.get_project_path(project_id, "database.json")
        if os.path.exists(db_file_path):
            with open(db_file_path, "r", encoding="utf-8") as f:
                db_data = json.load(f)

            original_count = len(db_data["databases"])
            db_data["databases"] = [
                db for db in db_data["databases"]
                if db["db_name"] != db_name
            ]

            if len(db_data["databases"]) == original_count:
                return jsonify({
                    "success": False,
                    "error": "Database not found"
                }), 404

            project_store.save_project_file(project_id, "database.json", db_data)

        return jsonify({
            "success": True
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ========== Plan Generation API ==========

def _build_db_schema(project_store, project_id):
    """Build a simplified representation of database schema for plan usage"""
    from database_parser import get_project_databases
    databases = get_project_databases(project_store, project_id)

    db_schema = []
    for db in databases:
        db_info = {"db_name": db.db_name, "tables": []}
        for table in db.tables:
            table_info = {
                "table_name": table["table_name"],
                "row_count": table["row_count"],
                "columns": [
                    {
                        "column_name": col["column_name"],
                        "data_type": col["data_type"],
                        "value_range": col.get("value_range", {})
                    }
                    for col in table["columns"]
                ]
            }
            db_info["tables"].append(table_info)
        db_schema.append(db_info)
    return db_schema


@app.route("/api/projects/<project_id>/plan", methods=["GET"])
def get_plan(project_id):
    """
    Get saved analysis plan

    Response:
        {
            "success": true,
            "data": {
                "goal": "...",
                "refined_requirements": [...],
                "nodes": { "d": [...], "D": [...], "V": [...], "I": [...] },
                "dependencies": [...]
            } | null
        }
    """
    try:
        project_store = get_project_store()
        project = project_store.get_project(project_id)

        if not project:
            return jsonify({
                "success": False,
                "error": "Project not found"
            }), 404

        plan_data = project_store.load_project_file(project_id, "plan.json")

        return jsonify({
            "success": True,
            "data": plan_data
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/projects/<project_id>/plan/generate-goal", methods=["POST"])
def generate_goal(project_id):
    """
    根据项目数据库结构生成概括性的项目目标
    当项目没有设置goal时调用
    """
    try:
        project_store = get_project_store()
        project = project_store.get_project(project_id)

        if not project:
            return jsonify({
                "success": False,
                "error": "Project not found"
            }), 404

        db_schema = _build_db_schema(project_store, project_id)
        if not db_schema:
            return jsonify({
                "success": False,
                "error": "No database uploaded. Please upload a database first."
            }), 400

        agent = get_or_init_agent()
        result = agent.generate_goal(db_schema)

        if result.get("goal"):
            project_store.update_project(project_id, goal=result["goal"])
            result["saved"] = True

        return jsonify({
            "success": True,
            "data": result
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/projects/<project_id>/plan", methods=["POST"])
def generate_plan(project_id):
    """
    Generate analysis plan
    If the project has no goal, it will auto-generate the goal first.
    After generation, save to plan.json

    Request Body (optional):
        {
            "context": "Additional context"
        }

    Response:
        {
            "success": true,
            "data": {
                "goal": "...",
                "refined_requirements": [...],
                "nodes": { "d": [...], "D": [...], "V": [...], "I": [...] },
                "dependencies": [...]
            }
        }
    """
    try:
        project_store = get_project_store()
        project = project_store.get_project(project_id)

        if not project:
            return jsonify({
                "success": False,
                "error": "Project not found"
            }), 404

        data = request.get_json() or {}
        context = data.get("context", "")

        goal = project.goal

        db_schema = _build_db_schema(project_store, project_id)
        if not db_schema:
            return jsonify({
                "success": False,
                "error": "No database uploaded. Please upload a database first."
            }), 400

        if not goal or goal.strip() == "":
            agent = get_or_init_agent()
            goal_result = agent.generate_goal(db_schema, context)
            goal = goal_result.get("goal", "")

            if goal:
                project_store.update_project(project_id, goal=goal)

        agent = get_or_init_agent()
        project_dir = project_store.get_project_path(project_id)
        plan_result = agent.plan(goal, db_schema, context, project_dir)

        from datetime import datetime
        plan_result["generated_at"] = datetime.now().isoformat()
        project_store.save_project_file(project_id, "plan.json", plan_result)

        # Report dependency validation errors to error_agent
        validation_errors = plan_result.get("validation_errors", [])
        if validation_errors:
            from agents.error_agent import get_error_agent
            project_dir = project_store.get_project_path(project_id)
            error_agent = get_error_agent(project_dir)
            for verr in validation_errors:
                error_agent.handle_error(
                    error_context={
                        "node": {"id": "|".join(verr.get("nodes", []))},
                        "execution_result": {
                            "success": False,
                            "validation_issues": [{
                                "type": verr["rule"],
                                "count": 1,
                                "columns": str(verr.get("nodes", []))
                            }],
                            "syntax_check": {"valid": False, "error": verr["message"]}
                        }
                    },
                    source_tag="plan_validation"
                )

        return jsonify({
            "success": True,
            "data": plan_result
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ========== Data Processing API ==========

@app.route("/api/projects/<project_id>/data/process", methods=["POST"])
def process_data(project_id):
    """
    Process all D (data processing) nodes in dependency order.
    Generates Python code, executes it, saves intermediate tables as CSV.

    Response:
        {
            "success": true,
            "data": {
                "processed_nodes": { "D1": {code, output_path, columns, row_count, success, error}, ... },
                "d_table_paths": { "d1": "path/to/d1.csv", ... }
            }
        }
    """
    try:
        project_store = get_project_store()
        project = project_store.get_project(project_id)

        if not project:
            return jsonify({
                "success": False,
                "error": "Project not found"
            }), 404

        plan_data = project_store.load_project_file(project_id, "plan.json")
        if not plan_data:
            return jsonify({
                "success": False,
                "error": "No plan found. Generate a plan first."
            }), 400

        db_schema = _build_db_schema(project_store, project_id)
        project_dir = project_store.get_project_path(project_id)

        agent = get_or_init_agent()
        result = agent.process_data(plan_data, db_schema, project_dir)

        all_table_paths = result.get("all_table_paths", {})
        vis_result = agent.process_visualizations(
            plan_data, db_schema, project_dir, all_table_paths
        )

        data_result = {
            "processed_nodes": result["processed_nodes"],
            "d_table_paths": result["d_table_paths"],
            "all_table_paths": all_table_paths,
            "processed_vis": vis_result.get("processed_vis", {})
        }
        project_store.save_project_file(project_id, "data_result.json", data_result)

        return jsonify({
            "success": True,
            "data": data_result
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/projects/<project_id>/data/process/node/<node_id>", methods=["POST"])
def process_single_d_node(project_id, node_id):
    """
    Process a single D node independently.
    Loads plan.json for node info, data_result.json for accumulated state (if any),
    processes the node, then saves the updated state.

    Response:
        {
            "success": true,
            "data": { node result }
        }
    """
    try:
        project_store = get_project_store()
        project = project_store.get_project(project_id)
        if not project:
            return jsonify({"success": False, "error": "Project not found"}), 404

        plan_data = project_store.load_project_file(project_id, "plan.json")
        if not plan_data:
            return jsonify({"success": False, "error": "No plan found"}), 400

        nodes = plan_data.get("nodes", {})
        dependencies = plan_data.get("dependencies", [])
        d_nodes = nodes.get("d", [])
        D_nodes = nodes.get("D", [])

        target_node = None
        for n in D_nodes:
            if n["id"] == node_id:
                target_node = n
                break
        if not target_node:
            return jsonify({"success": False, "error": f"D node {node_id} not found"}), 404

        # Load or initialize data_result
        data_result = project_store.load_project_file(project_id, "data_result.json")
        if not data_result:
            db_schema = _build_db_schema(project_store, project_id)
            project_dir = project_store.get_project_path(project_id)
            d_table_paths = {}
            for dn in d_nodes:
                source_table = dn.get("source_table", "")
                if source_table:
                    db_dir = os.path.join(project_dir, "databases")
                    csv_path = None
                    if os.path.exists(db_dir):
                        for fname in os.listdir(db_dir):
                            if fname.endswith(".csv"):
                                base_name = os.path.splitext(fname)[0]
                                if base_name in source_table or source_table.endswith(f".{base_name}"):
                                    csv_path = os.path.join(db_dir, fname)
                                    break
                    if csv_path:
                        d_table_paths[dn["id"]] = csv_path
            data_result = {
                "processed_nodes": {},
                "d_table_paths": d_table_paths,
                "all_table_paths": dict(d_table_paths)
            }

        processed_nodes = data_result.get("processed_nodes", {})
        all_table_paths = data_result.get("all_table_paths", {})

        # Build input info for this node
        input_node_ids = []
        for dep in dependencies:
            if dep.get("to") == node_id and dep.get("type") in ("d->D", "D->D"):
                input_node_ids.append(dep.get("from"))

        all_plan_nodes = d_nodes + D_nodes
        input_nodes = []
        input_table_paths = {}
        for in_id in input_node_ids:
            for n in all_plan_nodes:
                if n["id"] == in_id:
                    input_nodes.append(n)
                    break
            if in_id in all_table_paths:
                input_table_paths[in_id] = all_table_paths[in_id]

        if not input_table_paths and all_table_paths:
            input_table_paths = dict(all_table_paths)
            input_nodes = []
            for nid in input_table_paths:
                for n in all_plan_nodes:
                    if n["id"] == nid:
                        input_nodes.append(n)
                        break

        db_schema = _build_db_schema(project_store, project_id)
        project_dir = project_store.get_project_path(project_id)
        data_dir = os.path.join(project_dir, "data_tables")
        os.makedirs(data_dir, exist_ok=True)

        from agents.data_agent import get_data_agent
        data_agent = get_data_agent(project_dir=project_dir)
        result = data_agent.process_d_node(
            target_node, input_nodes, input_table_paths, data_dir
        )

        processed_nodes[node_id] = result
        if result.get("success") and result.get("output_path"):
            all_table_paths[node_id] = result["output_path"]

        updated_result = {
            "processed_nodes": processed_nodes,
            "d_table_paths": data_result.get("d_table_paths", {}),
            "all_table_paths": all_table_paths,
            "processed_vis": data_result.get("processed_vis", {})
        }
        project_store.save_project_file(project_id, "data_result.json", updated_result)

        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/projects/<project_id>/data/process/result", methods=["GET"])
def get_data_result(project_id):
    """
    Get the saved data processing result.

    Response:
        {
            "success": true,
            "data": {
                "processed_nodes": { ... },
                "d_table_paths": { ... }
            }
        }
    """
    try:
        project_store = get_project_store()
        project = project_store.get_project(project_id)

        if not project:
            return jsonify({
                "success": False,
                "error": "Project not found"
            }), 404

        data_result = project_store.load_project_file(project_id, "data_result.json")
        if not data_result:
            return jsonify({
                "success": True,
                "data": null
            })

        return jsonify({
            "success": True,
            "data": data_result
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/projects/<project_id>/data/<node_id>", methods=["GET"])
def get_node_data(project_id, node_id):
    """
    Get table data for a d or D node.
    Returns column info (with value ranges) and sample rows,
    matching the richness of original table metadata.

    Query Parameters:
        limit: max rows to return (default 50)

    Response:
        {
            "success": true,
            "data": {
                "node_id": "d1" | "D1",
                "node_type": "d" | "D",
                "columns": [{column_name, data_type, is_nullable, is_primary_key, value_range}, ...],
                "rows": [...],
                "row_count": 1000
            }
        }
    """
    try:
        project_store = get_project_store()
        project = project_store.get_project(project_id)

        if not project:
            return jsonify({
                "success": False,
                "error": "Project not found"
            }), 404

        limit = int(request.args.get("limit", 50))

        csv_path = _find_node_csv_path(project_store, project_id, node_id)

        if not csv_path or not os.path.exists(csv_path):
            return jsonify({
                "success": False,
                "error": f"Table data not found for node {node_id}"
            }), 404

        import pandas as pd

        df = pd.read_csv(csv_path)
        row_count = len(df)

        sample_df = df.head(limit)
        rows = sample_df.to_dict(orient="records")

        # Load rich column metadata from data_result.json (for D nodes)
        rich_columns_map = {}
        node_type = "D" if node_id.startswith("D") else "d"
        if node_type == "D":
            data_result = project_store.load_project_file(project_id, "data_result.json")
            if data_result:
                processed = data_result.get("processed_nodes", {})
                node_data = processed.get(node_id, {})
                for col in node_data.get("columns", []):
                    rich_columns_map[col["column_name"]] = col

        # Build column info with rich metadata if available
        columns = []
        for col in df.columns:
            col_dtype = str(df[col].dtype)
            col_info = {
                "column_name": col,
                "data_type": col_dtype,
                "is_nullable": bool(df[col].isna().any()),
                "is_primary_key": False
            }

            # Merge rich metadata from data_agent if available
            if col in rich_columns_map:
                rc = rich_columns_map[col]
                if "is_nullable" in rc:
                    col_info["is_nullable"] = rc["is_nullable"]
                if "is_primary_key" in rc:
                    col_info["is_primary_key"] = rc["is_primary_key"]
                if "value_range" in rc:
                    col_info["value_range"] = rc["value_range"]
            else:
                # Compute value_range on the fly
                numeric_types = ("int", "float", "Int64", "Float64")
                if any(t in col_dtype.lower() for t in numeric_types):
                    non_null = df[col].dropna()
                    if len(non_null) > 0:
                        col_info["value_range"] = {
                            "type": "numeric",
                            "min": float(non_null.min()),
                            "max": float(non_null.max())
                        }
                    else:
                        col_info["value_range"] = {"type": "numeric", "min": None, "max": None}
                else:
                    unique_vals = df[col].dropna().unique().tolist()
                    col_info["value_range"] = {
                        "type": "text",
                        "unique_count": len(unique_vals),
                        "sample_values": unique_vals[:20]
                    }

            columns.append(col_info)

        return jsonify({
            "success": True,
            "data": {
                "node_id": node_id,
                "node_type": node_type,
                "columns": columns,
                "rows": rows,
                "row_count": row_count
            }
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/projects/<project_id>/data/<node_id>/code", methods=["GET"])
def get_node_code(project_id, node_id):
    """
    Get the generated Python code for a D node.

    Response:
        {
            "success": true,
            "data": {
                "node_id": "D1",
                "code": "..."
            }
        }
    """
    try:
        project_store = get_project_store()
        project = project_store.get_project(project_id)

        if not project:
            return jsonify({
                "success": False,
                "error": "Project not found"
            }), 404

        data_result = project_store.load_project_file(project_id, "data_result.json")
        if not data_result:
            return jsonify({
                "success": False,
                "error": "No data processing result found. Run data processing first."
            }), 400

        processed = data_result.get("processed_nodes", {})
        node_data = processed.get(node_id)

        if not node_data:
            return jsonify({
                "success": False,
                "error": f"No code found for node {node_id}"
            }), 404

        return jsonify({
            "success": True,
            "data": {
                "node_id": node_id,
                "code": node_data.get("code", "")
            }
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/projects/<project_id>/vis/process", methods=["POST"])
def process_visualizations(project_id):
    """
    Process all V (visualization) nodes.
    Generates Vega-Lite specs, validates them, saves results.

    Response:
        {
            "success": true,
            "data": {
                "processed_vis": { "V1": {spec, metadata, spec_json, success, ...}, ... }
            }
        }
    """
    try:
        project_store = get_project_store()
        project = project_store.get_project(project_id)

        if not project:
            return jsonify({"success": False, "error": "Project not found"}), 404

        plan_data = project_store.load_project_file(project_id, "plan.json")
        if not plan_data:
            return jsonify({"success": False, "error": "No plan found"}), 400

        db_schema = _build_db_schema(project_store, project_id)
        project_dir = project_store.get_project_path(project_id)

        data_result = project_store.load_project_file(project_id, "data_result.json")
        all_table_paths = (data_result or {}).get("all_table_paths", {})

        agent = get_or_init_agent()
        vis_result = agent.process_visualizations(plan_data, db_schema, project_dir, all_table_paths)

        project_store.save_project_file(project_id, "vis_result.json", vis_result)

        return jsonify({"success": True, "data": vis_result})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/projects/<project_id>/vis/process/node/<node_id>", methods=["POST"])
def process_single_v_node(project_id, node_id):
    """
    Process a single V node independently.
    Loads data_result.json for input table paths, processes one V node,
    and accumulates into vis_result.json.

    Response:
        {
            "success": true,
            "data": { single V node result }
        }
    """
    try:
        project_store = get_project_store()
        project = project_store.get_project(project_id)
        if not project:
            return jsonify({"success": False, "error": "Project not found"}), 404

        plan_data = project_store.load_project_file(project_id, "plan.json")
        if not plan_data:
            return jsonify({"success": False, "error": "No plan found"}), 400

        nodes = plan_data.get("nodes", {})
        dependencies = plan_data.get("dependencies", [])
        v_nodes = nodes.get("V", [])

        target_node = None
        for n in v_nodes:
            if n["id"] == node_id:
                target_node = n
                break
        if not target_node:
            return jsonify({"success": False, "error": f"V node {node_id} not found"}), 404

        db_schema = _build_db_schema(project_store, project_id)
        project_dir = project_store.get_project_path(project_id)

        data_result = project_store.load_project_file(project_id, "data_result.json")
        all_table_paths = (data_result or {}).get("all_table_paths", {})

        # Build input nodes for this V node
        input_node_ids = []
        for dep in dependencies:
            if dep.get("to") == node_id and dep.get("type") in ("D->V", "V->V"):
                input_node_ids.append(dep.get("from"))

        all_plan_nodes = nodes.get("D", []) + nodes.get("V", [])
        input_nodes = []
        for in_id in input_node_ids:
            for n in all_plan_nodes:
                if n["id"] == in_id:
                    input_nodes.append(n)
                    break

        from agents.vis_agent import get_vis_agent
        vis_agent = get_vis_agent(project_dir=project_dir)
        output_dir = os.path.join(project_dir, "vis_outputs")
        os.makedirs(output_dir, exist_ok=True)

        result = vis_agent.process_v_node(target_node, input_nodes, all_table_paths, output_dir)

        # Accumulate into vis_result.json
        vis_result = project_store.load_project_file(project_id, "vis_result.json")
        processed_vis = (vis_result or {}).get("processed_vis", {})
        processed_vis[node_id] = result

        updated = {"processed_vis": processed_vis}
        project_store.save_project_file(project_id, "vis_result.json", updated)

        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/projects/<project_id>/vis/<node_id>", methods=["GET"])
def get_vis_spec(project_id, node_id):
    """
    Get the Vega-Lite spec and metadata for a V node.

    Response:
        {
            "success": true,
            "data": {
                "node_id": "V1",
                "spec": { ... },
                "spec_json": "...",
                "metadata": { ... },
                "success": true
            }
        }
    """
    try:
        project_store = get_project_store()
        project = project_store.get_project(project_id)

        if not project:
            return jsonify({"success": False, "error": "Project not found"}), 404

        vis_result = project_store.load_project_file(project_id, "vis_result.json")
        if not vis_result:
            return jsonify({"success": False, "error": "No visualization results found. Run data processing first."}), 400

        processed = vis_result.get("processed_vis", {})
        node_data = processed.get(node_id)

        if not node_data:
            return jsonify({"success": False, "error": f"No visualization found for node {node_id}"}), 404

        return jsonify({"success": True, "data": node_data})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/projects/<project_id>/agents/trace", methods=["GET"])
def get_agent_trace(project_id):
    """
    Get agent execution trace for a project.
    Reads plan.json, data_result.json, vis_result.json, and error logs
    to build a trace of all agent activities.

    Response:
        {
            "success": true,
            "data": {
                "agents": { ... },
                "active_agent": null,
                "active_nodes": []
            }
        }
    """
    try:
        project_store = get_project_store()
        project = project_store.get_project(project_id)

        if not project:
            return jsonify({"success": False, "error": "Project not found"}), 404

        plan_data = project_store.load_project_file(project_id, "plan.json")
        data_result = project_store.load_project_file(project_id, "data_result.json")
        vis_result = project_store.load_project_file(project_id, "vis_result.json")

        agents = {}

        # --- Plan Agent ---
        plan_items = []
        if plan_data:
            if plan_data.get("goal"):
                plan_items.append({
                    "id": "plan-goal",
                    "label": "Generate Goal",
                    "input": "Database Schema",
                    "output": plan_data["goal"][:80] + ("..." if len(plan_data.get("goal", "")) > 80 else ""),
                    "status": "success"
                })

            reqs = plan_data.get("refined_requirements", [])
            if reqs:
                req_summary = ", ".join(r["id"] for r in reqs)
                plan_items.append({
                    "id": "plan-requirements",
                    "label": "Refine Requirements",
                    "input": "Goal + Schema",
                    "output": f"{len(reqs)} requirements: {req_summary}",
                    "status": "success"
                })

            nodes = plan_data.get("nodes", {})
            if nodes:
                counts = {k: len(v) for k, v in nodes.items() if isinstance(v, list)}
                summary = ", ".join(f"{k}{c}" for k, c in counts.items())
                plan_items.append({
                    "id": "plan-nodes",
                    "label": "Generate Nodes & Dependencies",
                    "input": "Refined Requirements",
                    "output": summary,
                    "status": "success"
                })

        agents["plan"] = {
            "name": "Plan Agent",
            "status": "completed" if plan_items else "idle",
            "items": plan_items
        }

        # --- Data Agent ---
        data_items = []
        if data_result:
            processed_nodes = data_result.get("processed_nodes", {})
            for node_id, node_info in processed_nodes.items():
                node_success = node_info.get("success", False)
                output_cols = node_info.get("columns", [])
                col_summary = f"{len(output_cols)} cols" if output_cols else ""

                input_desc = ""
                # Try to find input nodes from plan
                if plan_data:
                    for dep in plan_data.get("dependencies", []):
                        if dep.get("to") == node_id:
                            input_desc = dep.get("from", "")
                            break

                data_items.append({
                    "id": node_id,
                    "label": f"{node_id}: {node_info.get('node_id', node_id)}",
                    "input": input_desc or "database",
                    "output": f"{node_id}.csv" + (f" ({col_summary})" if col_summary else ""),
                    "status": "success" if node_success else "error",
                    "error_detail": node_info.get("error") if not node_success else None
                })
        elif plan_data and plan_data.get("nodes", {}).get("D"):
            # Plan exists but data not processed yet
            agents["data"] = {
                "name": "Data Agent",
                "status": "idle",
                "items": []
            }

        if data_items:
            agents["data"] = {
                "name": "Data Agent",
                "status": "completed",
                "items": data_items
            }

        # --- Vis Agent ---
        vis_items = []
        vis_source = None
        if data_result and data_result.get("processed_vis"):
            vis_source = "data_result"
        elif vis_result and vis_result.get("processed_vis"):
            vis_source = "vis_result"

        if vis_source:
            processed_vis = (vis_result or data_result).get("processed_vis", {})
            for node_id, node_info in processed_vis.items():
                node_success = node_info.get("success", False)

                input_desc = ""
                metadata = node_info.get("metadata", {})
                used_tables = metadata.get("used_tables", [])
                if used_tables:
                    input_desc = ", ".join(used_tables)

                vis_items.append({
                    "id": node_id,
                    "label": f"{node_id}: {node_info.get('metadata', {}).get('marktype', 'chart')}",
                    "input": input_desc or "D nodes",
                    "output": f"{node_id}.json (Vega-Lite spec)" if node_success else "Failed",
                    "status": "success" if node_success else "error",
                    "error_detail": node_info.get("error") if not node_success else None
                })

        if vis_items:
            agents["vis"] = {
                "name": "Vis Agent",
                "status": "completed",
                "items": vis_items
            }
        elif plan_data and plan_data.get("nodes", {}).get("V"):
            # Plan exists but vis not processed
            agents["vis"] = {
                "name": "Vis Agent",
                "status": "idle",
                "items": []
            }

        # --- Error Agent ---
        error_items = []
        project_dir = project_store.get_project_path(project_id)
        errors_dir = os.path.join(project_dir, "errors")
        if os.path.isdir(errors_dir):
            for fname in sorted(os.listdir(errors_dir)):
                if fname.endswith(".json"):
                    fpath = os.path.join(errors_dir, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            err_data = json.load(f)

                        parts = fname.replace(".json", "").split("_")
                        source_tag = err_data.get("source_tag", parts[0] if len(parts) > 0 else "unknown")
                        node_id = err_data.get("node_id", parts[1] if len(parts) > 1 else "")

                        error_items.append({
                            "id": f"err-{node_id or fname}",
                            "label": f"{source_tag}: {node_id or fname}",
                            "input": source_tag,
                            "output": "Error log saved",
                            "status": "error",
                            "error_detail": err_data.get("summary", "")
                        })
                    except (json.JSONDecodeError, KeyError):
                        pass

        if data_items or vis_items:
            # Check for any errors in processed items
            has_errors = any(it["status"] == "error" for it in data_items + vis_items)
            if has_errors or error_items:
                agents["error"] = {
                    "name": "Error Agent",
                    "status": "completed",
                    "items": error_items if error_items else []
                }
            else:
                agents["error"] = {
                    "name": "Error Agent",
                    "status": "idle",
                    "items": []
                }

        # Only include agents that have status != idle
        result_agents = {}
        for k, v in agents.items():
            if v["status"] != "idle" or k == "error":
                result_agents[k] = v

        # Default connections between agents
        connections = [
            {"from": "plan", "to": "data"},
            {"from": "data", "to": "vis"},
            {"from": "data", "to": "error"},
            {"from": "vis", "to": "error"}
        ]

        return jsonify({
            "success": True,
            "data": {
                "agents": result_agents,
                "connections": connections,
                "active_agent": None,
                "active_nodes": []
            }
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _find_node_csv_path(project_store, project_id, node_id):
    """Find CSV path for a d or D node"""
    if node_id.startswith("D"):
        data_dir = project_store.get_project_path(project_id, "data_tables")
        csv_path = os.path.join(data_dir, f"{node_id}.csv")
        if os.path.exists(csv_path):
            return csv_path
    else:
        db_dir = project_store.get_project_path(project_id, "databases")
        if os.path.exists(db_dir):
            for fname in os.listdir(db_dir):
                fpath = os.path.join(db_dir, fname)
                if fname.endswith(".csv"):
                    base_name = os.path.splitext(fname)[0]
                    if base_name == node_id or base_name.startswith(node_id) or node_id.endswith(base_name):
                        return fpath

            for fname in os.listdir(db_dir):
                fpath = os.path.join(db_dir, fname)
                if fname.endswith(".csv"):
                    return fpath

    return None


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
