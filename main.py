import os
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

app = FastAPI()

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")

# MAPPING COMPLET DES 11 TABLES
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

# --- MODÈLES DE DONNÉES ---
class UniversalItem(BaseModel):
    table_key: str
    title_col: str
    title_val: str
    properties: Optional[dict] = {}

# --- ROUTE UNIVERSELLE (L'IA peut tout écrire) ---
@app.post("/add_entry")
def add_entry(item: UniversalItem):
    db_id = DATABASE_IDS.get(item.table_key)
    if not db_id:
        raise HTTPException(status_code=404, detail="Table non trouvée")
    
    url = "https://api.notion.com/v1/pages"
    
    # Construction dynamique des propriétés
    notion_props = {
        item.title_col: {"title": [{"text": {"content": item.title_val}}]}
    }
    
    # On ajoute les autres colonnes si l'IA en envoie
    for key, val in item.properties.items():
        if isinstance(val, float) or isinstance(val, int):
            notion_props[key] = {"number": val}
        else:
            notion_props[key] = {"select": {"name": val}}

    data = {"parent": {"database_id": db_id}, "properties": notion_props}
    response = requests.post(url, headers=headers, json=data)
    return response.json()

@app.get("/list_missions")
def list_missions():
    url = f"https://api.notion.com/v1/databases/{DATABASE_IDS['mission']}/query"
    return requests.post(url, headers=headers).json()

@app.get("/")
def home():
    return {"status": "SOVEREIGN FULL ENGINE ONLINE"}
