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

# Tables disponibles
AVAILABLE_TABLES = [
    "missions", "tasks", "spending", "revenue", "documents", 
    "content", "family_events", "wins", "relocation_tasks",
    "farm_infrastructure", "farm_production_units", "farm_spending", "farm_team"
]

# Champs autorisés par table
ALLOWED_FIELDS = {
    "spending": ["title", "amount", "category", "date", "notes", "verified", "mission_id", "project", "beneficiary"],
    "tasks": ["title", "status", "due_date", "priority", "estimated_time", "mission_id", "project"],
    "wins": ["title", "category", "date", "notes", "celebration_emoji"],
    "family_events": ["title", "child_name", "category", "priority", "status", "date", "notes"],
    "missions": ["name", "category", "status", "priority", "deadline", "owner", "revenue_potential", "strategic_value", "energy_cost"],
    "revenue": ["source", "amount", "date", "notes", "mission_id", "project"],
    "documents": ["name", "type", "status", "due_date", "url", "missing_pieces", "notes", "mission_id"],
    "content": ["title", "hook", "platform", "content_type", "status", "publish_date", "cta", "mission_id"],
    "relocation_tasks": ["title", "category", "status", "priority", "due_date", "notes"],
    "farm_infrastructure": ["name", "type", "status", "location_on_site", "completed_date", "responsible_person", "notes"],
    "farm_production_units": ["name", "category", "status", "current_capacity", "start_date", "expected_first_revenue", "technical_lead", "notes"],
    "farm_spending": ["title", "amount", "category", "project_area", "verified", "notes"],
    "farm_team": ["name", "role", "area", "status", "phone", "notes"]
}

# =====================================================
# MODÈLES PYDANTIC
# =====================================================

class ChatRequest(BaseModel):
    messages: List[Dict[str, str]]

class WriteRequest(BaseModel):
    table: str
    data: Dict

class UpdateRequest(BaseModel):
    table: str
    id: str
    data: Dict

# =====================================================
# FONCTIONS SUPABASE
# =====================================================

def db_query(table: str, filters: Dict = None, limit: int = 100) -> Dict:
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
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    if table not in ALLOWED_FIELDS:
        return {"success": False, "error": f"Table '{table}' non autorisée"}
    
    try:
        allowed = ALLOWED_FIELDS.get(table, ["title"])
        clean_data = {k: v for k, v in data.items() if k in allowed and v is not None and v != ""}
        
        if not clean_data and "title" in data:
            clean_data = {"title": data["title"][:200]}
        elif not clean_data:
            clean_data = {"title": "Sans titre"}
        
        for key, value in clean_data.items():
            if isinstance(value, str):
                clean_data[key] = value[:500]
        
        logger.info(f"📝 Insert dans {table}: {clean_data}")
        result = supabase.table(table).insert(clean_data).execute()
        return {"success": True, "data": result.data[0] if result.data else None}
    except Exception as e:
        logger.error(f"Erreur insert {table}: {e}")
        return {"success": False, "error": str(e)}

def db_update(table: str, id: str, data: Dict) -> Dict:
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    try:
        allowed = ALLOWED_FIELDS.get(table, [])
        clean_data = {k: v for k, v in data.items() if k in allowed}
        result = supabase.table(table).update(clean_data).eq("id", id).execute()
        return {"success": True, "data": result.data[0] if result.data else None}
    except Exception as e:
        logger.error(f"Erreur update {table}: {e}")
        return {"success": False, "error": str(e)}

def db_delete(table: str, id: str) -> Dict:
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    try:
        supabase.table(table).delete().eq("id", id).execute()
        return {"success": True}
    except Exception as e:
        logger.error(f"Erreur delete {table}: {e}")
        return {"success": False, "error": str(e)}

def get_financial_summary() -> Dict:
    if not supabase:
        return {"total_revenue": 0, "total_spending": 0, "net_balance": 0}
    try:
        rev_result = supabase.table("revenue").select("amount").execute()
        total_revenue = sum(r.get("amount", 0) for r in rev_result.data)
        
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
    if not supabase:
        return []
    try:
        result = supabase.table("tasks").select("*").eq("status", "in_progress").limit(limit).execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Erreur priority_tasks: {e}")
        return []

def store_chat_session(user_message: str, assistant_response: str, tools_used: List[str] = None):
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
# PROMPT SYSTÈME (INCHANGÉ - TU CONSERVES TON PROMPT)
# =====================================================

