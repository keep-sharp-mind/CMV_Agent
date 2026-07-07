"""
Flask应用 - 与前端通信
"""

import json
import os
from flask import Flask, request, jsonify, send_file
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


def _summarize_result_error(result):
    """Return a compact error/validation summary for trace and UI consumers."""
    if not isinstance(result, dict):
        return ""
    if result.get("error"):
        return str(result.get("error"))
    error_report = result.get("error_report") or {}
    if isinstance(error_report, dict):
        if error_report.get("summary"):
            return str(error_report.get("summary"))
        original_error = error_report.get("original_error") or {}
        if isinstance(original_error, dict) and original_error.get("error"):
            return str(original_error.get("error"))
    issues = result.get("validation_issues")
    if not issues and isinstance(error_report, dict):
        original_error = error_report.get("original_error") or {}
        issues = original_error.get("validation_issues") if isinstance(original_error, dict) else None
    if isinstance(issues, list) and issues:
        return "; ".join(
            str(issue.get("detail") or issue.get("type"))
            for issue in issues[:2]
            if isinstance(issue, dict) and (issue.get("detail") or issue.get("type"))
        )
    return ""


def _append_error_recovery_trace(project_dir, node_id, node_type, label, input_desc, result):
    """Record Error Agent diagnosis and regeneration attempts in trace.json."""
    error_report = (result or {}).get("error_report") or {}
    recovery_attempts = (result or {}).get("recovery_attempts") or error_report.get("recovery_attempts") or []
    has_error_flow = bool(error_report) or bool(recovery_attempts) or (result or {}).get("success") is False
    if not has_error_flow:
        return

    from trace_manager import append_trace_entry, make_trace_entry

    summary = _summarize_result_error(result) or "Validation failed"
    append_trace_entry(project_dir, make_trace_entry(
        step=f"error_{node_id}",
        node_type="Error",
        label=f"Diagnose {label}",
        input_desc=f"{node_type} {node_id}",
        output_desc="diagnosis",
        status="error",
        previous_error=summary,
        details={
            "source_node": node_id,
            "source_type": node_type,
            "summary": summary,
            "recovery_status": error_report.get("recovery_status", {})
        }
    ))

    for index, attempt in enumerate(recovery_attempts):
        attempt_no = attempt.get("attempt", index + 1) if isinstance(attempt, dict) else index + 1
        attempt_status = attempt.get("status", "retry") if isinstance(attempt, dict) else "retry"
        recovered = attempt_status == "recovered"
        append_trace_entry(project_dir, make_trace_entry(
            step=f"retry_{node_id}_{attempt_no}",
            node_type=node_type,
            label=f"Regenerate {label}",
            input_desc=input_desc,
            output_desc=f"{node_id} regenerated",
            status="recovered" if recovered else "error",
            is_retry=True,
            previous_error=summary,
            details={
                "source_node": node_id,
                "attempt": attempt_no,
                "attempt_status": attempt_status,
                "error": attempt.get("error") if isinstance(attempt, dict) else None,
                "diagnosis_duration_ms": attempt.get("diagnosis_duration_ms") if isinstance(attempt, dict) else None,
                "regeneration_duration_ms": attempt.get("regeneration_duration_ms") if isinstance(attempt, dict) else None,
                "phase_timings": attempt.get("phase_timings", {}) if isinstance(attempt, dict) else {}
            }
        ))


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

        # A new plan invalidates lineage computed from the previous graph.
        # Remove it before planning so failed or long-running replans cannot
        # leave stale data flow visible to clients.
        for stale_name in ("data_flow.json", "data_flow_contract.json"):
            stale_path = project_store.get_project_path(project_id, stale_name)
            if os.path.isfile(stale_path):
                os.remove(stale_path)

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
    print(f"[process_data] START project={project_id}", flush=True)
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
            "processed_vis": vis_result.get("processed_vis", {}),
            "field_semantics": result.get("field_semantics", {})
        }
        project_store.save_project_file(project_id, "data_result.json", data_result)

        # Trace batch processing
        from trace_manager import append_trace_entry, make_trace_entry
        plan_nodes = project_store.load_project_file(project_id, "plan.json").get("nodes", {})
        for node_id, node_res in result.get("processed_nodes", {}).items():
            node_info = next((n for n in plan_nodes.get("D", []) if n["id"] == node_id), None)
            append_trace_entry(project_dir, make_trace_entry(
                step=node_id, node_type="D",
                label=(node_info or {}).get("name", node_id),
                input_desc=node_id, output_desc=f"{node_id}.csv",
                status="success" if node_res.get("success") else "error"
            ))
        for node_id, node_res in vis_result.get("processed_vis", {}).items():
            node_info = next((n for n in plan_nodes.get("V", []) if n["id"] == node_id), None)
            status = "success" if node_res.get("success") else "error"
            if node_res.get("recovered"):
                status = "recovered"
            append_trace_entry(project_dir, make_trace_entry(
                step=node_id, node_type="V",
                label=(node_info or {}).get("name", node_id),
                input_desc=node_id, output_desc=f"{node_id}.json",
                status=status
            ))
        _save_data_flow(project_store, project_id, plan_data)

        print(f"[process_data] RETURN {len(result.get('processed_nodes', {}))} D-nodes processed", flush=True)
        return jsonify({
            "success": True,
            "data": data_result
        })

    except Exception as e:
        print(f"[process_data] ERROR: {e}", flush=True)
        import traceback; traceback.print_exc()
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
    print(f"[process_single_d_node] START node={node_id} project={project_id}", flush=True)
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
        from agents.data_agent import build_initial_field_semantics
        data_agent = get_data_agent(project_dir=project_dir)
        field_semantics = data_result.get("field_semantics")
        if not isinstance(field_semantics, dict) or not field_semantics:
            field_semantics = build_initial_field_semantics(
                d_nodes, db_schema
            )
        result = data_agent.process_d_node(
            target_node,
            input_nodes,
            input_table_paths,
            data_dir,
            field_semantics
        )

        processed_nodes[node_id] = result
        if result.get("field_semantics"):
            field_semantics[node_id] = result["field_semantics"]
        if result.get("success") and result.get("output_path"):
            all_table_paths[node_id] = result["output_path"]

        updated_result = {
            "processed_nodes": processed_nodes,
            "d_table_paths": data_result.get("d_table_paths", {}),
            "all_table_paths": all_table_paths,
            "processed_vis": data_result.get("processed_vis", {}),
            "field_semantics": field_semantics
        }
        project_store.save_project_file(project_id, "data_result.json", updated_result)

        from trace_manager import append_trace_entry, make_trace_entry
        input_desc = ", ".join(input_node_ids) if input_node_ids else "database"
        output_desc = f"{node_id}.csv"
        if result.get("columns"):
            output_desc += f" ({len(result['columns'])} cols)"
        append_trace_entry(project_dir, make_trace_entry(
            step=node_id, node_type="D",
            label=target_node.get("name", node_id),
            input_desc=input_desc, output_desc=output_desc,
            status="success" if result.get("success") else "error"
        ))
        _append_error_recovery_trace(
            project_dir,
            node_id,
            "D",
            target_node.get("name", node_id),
            input_desc,
            result
        )
        _save_data_flow(project_store, project_id, plan_data)

        print(f"[process_single_d_node] RETURN success={result.get('success')} node={node_id}", flush=True)
        return jsonify({"success": True, "data": result})
    except Exception as e:
        print(f"[process_single_d_node] ERROR: {e}", flush=True)
        import traceback; traceback.print_exc()
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


