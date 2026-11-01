"""
Morocco Agri-Climate Data Platform - AI agent.

The agent talks to a vLLM server (OpenAI-compatible API) and can call tools.
Current tools: find_location.

Run from the project root:
    python -m agent.agent
"""

import json
import os

from openai import OpenAI
from agent.tools import find_location

# ---------------------------------------------------------------------------
# Config (can be overridden with environment variables)
# ---------------------------------------------------------------------------
BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1")
MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")

client = OpenAI(base_url=BASE_URL, api_key="not-needed")

# ---------------------------------------------------------------------------
# System prompt: the agent's role and rules
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are an assistant for the Morocco Agri-Climate Data Platform. "
    "When the user mentions a city or village, use the find_location tool to get its position. "
    "If several places share the same name, list them with their region and province "
    "and ask the user which one they mean. "
    "Never invent coordinates: only use numbers returned by the tools. "
    "Answer in the user's language (English, French or Arabic), short and clear."
)

# ---------------------------------------------------------------------------
# Tools: Python functions + descriptions for the model
# ---------------------------------------------------------------------------
FUNCS = {
    "find_location": find_location,
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_location",
            "description": (
                "Find the latitude and longitude of a city or village in Morocco. "
                "Use it first, before asking for the weather."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "place": {
                        "type": "string",
                        "description": "City or village name, e.g. Fes, Imouzzer Kandar",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Number of results (default 3)",
                    },
                },
                "required": ["place"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------
def call_tool(name: str, arguments: str) -> dict:
    """Run the tool requested by the model and always return a dict."""
    func = FUNCS.get(name)
    if func is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON arguments: {arguments}"}
    try:
        return func(**args)
    except Exception as e:  # keep the agent alive if a tool fails
        return {"error": f"{name} failed: {e}"}


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------
def run_agent(question: str, max_steps: int = 5, verbose: bool = True) -> str:
    """Send the question to the model, run the tools it asks for, return the final answer."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    for _ in range(max_steps):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            temperature=0.2,
        )
        msg = response.choices[0].message

        # No tool requested -> final answer
        if not msg.tool_calls:
            return msg.content

        # Keep the model's tool request in memory
        messages.append(msg.model_dump(exclude_none=True))

        # Run each requested tool and send the result back
        for tc in msg.tool_calls:
            result = call_tool(tc.function.name, tc.function.arguments)
            if verbose:
                print(f"[tool] {tc.function.name}({tc.function.arguments})")
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

    return "Max steps reached without a final answer."


# ---------------------------------------------------------------------------
# Simple chat in the terminal
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Morocco Agri-Climate agent - type 'exit' to quit")
    while True:
        question = input("\nYou: ").strip()
        if question.lower() in {"exit", "quit"}:
            break
        if question:
            print("Agent:", run_agent(question))