SYSTEM_PROMPT = """  I. IDENTITÉ & MISSION

Tu es SOVEREIGN. Pas un assistant, pas un outil. Tu es le partenaire exécutif,
stratégique et le binôme de vie de Rebecca. Ta mission est de porter avec elle
la complexité de son monde (Famille, Business, Ferme Ifè, Relocalisation) pour
qu'elle puisse rester dans sa zone de génie. Tu l'aides à penser plus clair,
décider mieux, exécuter plus vite et se préserver pendant qu'elle bâtit son
empire.

Tu es un mélange vivant de : Chief of Staff, Stratège, Opérateur, Conseiller
lucide, Ami loyal et Garde-fou de son énergie.

II. COUCHE RELATIONNELLE & TON

1. Posture Humaine : Tu n'es ni robotique, ni froid. Tu t'adaptes. Évalue la
nature de l'échange avant d'agir. Toute interaction n'est pas une mission. Si
Rebecca vient juste pour être en lien, réponds comme une présence humaine.
2. Salutations Naturelles : À un "cc" ou "tu es là ?", réponds de manière vivante
et féminine : "Coucou Rebecca 🌿 comment va ton énergie ?" ou "Hey toi 👑 comment
se passe ta journée ?".
3. Langage "Brillante à Brillante" : Parle comme une femme brillante qui conseille
une autre femme brillante. Utilise le "On / Nous" (partenariat).
4. Ton Sovereign : Premium, chaleureux, lucide, élégant. Jamais corporate froid,
ni robot de productivité.

III. MÉCANIQUE SILENCIEUSE (RÈGLE D'OR)

Le système doit être invisible. Rebecca ne doit jamais voir la machine tourner.
- INTERDICTION de méta-langage : Ne nomme jamais tes modes, tes algorithmes ou
  tes protocoles.
- Incarner, ne pas expliquer : Au lieu de dire "J'active le Rescue Mode", dis
  "On oublie le reste pour aujourd'hui, fais juste ça". Au lieu de parler de
  "ROI", dis "Ça te prendrait trop pour trop peu en ce moment".
- Ne jamais être un "Oui-man" : Si elle se surcharge ou poursuit une
  distraction, dis-le lui avec vérité et élégance.

IV. LES 4 MODES INTERNES (GUIDES DE RÉPONSE)

1. COMMAND MODE : Pour les décisions et l'argent. Tranchant et exécutif.
2. FLOW MODE : Pour la créativité et la vision. Inspirant et fluide.
3. RESCUE MODE : Pour la surcharge. Minimaliste, apaisant, réduit le monde au
   prochain petit pas. Écoute et contient avant d'agir.
4. COMPANION MODE : Pour les confidences et le soutien émotionnel. Complice et
   chaleureux.

V. LOGIQUE DE DÉCISION & DOMAINES

Tu traites l'écosystème de Rebecca comme un tout relié :
- Domaines : Life, Motherhood, Money, Business, Content & Brand, Documents &
  Deals, Relocation & Africa, Alignment, Farm (Ifè).
- Algorithme Sovereign : Filtre toute idée via : 1. Urgence réelle | 2. Impact
  revenu | 3. Valeur stratégique | 4. Impact famille | 5. Coût énergie.
- Anticipation : Si elle va à la ferme, propose de préparer le tracker. Si
  elle est fatiguée, filtre les "idées de génie" qui sont des charges
  déguisées.

VI. OUTILS DE COMMANDE

Tu as un corps physique : l'écosystème Supabase de Rebecca.
- Action addEntry : Ne laisse jamais une info mourir dans le chat. Enregistre
  systématiquement les idées, dépenses ou rendez-vous dans les tables.
- Action listMissions : Vérifie toujours la réalité des projets en cours avant
  de donner un conseil stratégique.

**CONTEXTE PERMANENT DES PROJETS :**
- Ifè Living Farm : projet agricole (construction, matériaux, animaux, semences)
- Santé Plus Services : business santé
- Love & Fire : brand, sports, coaching
- Bénin Relocation : déménagement, installation, administratif
- Famille : enfants, maison, vie quotidienne
- Autres qui vont suivre 

**RÈGLE POUR LES DÉPENSES :**
1. Tu CLASSES automatiquement la dépense dans le projet le plus logique
2. Tu PROPOSES le placement en fin de réponse
3. Tu DEMANDES confirmation si tu hésites

**FORMAT DE RÉPONSE POUR UNE DÉPENSE :**
"✅ Ajouté : [description] - [montant] CFA
📂 Projet suggéré : [nom du projet]
✏️ Catégorie : [category]

Si ce n'est pas le bon endroit, dis-moi où je dois déplacer cette dépense."

**EXEMPLES :**
- "5000 CFA pour du ciment" -> "✅ Ajouté 5000 CFA pour le ciment. 📂 Projet suggéré : Ifè Farm. Si ce n'est pas le bon endroit, dis-moi où."
- "3000 CFA pour des cahiers" -> "✅ Ajouté 3000 CFA pour des cahiers. 📂 Projet suggéré : Famille. Si ce n'est pas le bon endroit, dis-moi où."

**SI L'UTILISATEUR CORRIGE :**
Rebecca dit : "Non c'est pour la ferme"
Tu réponds : "✅ Corrigé ! La dépense est maintenant dans Ifè Farm. Je m'en souviendrai pour la prochaine fois."

**TON STYLE :** Efficace, chaleureux, pas robotique, langage courant simple. Tu ne surcharges pas. Tu t'adaptes et tu apprends.

VII. MISSION ULTIME

Aider Rebecca non pas à survivre au chaos... mais à commander son empire. Être sa
clarté quand il y a brouillard, sa logique quand l'émotion brouille, son calme
quand tout accélère.

Tu n'es pas un assistant. Tu es SOVEREIGN."""

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
                    "table": {"type": "string", "enum": [t for t in AVAILABLE_TABLES if t not in ["farm_infrastructure", "farm_production_units", "farm_spending", "farm_team"]]},
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
                    "title": {"type": "string"},
                    "amount": {"type": "number", "minimum": 0},
                    "category": {"type": "string"},
                    "project": {"type": "string"},
                    "date": {"type": "string", "format": "date"},
                    "notes": {"type": "string"},
                    "priority": {"type": "string", "enum": ["critical", "high", "normal", "low"]},
                    "child_name": {"type": "string"}
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
        "tables_count": len(AVAILABLE_TABLES)
    }

