import os
import requests
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional

app = FastAPI()

# --- CONFIGURATION ---
# Remplace par ton secret Notion (ex: secret_xxxxx...)
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

# --- MODELES DE DONNEES ---
class InboxItem(BaseModel):
    title: str
    item_type: Optional[str] = "Task"
    area: Optional[str] = "Business"

# --- ROUTES API ---

@app.get("/")
def home():
    return {"status": "SOVEREIGN Bridge is Online", "owner": "Rebecca"}

@app.post("/add_inbox")
def add_inbox(item: InboxItem):
    """Ajoute une ligne dans l'Inbox Notion"""
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
    return response.json()

@app.get("/list_missions")
def list_missions():
    """Récupère la liste des missions actives"""
    url = f"https://api.notion.com/v1/databases/{DATABASE_IDS['mission']}/query"
    response = requests.post(url, headers=headers)
    return response.json()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
