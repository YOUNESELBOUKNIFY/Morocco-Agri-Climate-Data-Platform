"""Agent loop: the model (served by vLLM, OpenAI-compatible API) decides which tools to call."""

import json
import os

from dotenv import load_dotenv
from openai import OpenAI

from db_tools import DB_FUNCS, DB_TOOLS
from tools import FUNCS as WEATHER_FUNCS, TOOLS as WEATHER_TOOLS

load_dotenv()

client = OpenAI(base_url=os.getenv("LLM_BASE_URL", "http://localhost:8000/v1"),
                api_key=os.getenv("LLM_API_KEY", "x"))
MODEL = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")

TOOLS = WEATHER_TOOLS + DB_TOOLS
FUNCS = {**WEATHER_FUNCS, **DB_FUNCS}

SYSTEM = (
    "Tu es un assistant agricole et météo pour le Maroc.\n"
    "- Pour la météo d'un lieu, utilise meteo_ville ; pour une région, meteo_region.\n"
    "- Pour un conseil d'arrosage, récupère d'abord la météo, puis appelle conseil_irrigation.\n"
    "- Pour trouver où se trouve un lieu, utilise find_location.\n"
    "- Pour analyser ou nettoyer la base de données, utilise run_select pour mesurer, "
    "puis run_change pour UNE correction à la fois. N'invente jamais de valeurs manquantes.\n"
    "N'invente jamais de chiffres : utilise seulement les résultats des outils. "
    "Réponds dans la langue de l'utilisateur, de façon courte et claire."
)


def agent(question: str, max_steps: int = 8, verbose: bool = True) -> str:
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": question}]
    for _ in range(max_steps):
        msg = client.chat.completions.create(
            model=MODEL, messages=messages, tools=TOOLS, temperature=0.2
        ).choices[0].message
        if not msg.tool_calls:  # no tool requested -> final answer
            return msg.content
        messages.append(msg.model_dump(exclude_none=True))
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
                result = FUNCS[name](**args) if name in FUNCS else {"erreur": f"Outil inconnu : {name}"}
            except Exception as e:
                args, result = {}, {"erreur": f"{type(e).__name__}: {e}"}
            if verbose:
                print(f"🔧 {name}({args})")
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": result if isinstance(result, str)
                             else json.dumps(result, ensure_ascii=False)})
    return "Nombre max d'étapes atteint."


if __name__ == "__main__":
    print(agent("Quel temps fera-t-il demain à Fritissa ?"))