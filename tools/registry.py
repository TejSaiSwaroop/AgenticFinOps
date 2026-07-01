from typing import Dict, Any, Callable, List
import json

class ToolRegistry:
    def __init__(self, transaction_context: Dict[str, Any]):
        self.ctx = transaction_context
        self._tools: Dict[str, Dict[str, Any]] = {}

    def register(self, name: str, schema_json: dict, func: Callable):
        self._tools[name] = {
            "schema": schema_json,
            "func": func
        }

    def get_schema(self, name: str) -> dict:
        return self._tools[name]["schema"]

    def get_all_schemas(self) -> List[dict]:
        return [{"type": "function", "function": t["schema"]} for t in self._tools.values()]

    def execute(self, name: str, args: dict) -> str:
        if name not in self._tools:
            return json.dumps({"error": f"Tool '{name}' not found"})
        func = self._tools[name]["func"]
        try:
            # The function receives the args. If it needs context, we can pass it,
            # but your current functions accept exactly the LLM's parameters, so we call with **args.
            # If a function wants extra context (like transaction_id), we'd inject it here.
            return func(**args)
        except Exception as e:
            return json.dumps({"error": str(e)})