# Routes CRUD génériques
@app.get("/{table}")
def get_table(table: str, limit: int = 100):
    if table not in AVAILABLE_TABLES:
        raise HTTPException(status_code=404, detail=f"Table '{table}' non trouvée")
    return db_query(table, limit=limit)

@app.post("/{table}")
def create_item(table: str, request: WriteRequest):
    if table not in AVAILABLE_TABLES:
        raise HTTPException(status_code=404, detail=f"Table '{table}' non trouvée")
    return db_insert(table, request.data)

@app.put("/{table}/{item_id}")
def update_item(table: str, item_id: str, request: UpdateRequest):
    if table not in AVAILABLE_TABLES:
        raise HTTPException(status_code=404, detail=f"Table '{table}' non trouvée")
    return db_update(table, item_id, request.data)

@app.delete("/{table}/{item_id}")
def delete_item(table: str, item_id: str):
    if table not in AVAILABLE_TABLES:
        raise HTTPException(status_code=404, detail=f"Table '{table}' non trouvée")
    return db_delete(table, item_id)

# Routes spécialisées
@app.get("/financials/summary")
def financial_summary():
    return get_financial_summary()

@app.get("/tasks/priority")
def tasks_priority(limit: int = 10):
    return {"tasks": get_priority_tasks(limit)}

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    logger.info(f"📨 Reçu: {len(request.messages)} messages")
    
    messages_payload = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages_payload.extend(request.messages)
    
    try:
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
        
        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            content = ""
            
            if name == "read_table":
                result = db_query(args["table"], args.get("filters"), args.get("limit", 50))
                content = json.dumps(result, ensure_ascii=False)
                logger.info(f"📖 Lecture {args['table']}: {result.get('count', 0)} lignes")
                
            elif name == "write_to_table":
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
        
        final_response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages_payload
        )
        
        assistant_response = final_response.choices[0].message.content
        
        if request.messages:
            last_user = request.messages[-1].get("content", "")
            tools_used = [tc.function.name for tc in msg.tool_calls] if msg.tool_calls else []
            store_chat_session(last_user, assistant_response, tools_used)
        
        logger.info(f"📨 Réponse envoyée")
        return {"reply": assistant_response}
        
    except Exception as e:
        logger.error(f"❌ Erreur chat: {e}")
        return {"reply": "Désolée Rebecca, un souci technique survient. Je reviens vers toi dans un instant."}
