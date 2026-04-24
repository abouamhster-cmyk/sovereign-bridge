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

def send_to_notion(table_key: str, data: Dict):
    db_id = DATABASE_IDS.get(table_key)
    if not db_id: return False, "Tableau introuvable"

    # Noms exacts vérifiés sur tes captures
    title_map = {
        "inbox": "Item", "mission": "Mission Name", "task": "Task",
        "spending": "Expense", "infrastructure": "Asset", "revenue": "Source",
        "team": "Name", "family": "Item", "kids": "Document Name", # Modifié ici
        "move": "Task", "wins": "Win"
    }
    
    title_col = title_map.get(table_key, "Name")
    notion_props = {title_col: {"title": [{"text": {"content": data.get("title", "Sans titre")}}]}}

    # Mapping financier
    if table_key == "spending" and "amount" in data:
        notion_props["Amount (CFA/USD)"] = {"number": data["amount"]}
    if table_key == "revenue" and "amount" in data:
        notion_props["Amount Received"] = {"number": data["amount"]}

    # Mapping dates
    if table_key in ["family", "task", "wins"] and "date" in data:
        notion_props["Date"] = {"date": {"start": data["date"]}}

    try:
        res = requests.post("https://api.notion.com/v1/pages", headers=headers, json={"parent": {"database_id": db_id}, "properties": notion_props})
        if res.status_code == 200:
            return True, "Success"
        else:
            logger.error(f"NOTION API ERROR for {table_key}: {res.text}")
            return False, res.text
    except Exception as e:
        return False, str(e)

# --- TOOLS ---
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

class ChatRequest(BaseModel):
    messages: List[Dict]

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    response = client.chat.completions.create(model="gpt-4o", messages=request.messages, tools=tools)
    msg = response.choices[0].message
    
    if msg.tool_calls:
        for tool_call in msg.tool_calls:
            args = json.loads(tool_call.function.arguments)
            success, error_msg = send_to_notion(args["table_key"], args)
            if success:
                return {"reply": f"C'est fait, Rebecca. J'ai mis à jour votre {args['table_key']}."}
            else:
                return {"reply": f"Rebecca, j'ai tenté d'écrire dans {args['table_key']} mais Notion a renvoyé une erreur : {error_msg}. Vérifiez les noms des colonnes."}

    return {"reply": msg.content}
