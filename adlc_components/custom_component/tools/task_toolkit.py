import json
import uuid
import threading
from pathlib import Path
from typing import Any, Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from lfx.custom.custom_component.component import Component
from lfx.io import Output, StrInput
from lfx.log.logger import logger

_task_lock = threading.Lock()

def datetime_now_iso() -> str:
    """Helper to get current time in ISO format."""
    return datetime.now(timezone.utc).isoformat()

class TaskObjectSchema(BaseModel):
    id: str = Field(..., description="Unique task identifier, e.g., T-A1B2C3")
    subject: str = Field(..., description="Short summary of the task following WHERE HOW WHY RESULT format")
    description: str = Field(default="", description="Detailed description of the task requirements")
    status: str = Field(default="pending", description="Status of the task (pending, in_progress, completed, deleted)")
    activeForm: Optional[str] = Field(default=None, description="Active form (present continuous)")
    blocks: List[str] = Field(default_factory=list, description="List of task IDs blocked by this task")
    blockedBy: List[str] = Field(default_factory=list, description="List of task IDs blocking this task")
    owner: Optional[str] = Field(default=None, description="Owner or assignee of the task")
    metadata: Optional[dict[str, Any]] = Field(default=None, description="Arbitrary metadata dictionary")
    repoURL: Optional[str] = Field(default=None, description="Repository URL")
    parentID: Optional[str] = Field(default=None, description="ID of the parent task if this is a subtask")
    threadID: str = Field(default="default", description="ID of the execution flow or thread")
    created_at: str = Field(default_factory=datetime_now_iso, description="Creation timestamp in ISO format")
    updated_at: str = Field(default_factory=datetime_now_iso, description="Last update timestamp in ISO format")

