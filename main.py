import os
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

app = FastAPI()

# --- CONFIGURATION SÉCURISÉE ---
# Render lira cette valeur dans tes "Environment Variables"
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")

DATABASE_IDS = {
    "inbox": "345a95e67e2880fa9f59cf10841aad32",
    "mission": "345a95e67e28803d8751e0d78048c3bd",
    "task": "345a95e67e28801481badd2ec8442615",
    "revenue": "345a95e67e28809991f7d26de9168c09"
}

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# --- MODÈLES DE DONNÉES ---
class InboxItem(BaseModel):
    title: str
    item_type: Optional[str] = "Task"
    area: Optional[str] = "Business"

# --- ROUTES ---

@app.get("/")
def home():
    return {"status": "SOVEREIGN OS Online", "platform": "Render"}

@app.post("/add_inbox")
def add_inbox(item: InboxItem):
    """Ajoute une entrée dans l'Inbox Notion de Rebecca"""
    if not NOTION_TOKEN:
        raise HTTPException(status_code=500, detail="Notion Token manquant sur le serveur")
    
    url = "https://api.notion.com/v1/pages"
    data = {
        "parent": {"database_id": DATABASE_IDS["inbox"]},
        "properties": {
            "Item": {"title": [{"text": {"content": item.title}}]},
            "Type": {"select": {"name": item.item_type}},
            "Area": {"select": {"name": item.area}}
        }
    }
    response = requests.post(url, headers=headers, json=data)
    
    if response.status_code != 200:
        return {"error": response.json()}
    return {"status": "Success", "data": "Note ajoutée à l'Inbox"}

@app.get("/list_missions")
def list_missions():
    """Récupère la liste des missions actives"""
    url = f"https://api.notion.com/v1/databases/{DATABASE_IDS['mission']}/query"
    response = requests.post(url, headers=headers)
    return response.json()

# Render gère le port automatiquement via uvicorn dans sa commande de démarrage
