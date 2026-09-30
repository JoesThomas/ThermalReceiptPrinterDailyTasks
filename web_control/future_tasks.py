"""Private longer-term goals, stored only on the server."""
import json
import uuid
from pathlib import Path

TASKS_FILE = Path(__file__).resolve().parent.parent / "data" / "future_tasks.json"


def load_tasks():
    if not TASKS_FILE.exists():
        return []
    data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, list) or any(not isinstance(t, dict) or not all(isinstance(t.get(k), str) for k in ("id", "title", "next_step")) or not isinstance(t.get("done"), bool) for t in data):
        raise ValueError("Future tasks file is invalid; restore it before editing.")
    return data


def update_task(task_id=None, title="", next_step="", action="save"):
    tasks = load_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if task_id and task is None:
        raise ValueError("This task no longer exists. Refresh the page.")
    if action == "delete":
        tasks.remove(task)
    elif action == "toggle":
        task["done"] = not task["done"]
    else:
        title, next_step = title.strip(), next_step.strip()
        if not title or len(title) > 160 or len(next_step) > 240 or any(ord(c) < 32 for c in title + next_step):
            raise ValueError("Enter a title up to 160 characters and a next step up to 240 characters.")
        if task is None:
            if len(tasks) >= 100:
                raise ValueError("Use at most 100 future tasks.")
            task = {"id": uuid.uuid4().hex, "done": False}
            tasks.append(task)
        task.update(title=title, next_step=next_step)
    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = TASKS_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(tasks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(TASKS_FILE)
    return tasks
