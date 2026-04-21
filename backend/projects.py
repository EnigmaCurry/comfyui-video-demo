"""Project persistence — JSON files on disk.

Each project is stored as a directory under PROJECTS_DIR:
  projects/{id}/project.json   — project metadata + keyframes
  projects/{id}/images/        — rendered keyframe images
"""

import json
import logging
import os
from datetime import datetime, timezone

from config import settings
from models import Keyframe, KeyframeStatus, Project

log = logging.getLogger(__name__)

def _resolve_projects_dir() -> str:
    if settings.projects_dir:
        return settings.projects_dir
    # Default: {repo_root}/projects
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(repo_root, "projects")


PROJECTS_DIR = _resolve_projects_dir()


def _project_dir(project_id: str) -> str:
    return os.path.join(PROJECTS_DIR, project_id)


def _project_file(project_id: str) -> str:
    return os.path.join(_project_dir(project_id), "project.json")


def images_dir(project_id: str) -> str:
    d = os.path.join(_project_dir(project_id), "images")
    os.makedirs(d, exist_ok=True)
    return d


def save_project(project: Project) -> None:
    """Write project state to disk."""
    project.updated_at = datetime.now(timezone.utc).isoformat()
    d = _project_dir(project.id)
    os.makedirs(d, exist_ok=True)
    # Don't persist transient rendering status — reset to pending or done
    data = project.model_dump()
    for kf in data["keyframes"]:
        if kf["status"] == "rendering":
            kf["status"] = "done" if kf["image_filename"] else "pending"
        kf.pop("error_message", None)
    for img in data.get("images", []):
        if img["status"] == "rendering":
            img["status"] = "done" if img["image_filename"] else "pending"
        img.pop("error_message", None)
    path = _project_file(project.id)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    log.info("Saved project %s (%s) to %s", project.id, project.name, path)


def load_project(project_id: str) -> Project | None:
    path = _project_file(project_id)
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return Project(**json.load(f))


def list_projects(activity: str | None = None) -> list[dict]:
    """Return summaries of all projects, most recent first.

    If *activity* is given, only return projects matching that activity type.
    """
    results = []
    if not os.path.isdir(PROJECTS_DIR):
        return results
    for name in os.listdir(PROJECTS_DIR):
        path = _project_file(name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path) as f:
                data = json.load(f)
            proj_activity = data.get("activity", "film-director")
            if activity and proj_activity != activity:
                continue
            results.append({
                "id": data["id"],
                "activity": proj_activity,
                "name": data.get("name", ""),
                "premise": data.get("premise", data.get("theme", "")),
                "scene_count": data.get("scene_count", 0),
                "keyframe_count": len(data.get("keyframes", [])),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    results.sort(key=lambda p: p.get("updated_at", ""), reverse=True)
    return results


def delete_project(project_id: str) -> bool:
    import shutil
    d = _project_dir(project_id)
    if os.path.isdir(d):
        shutil.rmtree(d)
        return True
    return False
