"""
Function calling utilities for Cognitia memory and task management.

This module provides tools for LLM function calling integration,
allowing Cognitia to execute tasks based on user requests.

v2.1+: Includes RBAC permission checking for function calls
"""

import json
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from dateutil import parser as date_parser
from loguru import logger
from pydantic import BaseModel

from .memory_manager import MemoryManager
from .models import TaskItem, TaskType

# Import permission checking (optional - for RBAC)
try:
    from ..auth.permissions import (
        check_function_permission,
        PermissionDeniedError,
    )
    RBAC_AVAILABLE = True
except ImportError:
    RBAC_AVAILABLE = False
    logger.warning("RBAC permissions not available - function calls will not be restricted")


class FunctionCall(BaseModel):
    """Represents a function call request from the LLM."""
    name: str
    arguments: Dict[str, Any]


class FunctionResult(BaseModel):
    """Represents the result of a function call."""
    success: bool
    result: Any
    message: str


class FunctionRegistry:
    """
    Registry of available functions for LLM function calling.

    v2.1+: Includes RBAC permission checking for function calls
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        user_id: Optional[str] = None,
        user_role: Optional[str] = None,
    ):
        """
        Initialize function registry.

        Args:
            memory_manager: Memory manager for task/memory operations
            user_id: User ID for permission checking (v2.1+, optional)
            user_role: User role for permission checking (v2.1+, optional)
        """
        self.memory_manager = memory_manager
        self.functions: Dict[str, Callable] = {}
        self.user_id = user_id
        self.user_role = user_role

        # Register built-in functions
        self._register_builtin_functions()

    def _register_builtin_functions(self) -> None:
        """Register all built-in functions."""
        self.register_function("create_calendar_event", self.create_calendar_event)
        self.register_function("list_calendar_events", self.list_calendar_events)
        self.register_function("create_reminder", self.create_reminder)
        self.register_function("list_reminders", self.list_reminders)
        self.register_function("create_todo", self.create_todo)
        self.register_function("list_todos", self.list_todos)
        self.register_function("search_memories", self.search_memories)
        self.register_function("get_current_time", self.get_current_time)
        self.register_function("get_weather", self.get_weather)  # Placeholder

    def register_function(self, name: str, func: Callable) -> None:
        """Register a function in the registry."""
        self.functions[name] = func

    def get_function_schema(self) -> List[Dict[str, Any]]:
        """Get JSON schema for all registered functions."""
        schemas = []

        # Define schemas for built-in functions
        schemas.extend([
            {
                "name": "create_calendar_event",
                "description": "Create a new calendar event",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Event title"},
                        "description": {"type": "string", "description": "Event description"},
                        "start_time": {"type": "string", "description": "Start time (ISO format or natural language)"},
                        "end_time": {"type": "string", "description": "End time (ISO format or natural language)"},
                        "location": {"type": "string", "description": "Event location"},
                        "attendees": {"type": "array", "items": {"type": "string"}, "description": "List of attendees"}
                    },
                    "required": ["title", "start_time"]
                }
            },
            {
                "name": "list_calendar_events",
                "description": "List upcoming calendar events",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "days_ahead": {"type": "integer", "description": "Number of days to look ahead", "default": 7}
                    }
                }
            },
            {
                "name": "create_reminder",
                "description": "Create a reminder",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Reminder title"},
                        "description": {"type": "string", "description": "Reminder description"},
                        "remind_at": {"type": "string", "description": "When to remind (ISO format or natural language)"},
                        "priority": {"type": "integer", "description": "Priority (1-5)", "default": 3}
                    },
                    "required": ["title", "remind_at"]
                }
            },
            {
                "name": "list_reminders",
                "description": "List pending reminders",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Maximum number of reminders to return", "default": 10}
                    }
                }
            },
            {
                "name": "create_todo",
                "description": "Create a todo item",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Todo title"},
                        "description": {"type": "string", "description": "Todo description"},
                        "priority": {"type": "integer", "description": "Priority (1-5)", "default": 3},
                        "due_date": {"type": "string", "description": "Due date (ISO format or natural language)"}
                    },
                    "required": ["title"]
                }
            },
            {
                "name": "list_todos",
                "description": "List todo items",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "description": "Filter by status", "enum": ["pending", "completed"]},
                        "limit": {"type": "integer", "description": "Maximum number of todos to return", "default": 20}
                    }
                }
            },
            {
                "name": "search_memories",
                "description": "Search through conversation history and memories",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "limit": {"type": "integer", "description": "Maximum number of results", "default": 5}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "get_current_time",
                "description": "Get the current date and time",
                "parameters": {"type": "object", "properties": {}}
            }
        ])

        return schemas

    def execute_function(self, function_call: FunctionCall) -> FunctionResult:
        """
        Execute a function call and return the result.

        v2.1+: Checks RBAC permissions before executing

        Args:
            function_call: The function call to execute

        Returns:
            FunctionResult with success status and result/error message
        """
        try:
            if function_call.name not in self.functions:
                return FunctionResult(
                    success=False,
                    result=None,
                    message=f"Unknown function: {function_call.name}"
                )

            # v2.1+: Check permissions if RBAC is available and user_role is set
            if RBAC_AVAILABLE and self.user_role:
                if not check_function_permission(self.user_role, function_call.name):
                    logger.warning(
                        f"Permission denied: user {self.user_id} (role: {self.user_role}) "
                        f"attempted to call {function_call.name}"
                    )
                    return FunctionResult(
                        success=False,
                        result=None,
                        message=f"Permission denied: You don't have access to {function_call.name}"
                    )

            func = self.functions[function_call.name]
            result = func(**function_call.arguments)

            logger.info(f"Function call executed: {function_call.name} by user {self.user_id}")

            return FunctionResult(
                success=True,
                result=result,
                message=f"Successfully executed {function_call.name}"
            )

        except Exception as e:
            logger.error(f"Error executing {function_call.name}: {str(e)}")
            return FunctionResult(
                success=False,
                result=None,
                message=f"Error executing {function_call.name}: {str(e)}"
            )

    # Function implementations

    def create_calendar_event(
        self,
        title: str,
        description: Optional[str] = None,
        start_time: str = None,
        end_time: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[List[str]] = None
    ) -> str:
        """Create a calendar event."""
        try:
            start_dt = self._parse_datetime(start_time)
            end_dt = self._parse_datetime(end_time) if end_time else start_dt + timedelta(hours=1)

            event = TaskItem(
                type=TaskType.CALENDAR_EVENT,
                title=title,
                description=description,
                start_time=start_dt,
                end_time=end_dt,
                location=location,
                attendees=attendees or []
            )

            event_id = self.memory_manager.add_task(event)
            return f"Calendar event '{title}' created for {start_dt.strftime('%Y-%m-%d %H:%M')}"

        except Exception as e:
            raise ValueError(f"Failed to create calendar event: {str(e)}")

    def list_calendar_events(self, days_ahead: int = 7) -> List[Dict[str, Any]]:
        """List upcoming calendar events."""
        from .models import TaskQuery, TaskType

        query = TaskQuery(
            task_type=TaskType.CALENDAR_EVENT,
            due_after=datetime.now(),
            due_before=datetime.now() + timedelta(days=days_ahead)
        )

        events = self.memory_manager.get_tasks(query)
        return [
            {
                "id": event.id,
                "title": event.title,
                "start_time": event.start_time.isoformat() if event.start_time else None,
                "end_time": event.end_time.isoformat() if event.end_time else None,
                "location": event.location,
                "description": event.description
            }
            for event in events
        ]

    def create_reminder(
        self,
        title: str,
        description: Optional[str] = None,
        remind_at: str = None,
        priority: int = 3
    ) -> str:
        """Create a reminder."""
        try:
            remind_dt = self._parse_datetime(remind_at)

            reminder = TaskItem(
                type=TaskType.REMINDER,
                title=title,
                description=description,
                reminder_date=remind_dt,
                priority=priority
            )

            reminder_id = self.memory_manager.add_task(reminder)
            return f"Reminder '{title}' set for {remind_dt.strftime('%Y-%m-%d %H:%M')}"

        except Exception as e:
            raise ValueError(f"Failed to create reminder: {str(e)}")

    def list_reminders(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List pending reminders."""
        from .models import TaskQuery, TaskType, TaskStatus

        query = TaskQuery(
            task_type=TaskType.REMINDER,
            status=TaskStatus.PENDING,
            limit=limit
        )

        reminders = self.memory_manager.get_tasks(query)
        return [
            {
                "id": reminder.id,
                "title": reminder.title,
                "reminder_date": reminder.reminder_date.isoformat() if reminder.reminder_date else None,
                "priority": reminder.priority,
                "description": reminder.description
            }
            for reminder in reminders
        ]

    def create_todo(
        self,
        title: str,
        description: Optional[str] = None,
        priority: int = 3,
        due_date: Optional[str] = None
    ) -> str:
        """Create a todo item."""
        try:
            due_dt = self._parse_datetime(due_date) if due_date else None

            todo = TaskItem(
                type=TaskType.TODO,
                title=title,
                description=description,
                priority=priority,
                due_date=due_dt
            )

            todo_id = self.memory_manager.add_task(todo)
            due_text = f" due {due_dt.strftime('%Y-%m-%d')}" if due_dt else ""
            return f"Todo '{title}' created{due_text}"

        except Exception as e:
            raise ValueError(f"Failed to create todo: {str(e)}")

    def list_todos(self, status: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """List todo items."""
        from .models import TaskQuery, TaskType, TaskStatus

        query = TaskQuery(
            task_type=TaskType.TODO,
            limit=limit
        )

        if status:
            query.status = TaskStatus(status)

        todos = self.memory_manager.get_tasks(query)
        return [
            {
                "id": todo.id,
                "title": todo.title,
                "status": todo.status.value,
                "priority": todo.priority,
                "due_date": todo.due_date.isoformat() if todo.due_date else None,
                "description": todo.description
            }
            for todo in todos
        ]

    def search_memories(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search through memories."""
        from .models import MemoryQuery

        mem_query = MemoryQuery(query=query, limit=limit)
        results = self.memory_manager.search_memories(mem_query)

        return [
            {
                "content": memory.content,
                "type": memory.type.value,
                "timestamp": memory.timestamp.isoformat(),
                "similarity": score,
                "tags": memory.tags
            }
            for memory, score in results
        ]

    def get_current_time(self) -> str:
        """Get current date and time."""
        now = datetime.now()
        return now.strftime("%Y-%m-%d %H:%M:%S")

    def get_weather(self, location: Optional[str] = None) -> str:
        """Get weather information (placeholder)."""
        # This would integrate with a weather API
        return "Weather functionality not yet implemented"

    def _parse_datetime(self, datetime_str: str) -> datetime:
        """Parse datetime from various formats."""
        try:
            # Try ISO format first
            return datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
        except ValueError:
            # Try natural language parsing
            try:
                return date_parser.parse(datetime_str)
            except Exception:
                raise ValueError(f"Could not parse datetime: {datetime_str}")


def create_function_calling_prompt(function_schemas: List[Dict[str, Any]]) -> str:
    """Create a system prompt that includes function calling instructions."""
    functions_json = json.dumps(function_schemas, indent=2)

    return f"""You are Cognitia, a helpful AI assistant with access to various tools and functions.

You have access to the following functions:
{functions_json}

When a user asks you to perform an action that requires using one of these functions, respond with a JSON object containing the function name and arguments. The JSON should be in this format:
{{"function_call": {{"name": "function_name", "arguments": {{"arg1": "value1", "arg2": "value2"}}}}}}

If the user is just chatting or asking a question that doesn't require function calls, respond normally.

Remember to keep your responses concise and in character as Cognitia."""



