import os
import requests
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from typing import List, Optional, Dict

app = FastAPI()

# --- CONFIGURATION CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CLIENTS & SECRETS ---
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

# --- LOGIQUE INTELLIGENTE DE MAPPING NOTION ---
def send_to_notion(table_key: str, data: Dict):
    db_id = DATABASE_IDS.get(table_key)
    if not db_id: return {"error": "Table non trouvée"}

    # Mapping des noms de colonnes Titres par table
    title_map = {
        "inbox": "Item", "mission": "Mission Name", "task": "Task",
        "spending": "Expense", "infrastructure": "Asset", "revenue": "Source",
        "team": "Name", "family": "Item", "kids": "Document",
        "move": "Task", "wins": "Win"
    }
    
    title_col = title_map.get(table_key, "Name")
    
    # Construction de l'objet de propriétés Notion
    notion_props = {
        title_col: {"title": [{"text": {"content": data.get("title", "Sans titre")}}]}
    }

    # Intelligence de remplissage selon la table
    if table_key == "spending" and "amount" in data:
        notion_props["Amount (CFA/USD)"] = {"number": data["amount"]}
        if "category" in data: notion_props["Category"] = {"select": {"name": data["category"]}}

    if table_key == "revenue" and "amount" in data:
        notion_props["Amount Received"] = {"number": data["amount"]}

    if table_key == "task":
        # L'IA génère les scores Sovereign de 1 à 5
        notion_props["Urgency"] = {"number": data.get("urgency", 3)}
        notion_props["Revenue Impact"] = {"number": data.get("revenue_impact", 1)}
        notion_props["Strategic Value"] = {"number": data.get("strategic_value", 1)}
        notion_props["Family Impact"] = {"number": data.get("family_impact", 1)}
        notion_props["Energy Cost"] = {"number": data.get("energy_cost", 2)}

    if table_key in ["infrastructure", "move"]:
        # Gestion du type "Status" (rond de couleur Notion)
        notion_props["Status"] = {"status": {"name": data.get("status", "Pas commencé")}}

    if table_key == "family" and "date" in data:
        notion_props["Date"] = {"date": {"start": data["date"]}}

    url = "https://api.notion.com/v1/pages"
    res = requests.post(url, headers=headers, json={"parent": {"database_id": db_id}, "properties": notion_props})
    return res.json()

# --- DEFINITION DES OUTILS POUR L'IA (TOOLS) ---
tools = [{
    "type": "function",
    "function": {
        "name": "manage_rebecca_empire",
        "description": "Enregistre intelligemment une donnée dans le bon tableau Notion de Rebecca.",
        "parameters": {
            "type": "object",
            "properties": {
                "table_key": {"type": "string", "enum": list(DATABASE_IDS.keys())},
                "title": {"type": "string", "description": "Titre ou description de l'entrée"},
                "amount": {"type": "number", "description": "Montant financier si applicable"},
                "category": {"type": "string", "description": "Catégorie (ex: Construction, Scolarité)"},
                "status": {"type": "string", "description": "Status (ex: En cours, Terminé, Prêt)"},
                "urgency": {"type": "integer", "minimum": 1, "maximum": 5},
                "revenue_impact": {"type": "integer", "minimum": 1, "maximum": 5},
                "strategic_value": {"type": "integer", "minimum": 1, "maximum": 5},
                "family_impact": {"type": "integer", "minimum": 1, "maximum": 5},
                "energy_cost": {"type": "integer", "minimum": 1, "maximum": 5},
                "date": {"type": "string", "description": "Format YYYY-MM-DD"}
            },
            "required": ["table_key", "title"]
        }
    }
}]

class ChatRequest(BaseModel):
    messages: List[Dict]

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    # Appel à GPT-4o avec connaissance des outils
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=request.messages,
        tools=tools,
        tool_choice="auto"
    )
    
    response_message = response.choices[0].message
    
    # Si l'IA veut appeler une fonction (Notion)
    if response_message.tool_calls:
        for tool_call in response_message.tool_calls:
            args = json.loads(tool_call.function.arguments)
            send_to_notion(args["table_key"], args)
        
        return {"reply": f"C'est fait, Rebecca. J'ai mis à jour votre {args['table_key']}."}

    return {"reply": response_message.content}

@app.get("/")
def health(): return {"status": "Sovereign AI Engine Live"}
