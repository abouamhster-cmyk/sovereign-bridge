import os
import requests
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

# --- LOGIQUE NOTION ---
def save_to_notion(table_key, title_col, title_val):
    db_id = DATABASE_IDS.get(table_key)
    if not db_id: return "Table non trouvée"
    url = "https://api.notion.com/v1/pages"
    data = {
        "parent": {"database_id": db_id},
        "properties": {title_col: {"title": [{"text": {"content": title_val}}]}}
    }
    requests.post(url, headers=headers, json=data)
    return f"Succès : {title_val} ajouté dans {table_key}"

# --- LOGIQUE CHAT ---
class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    # L'IA discute et décide si elle doit enregistrer dans Notion
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": m.role, "content": m.content} for m in request.messages]
    )
    return {"reply": response.choices[0].message.content}

@app.get("/")
def health():
    return {"status": "Sovereign Backend Ready"}
