import os
import requests
import json
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from typing import List, Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")

DATABASE_IDS = {
    "inbox": "345a95e67e2880fa9f59cf10841aad32",
    "mission": "345a95e67e28803d8751e0d78048c3bd",
    "task": "345a95e67e28801481badd2ec8442615",
    "spending": "345a95e67e28809991f7d26de9168c09",
    "infrastructure": "345a95e67e288095852bd57abfd167f2",
    "revenue": "346a95e67e2880ab9a96ce90c44df26b",
    "team": "345a95e67e28806a9b0fec8a149ecade",
    "family": "345a95e67e2880b89ef4c839c26ecf67",
    "kids": "345a95e67e28805ab193dae4e21fe5b2",
    "move": "345a95e67e2880608e6dc46295ac3113",
    "wins": "345a95e67e288003b204ed870d366360"
}

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def get_real_columns(db_id):
    """Récupère les vrais noms des colonnes depuis Notion"""
    url = f"https://api.notion.com/v1/databases/{db_id}"
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        return list(res.json().get("properties", {}).keys())
    return []

def send_to_notion(table_key: str, data: Dict):
    db_id = DATABASE_IDS.get(table_key)
    if not db_id: return False, "Table non trouvée"

    title_map = {
        "inbox": "Item", "mission": "Mission Name", "task": "Task",
        "spending": "Expense", "infrastructure": "Asset", "revenue": "Source",
        "team": "Name", "family": "Item", "kids": "Document Name",
        "move": "Task", "wins": "Win"
    }
    
    title_col = title_map.get(table_key, "Name")
    notion_props = {title_col: {"title": [{"text": {"content": data.get("title", "Sans titre")}}]}}

    if "amount" in data:
        # On tente avec 'Amount', si ça échoue on verra dans les logs
        notion_props["Amount"] = {"number": data["amount"]}

    if "date" in data:
        notion_props["Date"] = {"date": {"start": data["date"]}}

    url = "https://api.notion.com/v1/pages"
    res = requests.post(url, headers=headers, json={"parent": {"database_id": db_id}, "properties": notion_props})
    
    if res.status_code != 200:
        real_cols = get_real_columns(db_id)
        error_msg = f"Erreur Notion. Colonnes attendues par l'API : {real_cols}. Erreur brute : {res.text}"
        logger.error(error_msg)
        return False, error_msg
    
    return True, "Success"

# --- CHAT ENDPOINT ---
class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    # DÉFINITION DES TOOLS DYNAMIQUE
    tools = [{
        "type": "function",
        "function": {
            "name": "manage_rebecca_empire",
            "description": "Enregistre une donnée dans Notion.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_key": {"type": "string", "enum": list(DATABASE_IDS.keys())},
                    "title": {"type": "string"},
                    "amount": {"type": "number"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"}
                },
                "required": ["table_key", "title"]
            }
        }
    }]

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": m.role, "content": m.content} for m in request.messages],
        tools=tools
    )
    
    msg = response.choices[0].message
    if msg.tool_calls:
        for tool_call in msg.tool_calls:
            args = json.loads(tool_call.function.arguments)
            success, feedback = send_to_notion(args["table_key"], args)
            if success:
                return {"reply": f"C'est fait Rebecca, c'est noté dans {args['table_key']}."}
            else:
                return {"reply": f"Désolé Rebecca, il y a un bug technique : {feedback}"}

    return {"reply": msg.content}

@app.get("/")
def health(): return {"status": "Sovereign Engine Live"}