def _serve_csv(project_id, filename):
    """Internal: serve a CSV file for a project."""
    from project import get_project_store
    ps = get_project_store()
    project = ps.get_project(project_id)
    if not project:
        return jsonify({"success": False, "error": "Project not found"}), 404
    node_id = filename.replace('.csv', '')
    csv_path = _find_node_csv_path(ps, project_id, node_id)
    if not csv_path or not os.path.exists(csv_path):
        return jsonify({"success": False, "error": f"CSV not found for {filename}"}), 404
    return send_file(csv_path, mimetype='text/csv', as_attachment=False)


@app.route("/api/projects/<project_id>/data/<path:filename>/download", methods=["GET"])
def download_csv_data(project_id, filename):
    """
    Download CSV data file for a given node_id (e.g. D1.csv).
    Used by Vega-Lite data.url in converted specs.
    """
    try:
        return _serve_csv(project_id, filename)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/data/<project_id>/<path:filename>", methods=["GET"])
def download_csv_simple(project_id, filename):
    """Simpler URL path for CSV download: /data/<project_id>/<filename>"""
    try:
        return _serve_csv(project_id, filename)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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
                "processed_vis": { ... }
            }
        }
    """
    print(f"[process_visualizations] START project={project_id}", flush=True)
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
        vis_result = agent.process_visualizations(plan_data, db_schema, project_dir, all_table_paths, project_id)

        project_store.save_project_file(project_id, "vis_result.json", vis_result)

        # Trace V nodes in batch
        from trace_manager import append_trace_entry, make_trace_entry
        plan_nodes = plan_data.get("nodes", {}).get("V", [])
        for node_id, node_res in vis_result.get("processed_vis", {}).items():
            node_info = next((n for n in plan_nodes if n["id"] == node_id), None)
            status = "success" if node_res.get("success") else "error"
            if node_res.get("recovered"):
                status = "recovered"
            append_trace_entry(project_dir, make_trace_entry(
                step=node_id, node_type="V",
                label=(node_info or {}).get("name", node_id),
                input_desc=node_id, output_desc=f"{node_id}.json",
                status=status
            ))
        _save_data_flow(project_store, project_id, plan_data)

        print(f"[process_visualizations] RETURN {len(vis_result.get('processed_vis', {}))} V-nodes", flush=True)
        return jsonify({"success": True, "data": vis_result})

    except Exception as e:
        print(f"[process_visualizations] ERROR: {e}", flush=True)
        import traceback; traceback.print_exc()
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
            "data": { node result }
        }
    """
    print(f"[process_single_v_node] START node={node_id} project={project_id}", flush=True)
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

        result = vis_agent.process_v_node(target_node, input_nodes, all_table_paths, output_dir, project_id)

        # Accumulate into vis_result.json
        vis_result = project_store.load_project_file(project_id, "vis_result.json")
        processed_vis = (vis_result or {}).get("processed_vis", {})
        processed_vis[node_id] = result

        updated = {"processed_vis": processed_vis}
        project_store.save_project_file(project_id, "vis_result.json", updated)

        from trace_manager import append_trace_entry, make_trace_entry
        input_desc = ", ".join(input_node_ids) if input_node_ids else "D nodes"
        output_desc = f"{node_id}.json (Vega-Lite spec)"
        status = "success" if result.get("success") else "error"
        if result.get("recovered"):
            status = "recovered"
        append_trace_entry(project_dir, make_trace_entry(
            step=node_id, node_type="V",
            label=target_node.get("name", node_id),
            input_desc=input_desc, output_desc=output_desc,
            status=status
        ))
        _append_error_recovery_trace(
            project_dir,
            node_id,
            "V",
            target_node.get("name", node_id),
            input_desc,
            result
        )
        if result.get("recovered") and result.get("error_report"):
            # Add a separate trace entry for the error→retry path
            append_trace_entry(project_dir, make_trace_entry(
                step=f"re_{node_id}", node_type="V",
                label=f"retry {target_node.get('name', node_id)}",
                input_desc=input_desc,
                output_desc=f"{node_id}.json (recovered spec)",
                status="recovered", is_retry=True,
                previous_error=result.get("error", "")
            ))
        _save_data_flow(project_store, project_id, plan_data)

        print(f"[process_single_v_node] RETURN success={result.get('success')} recovered={result.get('recovered')} node={node_id}", flush=True)
        return jsonify({"success": True, "data": result})
    except Exception as e:
        print(f"[process_single_v_node] ERROR: {e}", flush=True)
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/projects/<project_id>/interactions/process", methods=["POST"])
def process_interactions(project_id):
    """
    Process all I (interaction) nodes.
    Reads plan.json (I nodes + dependencies) and vis_result.json (processed_vis),
    modifies source/target V specs for interactivity, generates JS code,
    and saves the merged result to data_result.json.

    Response:
        {
            "success": true,
            "data": {
                "interaction_results": { ... },
                "processed_vis": { ... }   # updated specs with selections + dual-layers
            }
        }
    """
    print(f"[process_interactions] START project={project_id}", flush=True)
    try:
        project_store = get_project_store()
        project = project_store.get_project(project_id)
        if not project:
            return jsonify({"success": False, "error": "Project not found"}), 404

        plan_data = project_store.load_project_file(project_id, "plan.json")
        if not plan_data:
            return jsonify({"success": False, "error": "No plan found"}), 400

        # Load accumulated vis results
        vis_result = project_store.load_project_file(project_id, "vis_result.json")
        processed_vis = (vis_result or {}).get("processed_vis", {})

        # Also try data_result.json as fallback (single-node processing may have updated it)
        if not processed_vis:
            data_result = project_store.load_project_file(project_id, "data_result.json")
            processed_vis = (data_result or {}).get("processed_vis", {})

        if not processed_vis:
            return jsonify({"success": False, "error": "No processed visualizations found. Process V nodes first."}), 400

        data_result = project_store.load_project_file(project_id, "data_result.json")
        all_table_paths = (data_result or {}).get("all_table_paths", {})

        agent = get_or_init_agent()
        project_dir = project_store.get_project_path(project_id)
        field_semantics = (data_result or {}).get("field_semantics", {})
        result = agent.process_interactions(
            plan_data,
            processed_vis,
            all_table_paths,
            project_dir,
            project_id,
            field_semantics
        )

        # Merge updated processed_vis back to data_result.json
        merged = data_result or {}
        merged["processed_vis"] = result.get("processed_vis", processed_vis)
        merged["interaction_results"] = result.get("interaction_results", {})
        project_store.save_project_file(project_id, "data_result.json", merged)

        # Trace: record each I-node
        from trace_manager import append_trace_entry, make_trace_entry
        project_dir = project_store.get_project_path(project_id)
        i_results = result.get("interaction_results", {})
        for i_id, i_info in i_results.items():
            ispec = i_info.get("interaction_spec", {})
            sv = ispec.get("source_views", [])
            cv = ispec.get("controlled_view", [])
            sv_labels = [s.get("id", "") for s in sv]
            tv_labels = [c.get("view", "") for c in cv]
            append_trace_entry(project_dir, make_trace_entry(
                step=i_id, node_type="I",
                label=f"{i_id}",
                input_desc=", ".join(sv_labels) if sv_labels else "V nodes",
                output_desc=f"JS interaction: {', '.join(tv_labels)}" if tv_labels else "interaction code",
                status="success" if i_info.get("success") else "error"
            ))
        _save_data_flow(project_store, project_id, plan_data)

        print(f"[process_interactions] RETURN success with {len(result.get('interaction_results', {}))} I-nodes", flush=True)
        return jsonify({"success": True, "data": result})
    except Exception as e:
        print(f"[process_interactions] ERROR: {e}", flush=True)
        import traceback; traceback.print_exc()
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


