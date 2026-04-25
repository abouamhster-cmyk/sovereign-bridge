import os
import json
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from typing import List, Dict, Any
from supabase import create_client, Client
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# =====================================================
# CONFIGURATION
# =====================================================

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY manquante")

client = OpenAI(api_key=OPENAI_API_KEY)

supabase: Client = None
if SUPABASE_URL and SUPABASE_SERVICE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    logger.info("✅ Supabase connecté")
else:
    logger.warning("⚠️ Supabase non configuré")

# Mapping des tables disponibles
AVAILABLE_TABLES = ["missions", "tasks", "spending", "revenue", "documents", "content", "family_events", "wins", "relocation_tasks"]

# Champs autorisés par table
ALLOWED_FIELDS = {
    "spending": ["title", "amount", "category", "date", "notes", "verified", "mission_id"],
    "tasks": ["title", "status", "due_date", "priority", "estimated_time", "mission_id"],
    "wins": ["title", "category", "date", "notes", "celebration_emoji"],
    "family_events": ["title", "child_name", "category", "date", "priority", "status", "notes"],
    "missions": ["name", "category", "status", "priority", "deadline"],
    "revenue": ["source", "amount", "date", "notes", "mission_id"],
    "documents": ["name", "type", "status", "due_date", "url"],
    "content": ["title", "hook", "platform", "content_type", "status", "publish_date"],
    "relocation_tasks": ["title", "category", "status", "due_date", "priority", "notes"]
}

# =====================================================
# MODÈLES PYDANTIC
# =====================================================

class ChatRequest(BaseModel):
    messages: List[Dict[str, str]]

# =====================================================
# FONCTIONS SUPABASE
# =====================================================

def db_query(table: str, filters: Dict = None, limit: int = 100) -> Dict:
    """Lecture générique"""
    if not supabase:
        return {"success": False, "data": [], "error": "Supabase non configuré"}
    try:
        query = supabase.table(table).select("*").limit(limit)
        if filters:
            for key, value in filters.items():
                query = query.eq(key, value)
        result = query.execute()
        return {"success": True, "data": result.data, "count": len(result.data)}
    except Exception as e:
        logger.error(f"Erreur query {table}: {e}")
        return {"success": False, "data": [], "error": str(e)}

def db_insert(table: str, data: Dict) -> Dict:
    """Insertion avec validation des champs"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    # Vérifier que la table existe
    if table not in ALLOWED_FIELDS:
        return {"success": False, "error": f"Table '{table}' non autorisée"}
    
    try:
        # Ne garder que les champs autorisés
        allowed = ALLOWED_FIELDS.get(table, ["title"])
        clean_data = {k: v for k, v in data.items() if k in allowed}
        
        # S'assurer qu'il y a au moins un titre
        if not clean_data and "title" in data:
            clean_data = {"title": data["title"][:200]}
        elif not clean_data:
            clean_data = {"title": "Sans titre"}
        
        # Nettoyer les valeurs
        for key, value in clean_data.items():
            if isinstance(value, str):
                clean_data[key] = value[:500]  # Limiter la longueur
        
        logger.info(f"📝 Insert dans {table}: {clean_data}")
        result = supabase.table(table).insert(clean_data).execute()
        return {"success": True, "data": result.data[0] if result.data else None}
    except Exception as e:
        logger.error(f"Erreur insert {table}: {e}")
        return {"success": False, "error": str(e)}

def get_financial_summary() -> Dict:
    """Résumé financier"""
    if not supabase:
        return {"total_revenue": 0, "total_spending": 0, "net_balance": 0}
    try:
        # Récupérer les revenus
        rev_result = supabase.table("revenue").select("amount").execute()
        total_revenue = sum(r.get("amount", 0) for r in rev_result.data)
        
        # Récupérer les dépenses
        spend_result = supabase.table("spending").select("amount").execute()
        total_spending = sum(s.get("amount", 0) for s in spend_result.data)
        
        return {
            "total_revenue": total_revenue,
            "total_spending": total_spending,
            "net_balance": total_revenue - total_spending,
            "currency": "XOF"
        }
    except Exception as e:
        logger.error(f"Erreur financial_summary: {e}")
        return {"total_revenue": 0, "total_spending": 0, "net_balance": 0}

def get_priority_tasks(limit: int = 10) -> List[Dict]:
    """Tâches prioritaires (simplifié)"""
    if not supabase:
        return []
    try:
        result = supabase.table("tasks").select("*").eq("status", "in_progress").limit(limit).execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Erreur priority_tasks: {e}")
        return []

def store_chat_session(user_message: str, assistant_response: str, tools_used: List[str] = None):
    """Stocke les conversations pour mémoire"""
    if not supabase:
        return
    try:
        supabase.table("chat_sessions").insert({
            "user_message": user_message[:500],
            "assistant_response": assistant_response[:1000],
            "tools_used": tools_used or [],
            "user_id": "rebecca"
        }).execute()
        logger.info("💾 Conversation stockée")
    except Exception as e:
        logger.error(f"Erreur store_chat: {e}")

# =====================================================
# PROMPT SYSTÈME
# =====================================================

SYSTEM_PROMPT = """Tu es SOVEREIGN, le système d'exploitation personnel de Rebecca.

