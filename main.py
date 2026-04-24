import os
import requests
import json
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from typing import List, Dict, Optional

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

# --- FONCTION DE LECTURE (POUR QUE L'IA VOIE) ---
def query_notion(table_key: str):
    db_id = DATABASE_IDS.get(table_key)
    if not db_id: return {"error": "Table non trouvée"}
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    res = requests.post(url, headers=headers)
    return res.json()

# --- FONCTION D'ÉCRITURE AMÉLIORÉE ---
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

    # Remplissage intelligent des colonnes (basé sur tes captures)
    if "amount" in data:
        prop_name = "Amount Received" if table_key == "revenue" else "Amount"
        notion_props[prop_name] = {"number": data["amount"]}
    
    if "category" in data and table_key == "spending":
        notion_props["Category"] = {"select": {"name": data["category"]}}

    if "date" in data:
        notion_props["Date"] = {"date": {"start": data["date"]}}

    # LIER UNE MISSION (Relation)
    if "mission_id" in data:
        notion_props["🎯 MISSIONS"] = {"relation": [{"id": data["mission_id"]}]}

    url = "https://api.notion.com/v1/pages"
    res = requests.post(url, headers=headers, json={"parent": {"database_id": db_id}, "properties": notion_props})
    return (True, "Success") if res.status_code == 200 else (False, res.text)

# --- CONFIGURATION DES OUTILS IA ---
tools = [
    {
        "type": "function",
        "function": {
            "name": "write_to_empire",
            "description": "Enregistre une donnée. Utilise les colonnes : title, amount, category, date, mission_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_key": {"type": "string", "enum": list(DATABASE_IDS.keys())},
                    "title": {"type": "string"},
                    "amount": {"type": "number"},
                    "category": {"type": "string"},
                    "date": {"type": "string"},
                    "mission_id": {"type": "string", "description": "ID de la mission pour lier la donnée"}
                },
                "required": ["table_key", "title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_empire_table",
            "description": "Lit le contenu d'un tableau pour faire un point ou trouver un ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_key": {"type": "string", "enum": list(DATABASE_IDS.keys())}
                },
                "required": ["table_key"]
            }
        }
    }
]

class ChatRequest(BaseModel):
    messages: List[Dict]

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=request.messages,
        tools=tools
    )
    
    msg = response.choices[0].message
    if msg.tool_calls:
        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            
            if name == "write_to_empire":
                success, feedback = send_to_notion(args["table_key"], args)
                return {"reply": f"C'est fait Rebecca. ({args['table_key']})" if success else f"Erreur : {feedback}"}
            
            if name == "read_empire_table":
                data = query_notion(args["table_key"])
                # On renvoie les données à l'IA pour qu'elle les analyse
                new_messages = request.messages + [msg, {"role": "tool", "tool_call_id": tool_call.id, "content": json.dumps(data)}]
                second_response = client.chat.completions.create(model="gpt-4o", messages=new_messages)
                return {"reply": second_response.choices[0].message.content}

    return {"reply": msg.content}

@app.get("/")
def health(): return {"status": "Sovereign Intelligence Live"}
