"""
Project Management Module - CMV project data models and storage
"""

import os
import json
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime


class CMVProject:
    """CMV Project"""

    def __init__(
        self,
        name: str,
        goal: str = "",
        project_id: str = None,
        created_at: str = None,
        updated_at: str = None
    ):
        self.id = project_id or str(uuid.uuid4())
        self.name = name
        self.goal = goal
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "goal": self.goal,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CMVProject":
        return cls(
            name=data["name"],
            goal=data.get("goal", ""),
            project_id=data["id"],
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at")
        )


class ProjectStore:
    """Project repository manager"""

    def __init__(self, storage_dir: str = None):
        if storage_dir is None:
            # Default storage at backend/data/projects
            backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            storage_dir = os.path.join(backend_dir, "data", "projects")

        self.storage_dir = storage_dir
        self._ensure_storage_dir()

    def _ensure_storage_dir(self):
        """Ensure storage directory exists"""
        if not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir, exist_ok=True)

    def _get_index_file(self) -> str:
        """获取项目索引文件路径"""
        return os.path.join(self.storage_dir, "projects.json")

    def _load_index(self) -> List[Dict[str, Any]]:
        """Load project index"""
        index_file = self._get_index_file()
        if not os.path.exists(index_file):
            return []
        with open(index_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_index(self, projects: List[Dict[str, Any]]):
        """Save project index"""
        index_file = self._get_index_file()
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(projects, f, ensure_ascii=False, indent=2)

    def _get_project_dir(self, project_id: str) -> str:
        """Get project directory"""
        return os.path.join(self.storage_dir, project_id)

    def _ensure_project_dir(self, project_id: str) -> str:
        """Ensure project directory exists"""
        project_dir = self._get_project_dir(project_id)
        if not os.path.exists(project_dir):
            os.makedirs(project_dir, exist_ok=True)
        return project_dir

    def create_project(self, name: str, goal: str = "") -> CMVProject:
        """
        Create new project

        Args:
            name: Project name
            goal: Project goal

        Returns:
            CMVProject: Created project object
        """
        project = CMVProject(name=name, goal=goal)

        # Save to index
        projects = self._load_index()
        projects.append(project.to_dict())
        self._save_index(projects)

        # Create project directory and initial files
        project_dir = self._ensure_project_dir(project.id)
        with open(os.path.join(project_dir, "database.json"), "w", encoding="utf-8") as f:
            json.dump({"databases": []}, f, ensure_ascii=False, indent=2)

        return project

    def list_projects(self) -> List[CMVProject]:
        """List all projects"""
        projects_data = self._load_index()
        return [CMVProject.from_dict(p) for p in projects_data]

    def get_project(self, project_id: str) -> Optional[CMVProject]:
        """
        Get project

        Args:
            project_id: Project ID

        Returns:
            CMVProject or None
        """
        projects = self._load_index()
        for p in projects:
            if p["id"] == project_id:
                return CMVProject.from_dict(p)
        return None

    def update_project(self, project_id: str, name: str = None, goal: str = None) -> Optional[CMVProject]:
        """
        Update project

        Args:
            project_id: Project ID
            name: New name (optional)
            goal: New goal (optional)

        Returns:
            CMVProject or None
        """
        projects = self._load_index()
        for i, p in enumerate(projects):
            if p["id"] == project_id:
                if name is not None:
                    projects[i]["name"] = name
                if goal is not None:
                    projects[i]["goal"] = goal
                projects[i]["updated_at"] = datetime.now().isoformat()
                self._save_index(projects)
                return CMVProject.from_dict(projects[i])
        return None

    def delete_project(self, project_id: str) -> bool:
        """
        Delete project

        Args:
            project_id: Project ID

        Returns:
            bool: Whether deletion was successful
        """
        projects = self._load_index()
        new_projects = [p for p in projects if p["id"] != project_id]
        if len(new_projects) == len(projects):
            return False

        self._save_index(new_projects)

        # Delete project directory
        project_dir = self._get_project_dir(project_id)
        if os.path.exists(project_dir):
            import shutil
            shutil.rmtree(project_dir)

        return True

    def get_project_path(self, project_id: str, filename: str = None) -> str:
        """
        Get path of a file within a project

        Args:
            project_id: Project ID
            filename: File name (optional)

        Returns:
            File path
        """
        project_dir = self._ensure_project_dir(project_id)
        if filename:
            return os.path.join(project_dir, filename)
        return project_dir

    def save_project_file(self, project_id: str, filename: str, content: Any):
        """
        Save project file

        Args:
            project_id: Project ID
            filename: File name
            content: File content
        """
        project_dir = self._ensure_project_dir(project_id)
        file_path = os.path.join(project_dir, filename)

        if isinstance(content, (dict, list)):
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(content, f, ensure_ascii=False, indent=2)
        else:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

    def load_project_file(self, project_id: str, filename: str) -> Any:
        """
        Load project file

        Args:
            project_id: Project ID
            filename: File name

        Returns:
            File content
        """
        file_path = self.get_project_path(project_id, filename)
        if not os.path.exists(file_path):
            return None

        with open(file_path, "r", encoding="utf-8") as f:
            if filename.endswith(".json"):
                return json.load(f)
            return f.read()


# 全局项目存储实例
_project_store: Optional[ProjectStore] = None


def get_project_store() -> ProjectStore:
    """Get the global project store instance"""
    global _project_store
    if _project_store is None:
        _project_store = ProjectStore()
    return _project_store
