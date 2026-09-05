"""Built-in tools and registry for AgentArena."""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable

TOOL_REGISTRY: dict[str, Callable] = {}


def tool(fn: Callable) -> Callable:
    """Decorator that registers a function as an arena tool."""
    TOOL_REGISTRY[fn.__name__] = fn
    return fn


# ---------------------------------------------------------------------------
# Safe arithmetic evaluator
# ---------------------------------------------------------------------------

_SAFE_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    # operators
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv,
    ast.USub, ast.UAdd,
)

_OPS: dict[type, Callable] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node: ast.AST) -> float:
    if not isinstance(node, _SAFE_NODES):
        raise ValueError(f"Unsafe expression node: {type(node).__name__}")
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)):
            raise ValueError(f"Non-numeric constant: {node.value!r}")
        return node.value
    if isinstance(node, ast.BinOp):
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        op_fn = _OPS.get(type(node.op))
        if op_fn is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        return op_fn(left, right)
    if isinstance(node, ast.UnaryOp):
        operand = _safe_eval(node.operand)
        op_fn = _OPS.get(type(node.op))
        if op_fn is None:
            raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
        return op_fn(operand)
    raise ValueError(f"Unhandled node type: {type(node).__name__}")


@tool
def calculator(expression: str) -> str:
    """Evaluate a safe arithmetic expression. Returns string result."""
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid expression: {exc}") from exc
    result = _safe_eval(tree.body)
    # Return int string when result is a whole number
    if isinstance(result, float) and result.is_integer():
        return str(int(result))
    return str(result)


@tool
def web_search_stub(query: str) -> str:
    """Stub: returns a canned response to simulate web search."""
    return f"[stub] Top result for '{query}': This is a placeholder search result."


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

_TOOL_DESCRIPTIONS: dict[str, str] = {
    "calculator": "Evaluate a safe arithmetic expression and return the numeric result as a string.",
    "web_search_stub": "Search the web for a query (stub). Returns a placeholder search result.",
}

_TOOL_PARAMETERS: dict[str, dict] = {
    "calculator": {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "Arithmetic expression to evaluate."},
        },
        "required": ["expression"],
    },
    "web_search_stub": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
        },
        "required": ["query"],
    },
}


def get_tool_schemas(names: list[str], provider: str = "openai") -> list[dict]:
    """Return tool schema dicts for the given tool names.

    provider="anthropic" → Anthropic format (input_schema)
    provider="openai"    → OpenAI function-calling format
    """
    schemas = []
    for name in names:
        if name not in TOOL_REGISTRY:
            continue
        desc = _TOOL_DESCRIPTIONS.get(name, "")
        params = _TOOL_PARAMETERS.get(name, {"type": "object", "properties": {}})
        if provider == "anthropic":
            schemas.append({"name": name, "description": desc, "input_schema": params})
        else:
            schemas.append(
                {"type": "function", "function": {"name": name, "description": desc, "parameters": params}}
            )
    return schemas
