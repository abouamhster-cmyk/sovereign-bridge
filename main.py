import os
import requests
import json
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from typing import List, Dict, Optional

# Configuration des logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Configuration CORS pour ton application Next.js
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Clients et Configuration
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
    """Récupère les vrais noms des colonnes pour debug en cas d'erreur"""
    url = f"https://api.notion.com/v1/databases/{db_id}"
    res = requests.get(url, headers=headers)
    return list(res.json().get("properties", {}).keys()) if res.status_code == 200 else []

def send_to_notion(table_key: str, data: Dict):
    db_id = DATABASE_IDS.get(table_key)
    if not db_id: return False, "Table introuvable"

    # Mapping précis des colonnes Titres (Name) vérifié sur tes captures
    title_map = {
        "inbox": "Item", "mission": "Mission Name", "task": "Task",
        "spending": "Expense", "infrastructure": "Asset", "revenue": "Source",
        "team": "Name", "family": "Item", "kids": "Document Name",
        "move": "Task", "wins": "Win"
    }
    
    title_col = title_map.get(table_key, "Name")
    notion_props = {
        title_col: {"title": [{"text": {"content": data.get("title", "Sans titre")}}]}
    }

    # Logique financière (Noms de colonnes sans espaces)
    if "amount" in data:
        if table_key == "spending":
            notion_props["Amount"] = {"number": data["amount"]}
        elif table_key == "revenue":
            notion_props["Amount Received"] = {"number": data["amount"]}

    # Logique de Date
    if "date" in data:
        notion_props["Date"] = {"date": {"start": data["date"]}}

    # Logique de Status (pour move ou infrastructure)
    if "status" in data and table_key in ["move", "infrastructure"]:
        notion_props["Status"] = {"status": {"name": data["status"]}}

    try:
        url = "https://api.notion.com/v1/pages"
        res = requests.post(url, headers=headers, json={"parent": {"database_id": db_id}, "properties": notion_props})
        
        if res.status_code == 200:
            return True, "Success"
        else:
            real_cols = get_real_columns(db_id)
            error_detail = f"Erreur Notion sur '{table_key}'. Colonnes réelles: {real_cols}. Erreur: {res.text}"
            logger.error(error_detail)
            return False, error_detail
    except Exception as e:
        return False, str(e)

# --- CHAT LOGIC ---

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    # Outils disponibles pour l'IA
    tools = [{
        "type": "function",
        "function": {
            "name": "manage_rebecca_empire",
            "description": "Enregistre des données (dépenses, tâches, documents, notes) dans le Notion de Rebecca.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_key": {"type": "string", "enum": list(DATABASE_IDS.keys())},
                    "title": {"type": "string", "description": "Le texte principal"},
                    "amount": {"type": "number", "description": "Le montant si financier"},
                    "date": {"type": "string", "description": "Format YYYY-MM-DD"},
                    "status": {"type": "string", "description": "État (ex: À faire, Terminé)"}
                },
                "required": ["table_key", "title"]
            }
        }
    }]

    try:
        # Appel OpenAI
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": m.role, "content": m.content} for m in request.messages],
            tools=tools,
            tool_choice="auto"
        )
        
        response_message = response.choices[0].message

        # Vérification si l'IA veut utiliser l'outil Notion
        if response_message.tool_calls:
            for tool_call in response_message.tool_calls:
                args = json.loads(tool_call.function.arguments)
                success, feedback = send_to_notion(args["table_key"], args)
                
                if success:
                    return {"reply": f"C'est fait Rebecca, c'est noté dans {args['table_key']}."}
                else:
                    return {"reply": f"Il y a un petit souci technique avec le tableau {args['table_key']}. Voici l'erreur : {feedback}"}

        return {"reply": response_message.content}

    except Exception as e:
        logger.error(f"Global Error: {str(e)}")
        return {"reply": "Désolé Rebecca, une erreur système s'est produite."}

@app.get("/")
def health():
    return {"status": "SOVEREIGN ENGINE LIVE"}