@app.route("/api/projects/<project_id>/interactions/<node_id>", methods=["GET"])
def get_interaction_result(project_id, node_id):
    """Get the interaction result for an I node."""
    try:
        project_store = get_project_store()
        project = project_store.get_project(project_id)
        if not project:
            return jsonify({"success": False, "error": "Project not found"}), 404

        project_dir = project_store.get_project_path(project_id)
        i_path = os.path.join(project_dir, "interactions", f"{node_id}.json")
        if not os.path.isfile(i_path):
            return jsonify({"success": False, "error": f"No interaction result found for {node_id}"}), 404

        with open(i_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify({"success": True, "data": data})
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
                        for index, attempt in enumerate(err_data.get("recovery_attempts", []) or []):
                            attempt_status = attempt.get("status", "retry")
                            error_items.append({
                                "id": f"retry-{node_id or fname}-{index}",
                                "label": f"Regenerate {node_id or fname} (attempt {attempt.get('attempt', index + 1)})",
                                "input": "Error Agent diagnosis",
                                "output": (
                                    f"Recovered output ({attempt.get('regeneration_duration_ms')} ms)"
                                    if attempt_status == "recovered" and attempt.get("regeneration_duration_ms")
                                    else "Recovered output" if attempt_status == "recovered"
                                    else f"Retry result ({attempt.get('regeneration_duration_ms')} ms)" if attempt.get("regeneration_duration_ms")
                                    else "Retry result"
                                ),
                                "status": "success" if attempt_status == "recovered" else "error",
                                "error_detail": attempt.get("error"),
                                "diagnosis_duration_ms": attempt.get("diagnosis_duration_ms"),
                                "regeneration_duration_ms": attempt.get("regeneration_duration_ms"),
                                "phase_timings": attempt.get("phase_timings", {})
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

        # --- Interaction Agent ---
        interaction_items = []
        if data_result and data_result.get("interaction_results"):
            for i_id, i_info in data_result["interaction_results"].items():
                i_success = i_info.get("success", False)
                ispec = i_info.get("interaction_spec", {})
                sv_list = ispec.get("source_views", [])
                cv_list = ispec.get("controlled_view", [])
                sv_labels = [s.get("id", "") for s in sv_list]
                tv_labels = [c.get("view", "") for c in cv_list]
                interaction_items.append({
                    "id": i_id,
                    "label": f"{i_id}: {', '.join(sv_labels)} → {', '.join(tv_labels)}",
                    "input": ", ".join(sv_labels) if sv_labels else "V nodes",
                    "output": "JS interaction code",
                    "status": "success" if i_success else "error",
                    "error_detail": i_info.get("error") if not i_success else None
                })
        if interaction_items:
            agents["interaction"] = {
                "name": "Interaction Agent",
                "status": "completed",
                "items": interaction_items
            }

        # Only include agents that have status != idle
        result_agents = {}
        for k, v in agents.items():
            if v["status"] != "idle" or k == "error" or k == "interaction":
                result_agents[k] = v

        # Default connections between agents
        connections = [
            {"from": "plan", "to": "data"},
            {"from": "data", "to": "vis"},
            {"from": "vis", "to": "interaction"},
            {"from": "vis", "to": "error"},
            {"from": "interaction", "to": "error"}
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


@app.route("/api/projects/<project_id>/planner/data-flow", methods=["GET"])
def get_data_flow(project_id):
    """
    Compute data-flow (in_fields / out_fields) for all plan nodes.

    Response:
        {
            "success": true,
            "data": {
                "V1": { "in_fields": ["D1.species",...], "out_fields": ["species"] },
                ...
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

        flow = _save_data_flow(project_store, project_id, plan_data)

        return jsonify({"success": True, "data": flow})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/projects/<project_id>/trace", methods=["GET"])
def get_trace(project_id):
    """Get the generation trace.json for a project."""
    try:
        project_store = get_project_store()
        project = project_store.get_project(project_id)
        if not project:
            return jsonify({"success": False, "error": "Project not found"}), 404

        project_dir = project_store.get_project_path(project_id)
        trace_path = os.path.join(project_dir, "trace.json")
        if not os.path.isfile(trace_path):
            return jsonify({"success": True, "data": []})

        with open(trace_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/projects/<project_id>/reset-processing", methods=["POST"])
def reset_processing(project_id):
    """
    Clear all processing artifacts (data_result.json, vis_result.json,
    trace.json, interactions/, data_tables/, vis_outputs/) but keep plan.json.
    """
    try:
        project_store = get_project_store()
        project = project_store.get_project(project_id)
        if not project:
            return jsonify({"success": False, "error": "Project not found"}), 404

        project_dir = project_store.get_project_path(project_id)

        # Promote only successful node lineage into the regeneration contract
        # before clearing artifacts. Failed nodes keep their previous contract.
        stable_flow = project_store.load_project_file(
            project_id, "data_flow.json"
        ) or {}
        stable_node_ids = _successful_artifact_node_ids(
            project_store, project_id
        )
        previous_contract = project_store.load_project_file(
            project_id, "data_flow_contract.json"
        ) or {}
        next_contract = dict(previous_contract)
        next_contract.update({
            node_id: flow
            for node_id, flow in stable_flow.items()
            if node_id in stable_node_ids and isinstance(flow, dict)
        })
        if next_contract:
            project_store.save_project_file(
                project_id, "data_flow_contract.json", next_contract
            )

        files_to_remove = ["data_result.json", "vis_result.json", "trace.json", "data_flow.json"]
        for fname in files_to_remove:
            fpath = os.path.join(project_dir, fname)
            if os.path.isfile(fpath):
                os.remove(fpath)

        dirs_to_remove = ["data_tables", "vis_outputs", "interactions", "errors"]
        for dname in dirs_to_remove:
            dpath = os.path.join(project_dir, dname)
            if os.path.isdir(dpath):
                for root, dirs, files in os.walk(dpath, topdown=False):
                    for f in files:
                        os.remove(os.path.join(root, f))
                    for d in dirs:
                        os.rmdir(os.path.join(root, d))
                os.rmdir(dpath)

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _successful_artifact_node_ids(project_store, project_id):
    """Return nodes whose latest artifacts are safe to promote as contracts."""
    plan = project_store.load_project_file(project_id, "plan.json") or {}
    nodes = plan.get("nodes") or {}
    data_result = project_store.load_project_file(
        project_id, "data_result.json"
    ) or {}
    vis_result = project_store.load_project_file(
        project_id, "vis_result.json"
    ) or {}

    stable = {
        node.get("id")
        for node in (nodes.get("d") or [])
        if node.get("id")
    }
    processed_nodes = data_result.get("processed_nodes") or {}
    stable.update(
        node.get("id")
        for node in (nodes.get("D") or [])
        if (processed_nodes.get(node.get("id")) or {}).get("success")
    )

    processed_vis = {}
    for source in (
        vis_result.get("processed_vis") or {},
        data_result.get("processed_vis") or {}
    ):
        if isinstance(source, dict):
            processed_vis.update(source)
    stable.update(
        node.get("id")
        for node in (nodes.get("V") or [])
        if (processed_vis.get(node.get("id")) or {}).get("success")
    )

    project_dir = project_store.get_project_path(project_id)
    for node in nodes.get("I") or []:
        path = os.path.join(project_dir, "interactions", f"{node.get('id')}.json")
        try:
            with open(path, "r", encoding="utf-8") as file:
                if (json.load(file) or {}).get("success"):
                    stable.add(node.get("id"))
        except (OSError, json.JSONDecodeError):
            continue
    return stable


def _save_data_flow(project_store, project_id, plan_data):
    """Compute and persist data_flow.json. Returns the flow dict or empty dict."""
    try:
        print(f"[_save_data_flow] computing for project={project_id}", flush=True)
        db_schema = _build_db_schema(project_store, project_id)
        data_result = project_store.load_project_file(project_id, "data_result.json") or {}
        vis_result = project_store.load_project_file(project_id, "vis_result.json") or {}
        # vis_result contains the latest visualization generation output, while
        # data_result may contain interaction-enhanced specs. Merge both so field
        # lineage is not lost regardless of which pipeline stage ran last.
        processed_vis = {}
        for vis_source in (
            vis_result.get("processed_vis", {}),
            data_result.get("processed_vis", {})
        ):
            if isinstance(vis_source, dict):
                processed_vis.update(vis_source)
            elif isinstance(vis_source, list):
                for vis_item in vis_source:
                    if not isinstance(vis_item, dict):
                        continue
                    vis_id = vis_item.get("node_id") or vis_item.get("id")
                    if vis_id:
                        processed_vis[vis_id] = vis_item
        processed_nodes = data_result.get("processed_nodes", {})
        interaction_results = data_result.get("interaction_results", {})
        if not isinstance(interaction_results, dict):
            interaction_results = {}
        # Per-node interaction artifacts are also persisted independently.
        # Load them as a fallback when data_result was reset or partially saved.
        for interaction_node in plan_data.get("nodes", {}).get("I", []):
            interaction_id = interaction_node.get("id")
            if not interaction_id or interaction_id in interaction_results:
                continue
            interaction_path = project_store.get_project_path(
                project_id,
                os.path.join("interactions", f"{interaction_id}.json")
            )
            if not os.path.isfile(interaction_path):
                continue
            try:
                with open(interaction_path, "r", encoding="utf-8") as file:
                    interaction_results[interaction_id] = json.load(file)
            except (OSError, json.JSONDecodeError):
                pass
        print(f"[_save_data_flow] processed_vis={len(processed_vis)} processed_nodes={len(processed_nodes)}", flush=True)
        from agents.planner_agent import get_planner_agent
        pa = get_planner_agent()
        flow = pa.analyze_data_flow(
            plan_data,
            db_schema,
            processed_vis,
            processed_nodes,
            interaction_results
        )
        project_store.save_project_file(project_id, "data_flow.json", flow)
        print(f"[_save_data_flow] saved data_flow.json with {len(flow)} nodes", flush=True)
        return flow
    except Exception as e:
        import traceback
        print(f"[_save_data_flow] FAILED: {e}", flush=True)
        traceback.print_exc()
        return {}


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