class TaskToolkitComponent(Component):
    display_name = "Task Toolkit"
    description = "Provides tools to manage tasks (TaskCreate, TaskGet, TaskList, TaskUpdate) dynamically using the run_id context."
    icon = "clipboard-list"
    add_tool_output = True

    # Hidden trigger to toggle tool mode on the UI
    inputs = [
        StrInput(name="tool_mode_trigger", show=False, tool_mode=True),
    ]



    def get_storage_path(self) -> Path:
        """Resolve the storage directory dynamically based on session_id, run_id or fallback."""
        folder_id = "default"
        if hasattr(self, "graph") and self.graph and getattr(self.graph, "session_id", None):
            folder_id = str(self.graph.session_id)
        elif hasattr(self, "_session_id") and self._session_id:
            folder_id = str(self._session_id)
        elif hasattr(self, "graph") and self.graph and getattr(self.graph, "run_id", None):
            folder_id = str(self.graph.run_id)
        
        # Resolve to user home directory to ensure write permissions
        path = Path.home() / ".langflow" / "tasks" / folder_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _load_tasks(self, storage_dir: Path) -> dict[str, TaskObjectSchema]:
        """Load all tasks from the storage directory."""
        tasks = {}
        for file in storage_dir.glob("*.json"):
            if file.suffix == ".json" and not file.name.endswith(".tmp"):
                try:
                    with open(file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict) and "id" in data:
                            task = TaskObjectSchema.model_validate(data)
                            tasks[task.id] = task
                except Exception as e:
                    logger.error(f"Error loading task file {file.name}: {e}")
        return tasks

    def _save_task_atomic(self, storage_dir: Path, task: TaskObjectSchema):
        """Save a task atomically to avoid file corruption."""
        file_path = storage_dir / f"{task.id}.json"
        temp_path = storage_dir / f"{task.id}.json.tmp"
        
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(task.model_dump_json(indent=2))
            
            # Atomic rename
            if file_path.exists():
                file_path.unlink()
            temp_path.rename(file_path)
        except Exception as e:
            logger.error(f"Error saving task atomically {task.id}: {e}")
            if temp_path.exists():
                temp_path.unlink()
            raise IOError(f"Failed to save task {task.id} atomically: {e}")

    # --- Tool Implementations ---

    def task_create(
        self,
        subject: str,
        description: Optional[str] = None,
        activeForm: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        blockedBy: Optional[List[str]] = None,
        blocks: Optional[List[str]] = None,
        repoURL: Optional[str] = None,
        parentID: Optional[str] = None,
    ) -> str:
        """Create a new task with auto-generated ID and threadID recording.
        
        Args:
            subject: Task subject (required).
            description: Task description.
            activeForm: Active form (present continuous).
            metadata: Task metadata.
            blockedBy: Task IDs blocking this task.
            blocks: Task IDs this task blocks.
            repoURL: Repository URL.
            parentID: Parent task ID.
        """
        with _task_lock:
            try:
                storage_dir = self.get_storage_path()
                task_id = f"T-{uuid.uuid4()}"
                
                thread_id = "default"
                if hasattr(self, "graph") and self.graph and getattr(self.graph, "session_id", None):
                    thread_id = str(self.graph.session_id)
                elif hasattr(self, "_session_id") and self._session_id:
                    thread_id = str(self._session_id)
                elif hasattr(self, "graph") and self.graph and getattr(self.graph, "run_id", None):
                    thread_id = str(self.graph.run_id)
                
                task = TaskObjectSchema(
                    id=task_id,
                    subject=subject,
                    description=description if description is not None else "",
                    status="pending",
                    activeForm=activeForm,
                    blocks=blocks or [],
                    blockedBy=blockedBy or [],
                    metadata=metadata,
                    repoURL=repoURL,
                    parentID=parentID,
                    threadID=thread_id,
                )

                validated_task = TaskObjectSchema.model_validate(task.model_dump())
                self._save_task_atomic(storage_dir, validated_task)
                
                # Return minimal response matching OMO spec
                return json.dumps({
                    "task": {
                        "id": validated_task.id,
                        "subject": validated_task.subject
                    }
                })
            except Exception as e:
                if isinstance(e, Exception) and "Required" in str(e):
                    return json.dumps({"error": "validation_error", "message": str(e)})
                return json.dumps({"error": "internal_error"})

    def task_get(self, id: str) -> str:
        """Retrieve a task by ID.
        
        Args:
            id: Task ID to retrieve (format: T-{uuid}).
        """
        with _task_lock:
            try:
                if not id.startswith("T-"):
                    return json.dumps({"error": "invalid_task_id"})

                storage_dir = self.get_storage_path()
                tasks = self._load_tasks(storage_dir)
                    
                task = tasks.get(id)
                return json.dumps({"task": task.model_dump() if task else None})
            except Exception as e:
                if isinstance(e, Exception) and "validation" in str(e).lower():
                    return json.dumps({"error": "invalid_arguments"})
                return json.dumps({"error": "unknown_error"})

    def task_list(self) -> str:
        """List all active tasks with summary information."""
        with _task_lock:
            try:
                storage_dir = self.get_storage_path()
                
                if not storage_dir.exists():
                    return json.dumps({"tasks": []})

                tasks = self._load_tasks(storage_dir)
                
                if not tasks:
                    return json.dumps({"tasks": []})

                # Build task map for blocker resolution
                task_map = {t.id: t for t in tasks.values()}
                
                # Filter out completed and deleted tasks
                active_tasks = [t for t in tasks.values() if t.status not in ("completed", "deleted")]
                
                # Build summary with filtered blockedBy
                summaries = []
                for task in active_tasks:
                    # Filter blockedBy to only include unresolved (non-completed) blockers
                    unresolved_blockers = [
                        blocker_id for blocker_id in task.blockedBy
                        if not task_map.get(blocker_id) or task_map[blocker_id].status != "completed"
                    ]
                            
                    summaries.append({
                        "id": task.id,
                        "subject": task.subject,
                        "status": task.status,
                        "owner": task.owner,
                        "blockedBy": unresolved_blockers,
                    })
                    
                return json.dumps({
                    "tasks": summaries,
                    "reminder": "1 task = 1 task. Maximize parallel execution by running independent tasks (tasks with empty blockedBy) concurrently."
                })
            except Exception as e:
                return json.dumps({"error": "internal_error"})

    def task_update(
        self,
        id: str,
        subject: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        activeForm: Optional[str] = None,
        owner: Optional[str] = None,
        addBlocks: Optional[List[str]] = None,
        addBlockedBy: Optional[List[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        repoURL: Optional[str] = None,
        parentID: Optional[str] = None,
    ) -> str:
        """Update an existing task with new values.
        
        Args:
            id: Task ID (required).
            subject: Task subject.
            description: Task description.
            status: Task status (pending, in_progress, completed, deleted).
            activeForm: Active form (present continuous).
            owner: Task owner (agent name).
            addBlocks: Task IDs to add to blocks (additive, not replacement).
            addBlockedBy: Task IDs to add to blockedBy (additive, not replacement).
            metadata: Task metadata to merge (set key to null/None to delete).
            repoURL: Repository URL.
            parentID: Parent task ID.
        """
        with _task_lock:
            try:
                if not id.startswith("T-"):
                    return json.dumps({"error": "invalid_task_id"})
                    
                storage_dir = self.get_storage_path()
                tasks = self._load_tasks(storage_dir)
                
                if id not in tasks:
                    return json.dumps({"error": "task_not_found"})
                    
                task = tasks[id]
                
                if subject is not None:
                    task.subject = subject
                if description is not None:
                    task.description = description
                if status is not None:
                    task.status = status
                if activeForm is not None:
                    task.activeForm = activeForm
                if owner is not None:
                    task.owner = owner
                    
                # Additive blocks: combine and deduplicate (matching OMO behavior)
                if addBlocks:
                    combined = list(dict.fromkeys(task.blocks + addBlocks))
                    task.blocks = combined
    
                # Additive blockedBy: combine and deduplicate (matching OMO behavior)
                if addBlockedBy:
                    combined = list(dict.fromkeys(task.blockedBy + addBlockedBy))
                    task.blockedBy = combined
                            
                if metadata is not None:
                    merged = {**(task.metadata or {}), **metadata}
                    # Filter out values that are None (JSON null) to delete key
                    task.metadata = {k: v for k, v in merged.items() if v is not None} or None
    
                if repoURL is not None:
                    task.repoURL = repoURL
                if parentID is not None:
                    task.parentID = parentID
    
                validated_task = TaskObjectSchema.model_validate(task.model_dump())
                validated_task.updated_at = datetime_now_iso()
                self._save_task_atomic(storage_dir, validated_task)
                
                return json.dumps({"task": validated_task.model_dump()})
            except Exception as e:
                if isinstance(e, Exception) and "Required" in str(e):
                    return json.dumps({"error": "validation_error", "message": str(e)})
                return json.dumps({"error": "internal_error"})

    # --- Langflow & Langchain Tool Binding ---

    def build_tools(self) -> list:
        """Build the list of Langchain StructuredTools."""
        return [
            StructuredTool.from_function(
                func=self.task_create,
                name="task_create",
                tags=["task_create"],
                description=(
                    "Create a new task with auto-generated ID and threadID recording.\n\n"
                    "Auto-generates T-{uuid} ID, records threadID from context, sets status to 'pending'.\n"
                    "Returns minimal response with task ID and subject.\n\n"
                    "**IMPORTANT - Dependency Planning for Parallel Execution:**\n"
                    "Use `blockedBy` to specify task IDs that must complete before this task can start.\n"
                    "Calculate dependencies carefully to maximize parallel execution:\n"
                    "- Tasks with no dependencies can run simultaneously\n"
                    "- Only block a task if it truly depends on another's output\n"
                    "- Minimize dependency chains to reduce sequential bottlenecks"
                ),
            ),
            StructuredTool.from_function(
                func=self.task_get,
                name="task_get",
                tags=["task_get"],
                description=(
                    "Retrieve a task by ID.\n\n"
                    "Returns the full task object including all fields: id, subject, description, "
                    "status, activeForm, blocks, blockedBy, owner, metadata, repoURL, parentID, and threadID.\n\n"
                    "Returns null if the task does not exist or the file is invalid."
                ),
            ),
            StructuredTool.from_function(
                func=self.task_list,
                name="task_list",
                tags=["task_list"],
                description=(
                    "List all active tasks with summary information.\n\n"
                    "Returns tasks excluding completed and deleted statuses by default.\n"
                    "For each task's blockedBy field, filters to only include unresolved (non-completed) blockers.\n"
                    "Returns summary format: id, subject, status, owner, blockedBy (not full description)."
                ),
            ),
            StructuredTool.from_function(
                func=self.task_update,
                name="task_update",
                tags=["task_update"],
                description=(
                    "Update an existing task with new values.\n\n"
                    "Supports updating: subject, description, status, activeForm, owner, metadata.\n"
                    "For blocks/blockedBy: use addBlocks/addBlockedBy to append (additive, not replacement).\n"
                    "For metadata: merge with existing, set key to null to delete.\n\n"
                    "**IMPORTANT - Dependency Management:**\n"
                    "Use `addBlockedBy` to declare dependencies on other tasks.\n"
                    "Properly managed dependencies enable maximum parallel execution."
                ),
            ),
        ]

    async def _get_tools(self) -> list:
        """Override base Component _get_tools to support Langflow's auto tool conversion."""
        return self.build_tools()
