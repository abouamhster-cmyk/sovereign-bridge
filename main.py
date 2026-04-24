import os
import requests
import json
from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI
from typing import List, Optional

app = FastAPI()

# Configuration
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

# --- FONCTION D'ÉCRITURE NOTION ---
def call_notion_api(table_key, title_val, properties=None):
    db_id = DATABASE_IDS.get(table_key)
    if not db_id: return "Tableau introuvable."
    
    # Définition du nom de la colonne titre selon la table
    title_mapping = {
        "task": "Task", "inbox": "Item", "mission": "Mission Name",
        "spending": "Expense", "revenue": "Source", "family": "Item",
        "kids": "Document", "move": "Task", "wins": "Win", "team": "Name",
        "infrastructure": "Asset"
    }
    title_col = title_mapping.get(table_key, "Name")
    
    url = "https://api.notion.com/v1/pages"
    payload = {
        "parent": {"database_id": db_id},
        "properties": {
            title_col: {"title": [{"text": {"content": title_val}}]}
        }
    }
    # Ajout d'autres propriétés (comme le montant) si nécessaire
    if properties:
        for k, v in properties.items():
            if isinstance(v, (int, float)):
                payload["properties"][k] = {"number": v}
            else:
                payload["properties"][k] = {"select": {"name": v}}

    res = requests.post(url, headers=headers, json=payload)
    return res.json()

# --- DÉFINITION DES OUTILS POUR L'IA ---
tools = [{
    "type": "function",
    "function": {
        "name": "update_rebecca_empire",
        "description": "Enregistre une information dans le Notion de Rebecca",
        "parameters": {
            "type": "object",
            "properties": {
                "table_key": {"type": "string", "enum": list(DATABASE_IDS.keys())},
                "title_val": {"type": "string", "description": "Le texte principal à enregistrer"},
                "amount": {"type": "number", "description": "Si c'est de l'argent (dépense ou revenu)"}
            },
            "required": ["table_key", "title_val"]
        }
    }
}]

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    # Appel OpenAI avec les outils
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": m.role, "content": m.content} for m in request.messages],
        tools=tools,
        tool_choice="auto"
    )
    
    response_message = response.choices[0].message
    
    # Si l'IA décide d'appeler Notion
    if response_message.tool_calls:
        for tool_call in response_message.tool_calls:
            args = json.loads(tool_call.function.arguments)
            props = {"Amount (CFA/USD)": args.get("amount")} if args.get("amount") else None
            call_notion_api(args['table_key'], args['title_val'], props)
        
        return {"reply": f"C'est fait Rebecca, j'ai mis à jour ton tableau {args['table_key']}."}

    return {"reply": response_message.content}

@app.get("/")
def health(): return {"status": "Sovereign AI Engine Live"}
