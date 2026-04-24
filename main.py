import os
import requests
import json
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from typing import List, Dict, Any
from pywebpush import webpush, WebPushException

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- CONFIGURATION SECRETS ---
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY") # Clé pour les notifications

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

headers = {"Authorization": f"Bearer {NOTION_TOKEN}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"}

# Stockage temporaire de l'abonnement du navigateur de Rebecca
rebecca_subscription = {}

# --- OUTILS NOTION ---
def query_notion(table_key: str):
    db_id = DATABASE_IDS.get(table_key)
    return requests.post(f"https://api.notion.com/v1/databases/{db_id}/query", headers=headers).json()

def send_to_notion(table_key: str, data: Dict):
    db_id = DATABASE_IDS.get(table_key)
    title_map = {"inbox": "Item", "mission": "Mission Name", "task": "Task", "spending": "Expense", "infrastructure": "Asset", "revenue": "Source", "team": "Name", "family": "Item", "kids": "Document Name", "move": "Task", "wins": "Win"}
    title_col = title_map.get(table_key, "Name")
    
    notion_props = {title_col: {"title":[{"text": {"content": data.get("title", "Sans titre")}}]}}
    
    if "amount" in data:
        prop_name = "Amount Received" if table_key == "revenue" else "Amount"
        notion_props[prop_name] = {"number": data["amount"]}
    if "category" in data and table_key == "spending":
        notion_props["Category"] = {"select": {"name": data["category"]}}
    if "date" in data:
        notion_props["Date"] = {"date": {"start": data["date"]}}
    if "mission_uuid" in data:
        notion_props["🎯 MISSIONS"] = {"relation": [{"id": data["mission_uuid"]}]}

    res = requests.post("https://api.notion.com/v1/pages", headers=headers, json={"parent": {"database_id": db_id}, "properties": notion_props})
    return res.status_code == 200, res.text

def trigger_push_alert(title: str, message: str):
    global rebecca_subscription
    if not rebecca_subscription:
        return False, "Le navigateur de Rebecca n'est pas connecté aux alertes."
    if not VAPID_PRIVATE_KEY:
        return False, "Clé VAPID manquante sur le serveur."
    try:
        webpush(
            subscription_info=rebecca_subscription,
            data=json.dumps({"title": title, "body": message}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": "mailto:admin@sovereign.com"}
        )
        return True, "Alerte envoyée au téléphone."
    except WebPushException as ex:
        return False, str(ex)

# --- DÉFINITION DES TOOLS POUR OPENAI ---
tools =[
    {
        "type": "function",
        "function": {
            "name": "write_to_empire",
            "description": "Enregistre une donnée. Obligatoire : table_key, title. Optionnel : amount, date, mission_uuid.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_key": {"type": "string", "enum": list(DATABASE_IDS.keys())},
                    "title": {"type": "string"},
                    "amount": {"type": "number"},
                    "date": {"type": "string"},
                    "mission_uuid": {"type": "string"}
                },
                "required": ["table_key", "title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_empire_table",
            "description": "Lit un tableau pour trouver des infos ou des UUIDs de missions.",
            "parameters": {
                "type": "object",
                "properties": {"table_key": {"type": "string", "enum": list(DATABASE_IDS.keys())}},
                "required": ["table_key"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_push_alert",
            "description": "Envoie une notification push native sur l'appareil de Rebecca.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Titre de l'alerte"},
                    "message": {"type": "string", "description": "Contenu du rappel"}
                },
                "required": ["title", "message"]
            }
        }
    }
]

class ChatRequest(BaseModel):
    messages: List[Dict]

# --- ROUTES API ---

@app.post("/subscribe")
def subscribe(subscription: Dict[str, Any]):
    """Reçoit la clé du navigateur de Rebecca pour lui envoyer des push"""
    global rebecca_subscription
    rebecca_subscription = subscription
    return {"status": "Subscribed"}

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    current_messages = request.messages
    
    for _ in range(3):
        response = client.chat.completions.create(model="gpt-4o", messages=current_messages, tools=tools)
        msg = response.choices[0].message
        current_messages.append(msg)

        if not msg.tool_calls:
            return {"reply": msg.content}

        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            
            if name == "read_empire_table":
                result = query_notion(args["table_key"])
                content = json.dumps(result)
            elif name == "write_to_empire":
                success, feedback = send_to_notion(args["table_key"], args)
                content = "Succès" if success else f"Erreur Notion : {feedback}"
            elif name == "send_push_alert":
                success, feedback = trigger_push_alert(args["title"], args["message"])
                content = feedback
            
            current_messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": content})
    
    return {"reply": "J'ai dû interrompre ma réflexion. Pouvez-vous préciser ?"}

@app.get("/")
def health(): return {"status": "Sovereign Intelligence Online"}