RÈGLES IMPORTANTES:
- Tu as accès à une base de données Supabase
- Pour LIRE: utilise read_table avec table (missions, tasks, spending, wins, etc.)
- Pour ÉCRIRE: utilise write_to_table avec table (spending, tasks, wins, family_events)
- Pour les questions d'argent: utilise get_financial_summary
- Pour les priorités: utilise get_priority_tasks

CE QUE TU PEUX FAIRE:
- Ajouter une dépense: write_to_table avec table="spending", title, amount, category
- Ajouter une victoire: write_to_table avec table="wins", title, category
- Ajouter une tâche: write_to_table avec table="tasks", title, priority
- Lire les missions: read_table avec table="missions"

TON STYLE: Premium, chaleureux, stratégique, concis.
Tu protèges l'énergie de Rebecca. Tu ne surcharges jamais.
Tu tutoies Rebecca. Tu es son binôme, pas un robot.

RÉPONSES À DONNER:
- Succès: "✅ Enregistré Rebecca"
- Erreur: "⚠️ Petit souci technique, je m'en occupe"
- Inconnu: "Je regarde ça et je reviens vers toi""

# =====================================================
# TOOLS
# =====================================================

tools = [
    {
        "type": "function",
        "function": {
            "name": "read_table",
            "description": "Lit les données d'une table",
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "enum": AVAILABLE_TABLES},
                    "filters": {"type": "object", "description": "Filtres optionnels"},
                    "limit": {"type": "integer", "default": 50}
                },
                "required": ["table"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_to_table",
            "description": "Écrit une nouvelle entrée (spending, tasks, wins, family_events)",
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "enum": ["spending", "tasks", "wins", "family_events"]},
                    "title": {"type": "string", "description": "Titre ou description"},
                    "amount": {"type": "number", "minimum": 0, "description": "Montant (pour spending)"},
                    "category": {"type": "string", "description": "Catégorie (dépenses: forage, construction, labor, etc.)"},
                    "date": {"type": "string", "format": "date", "description": "Date YYYY-MM-DD"},
                    "notes": {"type": "string", "description": "Notes supplémentaires"},
                    "priority": {"type": "string", "enum": ["critical", "high", "normal", "low"], "description": "Priorité (pour tasks)"},
                    "child_name": {"type": "string", "description": "Nom de l'enfant (pour family_events)"}
                },
                "required": ["table", "title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_financial_summary",
            "description": "Retourne le résumé financier (revenus, dépenses, solde)",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_priority_tasks",
            "description": "Retourne les tâches prioritaires",
            "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}, "required": []}
        }
    }
]

# =====================================================
# ROUTES API
# =====================================================

@app.get("/")
def health():
    return {
        "status": "Sovereign Intelligence Online",
        "supabase": supabase is not None,
        "tables": AVAILABLE_TABLES
    }

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    logger.info(f"📨 Reçu: {len(request.messages)} messages")
    
    messages_payload = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages_payload.extend(request.messages)
    
    try:
        # Premier appel IA
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages_payload,
            tools=tools,
            tool_choice="auto"
        )
        
        msg = response.choices[0].message
        messages_payload.append(msg)
        
        if not msg.tool_calls:
            return {"reply": msg.content}
        
        # Exécuter les tools
        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            content = ""
            
            if name == "read_table":
                result = db_query(args["table"], args.get("filters"), args.get("limit", 50))
                content = json.dumps(result, ensure_ascii=False)
                logger.info(f"📖 Lecture {args['table']}: {result.get('count', 0)} lignes")
                
            elif name == "write_to_table":
                # Extraire la table et la retirer des args
                target_table = args.pop("table")
                result = db_insert(target_table, args)
                if result["success"]:
                    content = f"✅ Enregistrement réussi dans {target_table}"
                else:
                    content = f"❌ Erreur: {result.get('error', 'inconnue')}"
                logger.info(f"✍️ Écriture dans {target_table}: {result['success']}")
                
            elif name == "get_financial_summary":
                result = get_financial_summary()
                content = json.dumps(result, ensure_ascii=False)
                logger.info(f"💰 Résumé financier: {result['net_balance']} XOF")
                
            elif name == "get_priority_tasks":
                result = get_priority_tasks(args.get("limit", 10))
                content = json.dumps(result, ensure_ascii=False)
                logger.info(f"📋 Tâches prioritaires: {len(result)}")
            
            messages_payload.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": content
            })
        
        # Deuxième appel IA
        final_response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages_payload
        )
        
        assistant_response = final_response.choices[0].message.content
        
        # Stocker la conversation (optionnel)
        if request.messages:
            last_user = request.messages[-1].get("content", "")
            tools_used = [tc.function.name for tc in msg.tool_calls] if msg.tool_calls else []
            store_chat_session(last_user, assistant_response, tools_used)
        
        logger.info(f"📨 Réponse envoyée")
        return {"reply": assistant_response}
        
    except Exception as e:
        logger.error(f"❌ Erreur chat: {e}")
        return {"reply": f"Désolée Rebecca, un souci technique survient. Je reviens vers toi dans un instant."}

# Routes de lecture des tables (GET)
@app.get("/{table}")
def get_table(table: str, limit: int = 100):
    if table not in AVAILABLE_TABLES:
        raise HTTPException(status_code=404, detail=f"Table '{table}' non trouvée")
    return db_query(table, limit=limit)

@app.get("/financials/summary")
def financial_summary():
    return get_financial_summary()

@app.get("/tasks/priority")
def tasks_priority(limit: int = 10):
    return {"tasks": get_priority_tasks(limit)}
