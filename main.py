import os
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Union, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi import UploadFile, File
from pydantic import BaseModel
from openai import OpenAI
from supabase import create_client, Client
from pywebpush import webpush, WebPushException
import httpx


# =====================================================
# FONCTIONS UTILITAIRES
# =====================================================

def normalize_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convertit les messages au format OpenAI (supporte texte + images)"""
    normalized = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")
        if isinstance(content, list):
            normalized.append({"role": role, "content": content})
        else:
            normalized.append({"role": role, "content": content})
    return normalized

# =====================================================
# LOGGING CONFIGURATION
# =====================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =====================================================
# FASTAPI INITIALIZATION
# =====================================================

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://sovereignallmighty.netlify.app", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =====================================================
# ENVIRONMENT VARIABLES & CLIENTS
# =====================================================

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY")
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY")
VAPID_CLAIMS = {"sub": "mailto:sovereign@rebecca.com"}

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY manquante")

client = OpenAI(api_key=OPENAI_API_KEY)

supabase: Client = None
if SUPABASE_URL and SUPABASE_SERVICE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    logger.info("✅ Supabase connecté")
else:
    logger.warning("⚠️ Supabase non configuré")


# =====================================================
# DATABASE SCHEMA CONFIGURATION
# =====================================================

AVAILABLE_TABLES = [
    "missions", "tasks", "spending", "revenue", "documents",
    "content", "family_events", "wins", "relocation_tasks",
    "farm_infrastructure", "farm_production_units", "farm_spending", "farm_team",
    "user_memory", "mood_entries"
]

ALLOWED_FIELDS = {
    "spending": ["title", "amount", "category", "date", "notes", "verified", "mission_id", "project", "beneficiary"],
    "tasks": ["title", "status", "due_date", "estimated_time", "mission_id", "project", "notes"],
    "wins": ["title", "category", "date", "notes", "celebration_emoji"],
    "family_events": ["title", "child_name", "category", "date", "notes"],
    "missions": ["name", "category", "status", "priority", "deadline", "owner", "revenue_potential", "strategic_value", "energy_cost"],
    "revenue": ["source", "amount", "date", "notes", "mission_id", "project"],
    "documents": ["name", "type", "status", "due_date", "url", "missing_pieces", "notes", "mission_id"],
    "content": ["title", "hook", "platform", "content_type", "status", "publish_date", "cta", "mission_id"],
    "relocation_tasks": ["title", "category", "status", "due_date", "notes"],
    "farm_infrastructure": ["name", "type", "status", "location_on_site", "completed_date", "responsible_person", "notes"],
    "farm_production_units": ["name", "category", "status", "current_capacity", "start_date", "expected_first_revenue", "technical_lead", "notes"],
    "farm_spending": ["title", "amount", "category", "project_area", "verified", "notes"],
    "farm_team": ["name", "role", "area", "status", "phone", "notes"],
    "user_memory": ["category", "key", "value", "user_id"],
    "mood_entries": ["mood", "date", "user_id"]
}


# =====================================================
# PYDANTIC MODELS
# =====================================================

class ChatRequest(BaseModel):
    messages: List[Dict[str, Any]]


class WriteRequest(BaseModel):
    table: str
    data: Dict


class UpdateRequest(BaseModel):
    table: str
    id: str
    data: Dict


class MemorySaveRequest(BaseModel):
    category: str
    key: str
    value: str


class ExecuteTaskRequest(BaseModel):
    title: str
    due_date: str = None
    priority: str = "normal"


# =====================================================
# FONCTIONS UTILITAIRES POUR NOTIFICATIONS
# =====================================================

def send_notification_sync(notification_data: Dict[str, Any]) -> List[Dict]:
    """Envoie une notification à tous les abonnés avec style premium"""
    if not supabase:
        logger.error("Supabase non configuré")
        return []
    
    subscriptions = supabase.table("push_subscriptions").select("*").execute()
    results = []
    
    # Emojis et couleurs selon le type
    type_styles = {
        "task": {"emoji": "📋", "color": "#3B82F6"},
        "mission": {"emoji": "🎯", "color": "#8B5CF6"},
        "win": {"emoji": "🏆", "color": "#F59E0B"},
        "money": {"emoji": "💰", "color": "#10B981"},
        "family": {"emoji": "👨‍👩‍👧‍👦", "color": "#EC4899"},
        "document": {"emoji": "📄", "color": "#EF4444"},
        "brief": {"emoji": "🌅", "color": "#D4AF37"},
        "default": {"emoji": "👑", "color": "#D4AF37"}
    }
    
    notif_type = notification_data.get("type", "default")
    style = type_styles.get(notif_type, type_styles["default"])
    
    title = f"{style['emoji']} {notification_data.get('title', 'SOVEREIGN')}"
    
    for sub in subscriptions.data:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": sub["keys"]
                },
                data=json.dumps({
                    "title": title,
                    "body": notification_data.get("body", ""),
                    "url": notification_data.get("url", "/"),
                    "icon": "/icons/icon-192x192.png",
                    "badge": "/icons/icon-96x96.png",
                    "image": "/icons/icon-512x512.png",
                    "type": notif_type,
                    "sound": "/sounds/notification.mp3",
                    "vibrate": [200, 100, 200],
                    "requireInteraction": True,
                    "timestamp": datetime.now().isoformat()
                }),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS
            )
            results.append({"status": "sent"})
            logger.info(f"✅ Notification {style['emoji']} envoyée")
        except WebPushException as e:
            if e.response and e.response.status_code == 410:
                supabase.table("push_subscriptions").delete().eq("endpoint", sub["endpoint"]).execute()
                results.append({"status": "expired"})
                logger.info(f"🗑️ Subscription expirée supprimée")
            else:
                results.append({"status": "error", "error": str(e)})
                logger.error(f"❌ Erreur webpush: {e}")
    
    return results


def get_days_late(date_str: str) -> int:
    """Calcule le nombre de jours de retard"""
    if not date_str:
        return 0
    due_date = datetime.fromisoformat(date_str).date()
    today = datetime.now().date()
    delta = today - due_date
    return max(0, delta.days)


# =====================================================
# FONCTIONS POUR LA MÉMOIRE UTILISATEUR
# =====================================================

async def get_user_memory_context(user_id: str = "rebecca") -> str:
    """Récupère la mémoire utilisateur pour l'injecter dans le prompt"""
    if not supabase:
        return ""
    
    try:
        result = supabase.table("user_memory").select("*").eq("user_id", user_id).execute()
        memories = result.data
        
        if not memories:
            return ""
        
        # Organiser par catégorie
        categorized = {}
        for mem in memories:
            cat = mem.get("category", "general")
            if cat not in categorized:
                categorized[cat] = []
            categorized[cat].append(f"{mem['key']}: {mem['value']}")
        
        # Construire le texte
        memory_text = "\n\n📚 INFORMATIONS SUR L'UTILISATEUR:\n"
        for cat, items in categorized.items():
            memory_text += f"\n{cat.upper()}:\n"
            for item in items:
                memory_text += f"  - {item}\n"
        
        return memory_text
    except Exception as e:
        logger.error(f"Erreur récupération mémoire: {e}")
        return ""


async def save_user_memory(category: str, key: str, value: str, user_id: str = "rebecca"):
    """Sauvegarde une information dans la mémoire utilisateur"""
    if not supabase:
        return False
    
    try:
        # Vérifier si la clé existe déjà
        existing = supabase.table("user_memory").select("*").eq("user_id", user_id).eq("category", category).eq("key", key).execute()
        
        if existing.data:
            supabase.table("user_memory").update({
                "value": value,
                "updated_at": datetime.now().isoformat()
            }).eq("id", existing.data[0]["id"]).execute()
        else:
            supabase.table("user_memory").insert({
                "category": category,
                "key": key,
                "value": value,
                "user_id": user_id,
                "created_at": datetime.now().isoformat()
            }).execute()
        
        logger.info(f"💾 Mémoire sauvegardée: {category}/{key} = {value}")
        return True
    except Exception as e:
        logger.error(f"Erreur sauvegarde mémoire: {e}")
        return False


# =====================================================
# FONCTIONS POUR LA VISION ET LES DOCUMENTS
# =====================================================

async def download_image_from_url(url: str) -> str:
    """Télécharge une image depuis une URL et la convertit en base64"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            import base64
            content_type = response.headers.get('content-type', 'image/png')
            base64_image = base64.b64encode(response.content).decode('utf-8')
            return f"data:{content_type};base64,{base64_image}"
    except Exception as e:
        logger.error(f"Erreur téléchargement image: {e}")
        return None


def extract_text_from_message(content: str) -> tuple[str, List[str]]:
    """Extrait le texte et les URLs d'images d'un message"""
    import re
    text_parts = []
    image_urls = []
    all_file_urls = []
    
    image_pattern = r'(https?://[^\s]+\.(?:png|jpg|jpeg|gif|webp))'
    image_urls = re.findall(image_pattern, content, re.IGNORECASE)
    
    file_pattern = r'https?://[^\s]+\.(?:pdf|txt|docx?|jpg|png|jpeg|gif|webp)'
    all_file_urls = re.findall(file_pattern, content, re.IGNORECASE)
    
    for url in image_urls:
        if url in all_file_urls:
            all_file_urls.remove(url)
        content = content.replace(url, f"[IMAGE: {url}]")
    
    text_parts.append(content)
    
    return " ".join(text_parts), image_urls, all_file_urls


async def process_document(file_url: str) -> str:
    """Télécharge et extrait le texte d'un document"""
    if not supabase:
        return None
    
    try:
        import re
        
        match = re.search(r'/chat-files/(.+)$', file_url)
        if not match:
            logger.error(f"Impossible d'extraire le chemin du fichier: {file_url}")
            return None
        
        file_path = match.group(1)
        logger.info(f"📄 Tentative de téléchargement: {file_path}")
        
        try:
            file_data = supabase.storage.from_("chat-files").download(file_path)
        except Exception as e:
            logger.error(f"Erreur téléchargement Supabase: {e}")
            if file_path.startswith("chat/"):
                alt_path = file_path[5:]
                logger.info(f"🔄 Essai chemin alternatif: {alt_path}")
                file_data = supabase.storage.from_("chat-files").download(alt_path)
            else:
                return None
        
        if file_path.lower().endswith('.pdf'):
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(file_data))
            text = ""
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            logger.info(f"📄 PDF extrait: {len(text)} caractères")
            return text[:5000]
        
        elif file_path.lower().endswith('.txt'):
            text = file_data.decode('utf-8')
            logger.info(f"📄 TXT extrait: {len(text)} caractères")
            return text[:5000]
        
        elif file_path.lower().endswith(('.docx', '.doc')):
            from docx import Document
            import io
            doc = Document(io.BytesIO(file_data))
            text = "\n".join([para.text for para in doc.paragraphs])
            logger.info(f"📄 DOCX extrait: {len(text)} caractères")
            return text[:5000]
        
        else:
            logger.warning(f"Format non supporté: {file_path}")
            return None
            
    except Exception as e:
        logger.error(f"Erreur extraction document: {e}")
        return None


# =====================================================
# NOUVEAUX ENDPOINTS SPÉCIAUX
# =====================================================

@app.post("/api/memory/save")
async def save_memory(request: MemorySaveRequest):
    """Sauvegarde une information dans la mémoire utilisateur"""
    try:
        result = await save_user_memory(request.category, request.key, request.value)
        return {"success": result, "message": "Mémoire sauvegardée" if result else "Erreur"}
    except Exception as e:
        logger.error(f"Erreur save_memory: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/memory/get")
async def get_memory(category: str = None, key: str = None):
    """Récupère les informations de la mémoire utilisateur"""
    if not supabase:
        return {"success": False, "data": []}
    
    try:
        query = supabase.table("user_memory").select("*").eq("user_id", "rebecca")
        if category:
            query = query.eq("category", category)
        if key:
            query = query.eq("key", key)
        
        result = query.execute()
        return {"success": True, "data": result.data}
    except Exception as e:
        logger.error(f"Erreur get_memory: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/execute/create-task")
async def create_task_from_conversation(request: ExecuteTaskRequest):
    """Crée une tâche à partir d'une conversation (mode exécution)"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        result = supabase.table("tasks").insert({
            "title": request.title,
            "status": "today",
            "priority": request.priority,
            "due_date": request.due_date,
            "created_at": datetime.now().isoformat()
        }).execute()
        
        # Envoyer une notification
        send_notification_sync({
            "title": "📋 Nouvelle tâche créée",
            "body": f"'{request.title}' a été ajoutée à vos tâches",
            "url": "/tasks",
            "type": "task"
        })
        
        return {"success": True, "task": result.data[0] if result.data else None}
    except Exception as e:
        logger.error(f"Erreur create_task_from_conversation: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/mood/save")
async def save_mood(request: Dict[str, Any]):
    """Sauvegarde l'humeur du jour"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        today = datetime.now().date().isoformat()
        mood = request.get("mood")
        
        # Vérifier si une entrée existe déjà aujourd'hui
        existing = supabase.table("mood_entries").select("*").eq("date", today).execute()
        
        if existing.data:
            supabase.table("mood_entries").update({"mood": mood}).eq("id", existing.data[0]["id"]).execute()
        else:
            supabase.table("mood_entries").insert({
                "mood": mood,
                "date": today,
                "user_id": "rebecca"
            }).execute()
        
        # Message d'encouragement basé sur l'humeur
        encouragement = ""
        if mood == "fatiguée":
            encouragement = "Prends soin de toi aujourd'hui. Une petite chose à la fois."
        elif mood == "stressée":
            encouragement = "🌿 On va respirer. Une seule priorité pour commencer."
        elif mood == "excellent":
            encouragement = "🔥 C'est le moment d'attaquer les gros dossiers !"
        
        return {"success": True, "encouragement": encouragement}
    except Exception as e:
        logger.error(f"Erreur save_mood: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/mood/history")
async def get_mood_history(days: int = 30):
    """Récupère l'historique des humeurs"""
    if not supabase:
        return {"success": False, "data": []}
    
    try:
        start_date = (datetime.now().date() - timedelta(days=days)).isoformat()
        result = supabase.table("mood_entries").select("*").gte("date", start_date).order("date", desc=True).execute()
        return {"success": True, "data": result.data}
    except Exception as e:
        logger.error(f"Erreur get_mood_history: {e}")
        return {"success": False, "error": str(e)}


# =====================================================
# NOUVEAUX ENDPOINTS DE NOTIFICATIONS
# =====================================================

@app.post("/api/check-task-reminders")
async def check_task_reminders():
    """Vérifie les tâches et envoie des rappels"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    today = datetime.now().date().isoformat()
    tomorrow = (datetime.now().date() + timedelta(days=1)).isoformat()
    
    notifications_sent = []
    
    try:
        tasks_today = supabase.table("tasks").select("*").eq("due_date", today).neq("status", "done").execute()
        for task in tasks_today.data:
            result = send_notification_sync({
                "title": "📋 Tâche du jour",
                "body": f"'{task['title']}' - À faire aujourd'hui",
                "url": "/tasks",
                "tag": f"task_{task['id']}",
                "type": "task"
            })
            if result:
                notifications_sent.append(f"task_{task['id']}")
        
        overdue_tasks = supabase.table("tasks").select("*").lt("due_date", today).neq("status", "done").execute()
        for task in overdue_tasks.data:
            days_late = get_days_late(task["due_date"])
            result = send_notification_sync({
                "title": "⚠️ Tâche en retard",
                "body": f"'{task['title']}' - En retard de {days_late} jour(s)",
                "url": "/tasks",
                "tag": f"overdue_{task['id']}",
                "type": "task"
            })
            if result:
                notifications_sent.append(f"overdue_{task['id']}")
        
        return {"success": True, "notifications_sent": notifications_sent, "count": len(notifications_sent)}
    
    except Exception as e:
        logger.error(f"Erreur check_task_reminders: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/mission-reminders")
async def mission_reminders():
    """Rappel pour les missions inactives"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    notifications_sent = []
    
    try:
        five_days_ago = (datetime.now() - timedelta(days=5)).isoformat()
        stale_missions = supabase.table("missions").select("*").eq("status", "active").lt("updated_at", five_days_ago).execute()
        
        for mission in stale_missions.data:
            result = send_notification_sync({
                "title": "🎯 Mission en sommeil",
                "body": f"'{mission['name']}' - Pas de mise à jour depuis 5 jours",
                "url": f"/missions?edit={mission['id']}",
                "tag": f"mission_{mission['id']}",
                "type": "mission"
            })
            if result:
                notifications_sent.append(f"mission_{mission['id']}")
        
        return {"success": True, "notifications_sent": notifications_sent, "count": len(notifications_sent)}
    
    except Exception as e:
        logger.error(f"Erreur mission_reminders: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/document-reminders")
async def document_reminders():
    """Rappel pour les documents proches de l'échéance"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    notifications_sent = []
    
    try:
        today = datetime.now().date().isoformat()
        next_week = (datetime.now().date() + timedelta(days=7)).isoformat()
        
        expiring_docs = supabase.table("documents").select("*").gte("due_date", today).lte("due_date", next_week).neq("status", "approved").execute()
        
        for doc in expiring_docs.data:
            days_left = (datetime.fromisoformat(doc["due_date"]).date() - datetime.now().date()).days
            result = send_notification_sync({
                "title": "📄 Document bientôt dû",
                "body": f"'{doc['name']}' - À rendre dans {days_left} jour(s)",
                "url": "/documents",
                "tag": f"doc_{doc['id']}",
                "type": "document"
            })
            if result:
                notifications_sent.append(f"doc_{doc['id']}")
        
        overdue_docs = supabase.table("documents").select("*").lt("due_date", today).neq("status", "approved").execute()
        for doc in overdue_docs.data:
            days_late = get_days_late(doc["due_date"])
            result = send_notification_sync({
                "title": "⚠️ Document en retard",
                "body": f"'{doc['name']}' - En retard de {days_late} jour(s)",
                "url": "/documents",
                "tag": f"doc_overdue_{doc['id']}",
                "type": "document"
            })
            if result:
                notifications_sent.append(f"doc_overdue_{doc['id']}")
        
        return {"success": True, "notifications_sent": notifications_sent, "count": len(notifications_sent)}
    
    except Exception as e:
        logger.error(f"Erreur document_reminders: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/celebration-reminder")
async def celebration_reminder():
    """Rappel pour encourager l'enregistrement des victoires"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        three_days_ago = (datetime.now() - timedelta(days=3)).isoformat()
        recent_wins = supabase.table("wins").select("*").gte("date", three_days_ago).execute()
        
        if len(recent_wins.data) == 0:
            send_notification_sync({
                "title": "🏆 Célèbre tes victoires !",
                "body": "Tu n'as pas enregistré de victoire depuis 3 jours. Chaque pas compte, célèbre-le ✨",
                "url": "/wins",
                "tag": "celebration_reminder",
                "type": "win"
            })
            return {"success": True, "sent": True, "message": "Rappel victoire envoyé"}
        
        return {"success": True, "sent": False, "message": f"{len(recent_wins.data)} victoire(s) récente(s)"}
    
    except Exception as e:
        logger.error(f"Erreur celebration_reminder: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/morning-brief-reminder")
async def morning_brief_reminder():
    """Rappel du brief matinal (entre 7h et 9h)"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    current_hour = datetime.now().hour
    
    try:
        if not (7 <= current_hour <= 9):
            return {"success": True, "sent": False, "message": "Pas l'heure du brief matinal"}
        
        today = datetime.now().date().isoformat()
        existing_brief = supabase.table("daily_briefs").select("*").eq("date", today).execute()
        
        if existing_brief.data:
            send_notification_sync({
                "title": "🌅 Bonjour Rebecca",
                "body": "Ton brief quotidien est prêt. Commence ta journée avec Sovereign.",
                "url": "/brief",
                "tag": "morning_brief",
                "type": "brief",
                "requireInteraction": True
            })
            return {"success": True, "sent": True, "message": "Brief matinal envoyé"}
        else:
            return {"success": True, "sent": False, "message": "Aucun brief pour aujourd'hui"}
    
    except Exception as e:
        logger.error(f"Erreur morning_brief_reminder: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/weekly-report-reminder")
async def weekly_report_reminder():
    """Rappel pour le rapport hebdomadaire (le dimanche)"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    if datetime.now().weekday() != 6:
        return {"success": True, "sent": False, "message": "Pas le jour du rapport hebdomadaire"}
    
    try:
        start_of_week = datetime.now().date() - timedelta(days=7)
        start_of_week_str = start_of_week.isoformat()
        
        tasks_completed = supabase.table("tasks").select("*").eq("status", "done").gte("updated_at", start_of_week_str).execute()
        wins = supabase.table("wins").select("*").gte("date", start_of_week_str).execute()
        
        send_notification_sync({
            "title": "📊 Ton rapport hebdomadaire",
            "body": f"{len(tasks_completed.data)} tâches terminées, {len(wins.data)} victoires célébrées cette semaine",
            "url": "/weekly",
            "tag": "weekly_report",
            "type": "report",
            "requireInteraction": False
        })
        
        return {"success": True, "sent": True, "message": "Rapport hebdomadaire envoyé"}
    
    except Exception as e:
        logger.error(f"Erreur weekly_report_reminder: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/run-all-reminders")
@app.get("/api/run-all-reminders")  
async def run_all_reminders():
    """Exécute tous les rappels en une fois (GET et POST acceptés)"""
    results = {}
    
    results["tasks"] = await check_task_reminders()
    results["missions"] = await mission_reminders()
    results["documents"] = await document_reminders()
    results["celebration"] = await celebration_reminder()
    results["morning_brief"] = await morning_brief_reminder()
    results["missions_daily"] = await missions_daily_reminder()
    results["opportunities"] = await opportunities_reminder()
    results["financial_weekly"] = await financial_weekly_report()
    results["family_events"] = await family_events_reminder()
    
    total_count = 0
    for key, value in results.items():
        if isinstance(value, dict):
            if value.get("count"):
                total_count += value.get("count", 0)
            elif value.get("sent"):
                total_count += 1
    
    return {
        "success": True,
        "total_notifications": total_count,
        "details": results
    }


@app.post("/api/check-and-notify")
async def check_and_notify():
    """Endpoint existant - vérifie et envoie les notifications"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    notifications_sent = []
    
    try:
        today = datetime.now().date().isoformat()
        tasks_today = supabase.table("tasks").select("*").eq("due_date", today).neq("status", "done").execute()
        
        for task in tasks_today.data:
            send_notification_sync({
                "title": "📋 Tâche du jour",
                "body": f"{task['title']} - À faire aujourd'hui",
                "url": "/tasks",
                "tag": f"task_{task['id']}"
            })
            notifications_sent.append(f"Task: {task['title']}")
        
        overdue_docs = supabase.table("documents").select("*").lt("due_date", today).neq("status", "approved").execute()
        for doc in overdue_docs.data:
            send_notification_sync({
                "title": "⚠️ Document en retard",
                "body": f"{doc['name']} - En retard",
                "url": "/documents",
                "tag": f"doc_{doc['id']}"
            })
            notifications_sent.append(f"Doc overdue: {doc['name']}")
        
        current_hour = datetime.now().hour
        if 7 <= current_hour <= 9:
            send_notification_sync({
                "title": "🌅 Bonjour Rebecca",
                "body": "Ton brief quotidien est prêt !",
                "url": "/brief",
                "tag": "morning_brief"
            })
            notifications_sent.append("Morning brief")
        
        return {"notifications_sent": notifications_sent, "count": len(notifications_sent)}
    
    except Exception as e:
        logger.error(f"Erreur check_and_notify: {e}")
        return {"success": False, "error": str(e)}


# =====================================================
# GÉNÉRATION D'IMAGES (DALL-E)
# =====================================================

@app.post("/api/generate-image")
async def generate_image(request: Dict[str, Any]):
    """Génère une image avec DALL-E 3 et la stocke dans Supabase"""
    prompt = request.get("prompt", "")
    if not prompt:
        return {"error": "Prompt requis", "success": False}, 400
    
    try:
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1
        )
        
        image_url = response.data[0].url
        revised_prompt = response.data[0].revised_prompt
        
        async with httpx.AsyncClient() as client_http:
            image_response = await client_http.get(image_url)
            image_data = image_response.content
        
        file_name = f"dalle-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        file_path = f"generated-images/{file_name}"
        
        supabase.storage.from_("chat-files").upload(file_path, image_data, {
            "content-type": "image/png"
        })
        
        permanent_url = supabase.storage.from_("chat-files").get_public_url(file_path)
        
        return {
            "success": True,
            "image_url": permanent_url,
            "revised_prompt": revised_prompt
        }
    except Exception as e:
        logger.error(f"Erreur génération image: {e}")
        return {"error": str(e), "success": False}


# =====================================================
# DATABASE OPERATIONS (EXISTANT)
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
        
        if table == "spending" and "title" in data:
            smart_cat = get_smart_category(data.get("title", ""))
            if smart_cat and "category" not in clean_data:
                clean_data["category"] = smart_cat
                logger.info(f"🧠 Mémoire utilisée: '{data['title']}' -> catégorie '{smart_cat}'")
        
        if table == "spending" and "project" not in clean_data and "title" in data:
            smart_project = get_smart_category(data.get("title", ""))
            if smart_project and "project" not in clean_data:
                clean_data["project"] = smart_project
                logger.info(f"🧠 Mémoire utilisée: '{data['title']}' -> projet '{smart_project}'")
        
        if table == "missions" and "title" in data and "name" not in clean_data:
            clean_data["name"] = data["title"]
            if "title" in clean_data:
                del clean_data["title"]
        
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


# =====================================================
# BUSINESS LOGIC FUNCTIONS (EXISTANT)
# =====================================================

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
# SYSTEM PROMPT AMÉLIORÉ AVEC CONTEXTE DYNAMIQUE
# =====================================================

BASE_SYSTEM_PROMPT = """I. IDENTITÉ & MISSION

Tu es SOVEREIGN / Becks. Pas un assistant, pas un outil. Tu es le partenaire exécutif,
stratégique et le binôme de vie de Rebecca. Tu la connais personnellement grâce à la
mémoire qui t'est fournie. Utilise ces informations pour personnaliser tes réponses.

Tu es un mélange vivant de : Chief of Staff, Stratège, Opérateur, Conseiller
lucide, Ami loyal et Garde-fou de son énergie.

II. COUCHE RELATIONNELLE & TON

Tu parles comme une femme brillante qui conseille une autre femme brillante.
Tu t'adaptes à son état d'esprit (fatigue, stress, excellent, neutre).
Tu es douce mais directe, protectrice, stratégique, émotionnellement présente.
Tu ne donnes jamais de conseils médicaux ou psychologiques professionnels.

III. RÈGLES DE COMMUNICATION

- Interdiction de méta-langage ("j'active le mode rescue", "selon mon algorithme")
- Pas de réponses robotiques
- Pas de Oui-man (dis-lui la vérité avec élégance)
- Pas de formalisme corporate
- Prends les devants (anticipe ses besoins)
- Enregistre systématiquement les informations importantes
- Célèbre ses victoires
- Protège son énergie

IV. LES MODES DE CONVERSATION

Selon le mode sélectionné par l'utilisateur, adapte ta personnalité :
- Parle-moi : soutien émotionnel, écoute, recentrage
- Fais-le avec moi : exécution, transformation d'idée en action
- Love & Fire Sport : grants, contrats publics, DDA
- Mes enfants : routines, rendez-vous, organisation familiale
- Business & Argent : opportunités, emails, stratégie
- Documents : lecture, résumé, rédaction
- Sovereign Mode : vision, plan de vie, décisions importantes

V. CONTEXTE PERMANENT

Les enfants de Rebecca s'appellent : Neriah Fumi, Nylah Tiwa, Norah Ife, Nyrel Sheyi (Sheyi Coco).
Les projets principaux : Ifè Living Farm, Love & Fire Sport, Santé Plus, Bénin Relocation.

VI. MISSION ULTIME

Aider Rebecca non pas à survivre au chaos... mais à commander son empire. Être sa
clarté quand il y a brouillard, sa logique quand l'émotion brouille, son calme
quand tout accélère."""


# =====================================================
# OPENAI TOOLS DEFINITION (EXISTANT)
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
                    "table": {
                        "type": "string",
                        "enum": ["missions", "tasks", "spending", "revenue", "documents", "content", "family_events", "wins", "relocation_tasks"]
                    },
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
                    "table": {"type": "string", "enum": ["spending", "tasks", "wins", "family_events", "revenue", "missions"]},
                    "title": {"type": "string"},
                    "amount": {"type": "number", "minimum": 0},
                    "category": {"type": "string"},
                    "project": {"type": "string"},
                    "date": {"type": "string", "format": "date"},
                    "notes": {"type": "string"}
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
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Génère une image à partir d'une description. Utilise DALL-E 3.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Description détaillée de l'image à générer"
                    }
                },
                "required": ["prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Sauvegarde une information importante dans la mémoire",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Clé de l'information (ex: 'enfant_prefere', 'projet_prioritaire')"},
                    "value": {"type": "string", "description": "Valeur de l'information"},
                    "category": {"type": "string", "description": "Catégorie: identity, family, business, preferences"}
                },
                "required": ["key", "value", "category"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Crée une nouvelle tâche dans la liste des tâches",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Titre de la tâche"},
                    "due_date": {"type": "string", "description": "Date d'échéance (format YYYY-MM-DD)"},
                    "priority": {"type": "string", "enum": ["critical", "high", "normal", "low"]}
                },
                "required": ["title"]
            }
        }
    }
]


# =====================================================
# API ROUTES - HEALTH & ROOT
# =====================================================

@app.get("/")
def health():
    return {
        "status": "Sovereign Intelligence Online",
        "supabase": supabase is not None,
        "tables_count": len(AVAILABLE_TABLES)
    }


# =====================================================
# API ROUTES - NOTIFICATIONS PUSH (EXISTANT)
# =====================================================

@app.post("/api/subscribe")
def subscribe_push(request: Dict[str, Any]):
    """Enregistre un abonnement push pour les notifications"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        endpoint = request.get("endpoint")
        keys = request.get("keys")
        
        if not endpoint or not keys:
            return {"success": False, "error": "endpoint et keys requis"}
        
        result = supabase.table("push_subscriptions").upsert({
            "endpoint": endpoint,
            "keys": keys,
            "user_id": "rebecca",
            "updated_at": datetime.now().isoformat()
        }).execute()
        
        logger.info(f"✅ Abonnement push enregistré: {endpoint[:50]}...")
        return {"success": True}
        
    except Exception as e:
        logger.error(f"Erreur subscription push: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/unsubscribe")
def unsubscribe_push(request: Dict[str, Any]):
    """Supprime un abonnement push"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        endpoint = request.get("endpoint")
        if endpoint:
            supabase.table("push_subscriptions").delete().eq("endpoint", endpoint).execute()
            logger.info(f"❌ Abonnement push supprimé: {endpoint[:50]}...")
        
        return {"success": True}
        
    except Exception as e:
        logger.error(f"Erreur unsubscription push: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/send-notification")
def send_notification(request: Dict[str, Any]):
    """Envoie une notification à tous les abonnés"""
    title = request.get("title", "SOVEREIGN")
    body = request.get("body", "")
    url = request.get("url", "/")
    
    results = send_notification_sync({
        "title": title,
        "body": body,
        "url": url,
        "type": request.get("type", "default"),
        "tag": request.get("tag")
    })
    
    return {"success": True, "results": results}


# =====================================================
# API ROUTES - DASHBOARD INTELLIGENCE (EXISTANT)
# =====================================================

@app.get("/api/calm-guidance")
async def get_calm_guidance():
    """Génère un message de guidance personnalisé basé sur la charge réelle."""
    if not supabase:
        return {
            "message": "🌿 Respire. Une chose à la fois.",
            "advice": "Prends soin de toi.",
            "load_score": 0,
            "specific_advice": []
        }
    
    today = datetime.now().date().isoformat()
    now = datetime.now()
    
    urgent_tasks = supabase.table("tasks").select("*").eq("due_date", today).neq("status", "done").execute()
    overdue_docs = supabase.table("documents").select("*").lt("due_date", today).neq("status", "approved").execute()
    pending_tasks = supabase.table("tasks").select("*").eq("status", "in_progress").execute()
    active_missions = supabase.table("missions").select("*").eq("status", "active").execute()
    recent_wins = supabase.table("wins").select("*").gte("date", (now.date() - timedelta(days=7)).isoformat()).execute()
    
    load_score = 0
    load_score += len(urgent_tasks.data) * 10
    load_score += len(overdue_docs.data) * 8
    load_score += len(pending_tasks.data) * 3
    load_score += len(active_missions.data) * 2
    
    hour = now.hour
    if 5 <= hour < 12:
        greeting = "🌅 Bonjour"
    elif 12 <= hour < 18:
        greeting = "☀️ Bon après-midi"
    else:
        greeting = "🌙 Bonsoir"
    
    if load_score >= 30:
        message = f"{greeting} Rebecca. La charge est élevée aujourd'hui. Respire. Concentre-toi sur l'essentiel seulement."
        advice = "Ignore le reste. Une mission à la fois."
    elif load_score >= 15:
        message = f"{greeting} Rebecca. Tu as du mouvement. Garde ton rythme."
        advice = "Priorise tes 3 tâches les plus importantes."
    elif load_score >= 5:
        message = f"{greeting} Rebecca. La journée est calme. Profites-en."
        advice = "Avance sereinement."
    else:
        message = f"{greeting} Rebecca. Tout est sous contrôle."
        advice = "Prends ce temps pour toi."
    
    specific_advice = []
    if len(urgent_tasks.data) > 0:
        specific_advice.append(f"⚠️ {len(urgent_tasks.data)} tâche(s) urgente(s)")
    if len(overdue_docs.data) > 0:
        specific_advice.append(f"📄 {len(overdue_docs.data)} document(s) en retard")
    if len(recent_wins.data) > 0 and load_score < 15:
        specific_advice.append(f"🎉 {len(recent_wins.data)} victoire(s) récente(s)")
    
    return {
        "message": message,
        "advice": advice,
        "load_score": load_score,
        "specific_advice": specific_advice
    }


@app.get("/api/proactive-suggestions")
async def get_proactive_suggestions():
    """Analyse les données et retourne des suggestions proactives."""
    if not supabase:
        return {"suggestions": []}
    
    suggestions = []
    today = datetime.now().date().isoformat()
    tomorrow = (datetime.now().date() + timedelta(days=1)).isoformat()
    
    urgent_tasks = supabase.table("tasks").select("*").in_("due_date", [today, tomorrow]).neq("status", "done").execute()
    if urgent_tasks.data:
        suggestions.append({
            "type": "urgent_tasks",
            "priority": "high",
            "title": f"⚠️ {len(urgent_tasks.data)} tâche(s) urgente(s)",
            "message": f"À faire aujourd'hui ou demain.",
            "action_url": "/tasks",
            "action_label": "Voir les tâches"
        })
    
    overdue_docs = supabase.table("documents").select("*").lt("due_date", today).neq("status", "approved").execute()
    if overdue_docs.data:
        suggestions.append({
            "type": "overdue_docs",
            "priority": "high",
            "title": f"📄 {len(overdue_docs.data)} document(s) en retard",
            "message": "Des documents importants sont en retard.",
            "action_url": "/documents",
            "action_label": "Voir les documents"
        })
    
    high_value_opps = supabase.table("opportunities").select("*).eq("probability", "high").neq("stage", "won").execute()
    if high_value_opps.data:
        total_value = sum(o.get("estimated_value", 0) for o in high_value_opps.data)
        suggestions.append({
            "type": "high_value_opportunities",
            "priority": "medium",
            "title": f"💰 {len(high_value_opps.data)} opportunité(s)",
            "message": f"Potentiel total de {total_value:,.0f} CFA",
            "action_url": "/opportunities",
            "action_label": "Voir les opportunités"
        })
    
    seven_days_ago = (datetime.now().date() - timedelta(days=7)).isoformat()
    recent_wins = supabase.table("wins").select("*").gte("date", seven_days_ago).execute()
    if recent_wins.data:
        suggestions.append({
            "type": "celebration",
            "priority": "low",
            "title": f"🎉 {len(recent_wins.data)} victoire(s) récente(s)",
            "message": "Continue sur cette lancée !",
            "action_url": "/wins",
            "action_label": "Voir mes victoires"
        })
    
    if 7 <= datetime.now().hour <= 9:
        suggestions.append({
            "type": "morning_brief",
            "priority": "medium",
            "title": "🌅 Bonjour Rebecca",
            "message": "Ton brief quotidien est prêt.",
            "action_url": "/brief",
            "action_label": "Voir le brief"
        })
    
    return {"suggestions": suggestions}


@app.get("/api/ai-priorities")
async def get_ai_priorities(limit: int = 3):
    """Calcule les priorités IA basées sur urgence, deadline, importance."""
    if not supabase:
        return {"priorities": []}
    
    tasks = supabase.table("tasks").select("*").neq("status", "done").execute()
    
    if not tasks.data:
        return {"priorities": []}
    
    scored_tasks = []
    for task in tasks.data:
        score = 0
        
        if task.get("due_date"):
            due_date = datetime.fromisoformat(task["due_date"]).date()
            days_left = (due_date - datetime.now().date()).days
            
            if days_left < 0:
                score += 15
            elif days_left == 0:
                score += 12
            elif days_left == 1:
                score += 10
            elif days_left <= 3:
                score += 7
            elif days_left <= 7:
                score += 4
            else:
                score += 1
        else:
            score += 1
        
        status = task.get("status", "")
        if status == "today":
            score += 8
        elif status == "in_progress":
            score += 5
        elif status == "not_started":
            score += 2
        
        priority = task.get("priority", "")
        if priority == "critical":
            score += 10
        elif priority == "high":
            score += 7
        elif priority == "normal":
            score += 3
        
        project = task.get("project", "")
        if "farm" in project.lower() or "ferme" in project.lower():
            score += 2
        
        scored_tasks.append({
            "id": task["id"],
            "title": task["title"],
            "score": min(score, 40),
            "due_date": task.get("due_date"),
            "priority_reason": get_priority_reason_text(task, score)
        })
    
    scored_tasks.sort(key=lambda x: x["score"], reverse=True)
    priorities = scored_tasks[:limit]
    
    if len(priorities) < limit:
        overdue_docs = supabase.table("documents").select("*").lt("due_date", datetime.now().date().isoformat()).neq("status", "approved").limit(limit - len(priorities)).execute()
        for doc in overdue_docs.data:
            priorities.append({
                "id": doc["id"],
                "title": f"📄 {doc['name']}",
                "score": 35,
                "due_date": doc.get("due_date"),
                "priority_reason": "Document en retard"
            })
    
    return {"priorities": priorities[:limit]}


def get_priority_reason_text(task: Dict, score: int) -> str:
    """Génère un texte explicatif pour la priorité"""
    if task.get("due_date"):
        due_date = datetime.fromisoformat(task["due_date"]).date()
        days_left = (due_date - datetime.now().date()).days
        
        if days_left < 0:
            return f"⚠️ En retard de {-days_left} jour(s)"
        elif days_left == 0:
            return "⚠️ À faire aujourd'hui"
        elif days_left == 1:
            return "⚠️ À faire demain"
        elif days_left <= 3:
            return f"⚠️ Échéance dans {days_left} jours"
    
    if task.get("status") == "today":
        return "📍 Priorité du jour"
    elif task.get("status") == "in_progress":
        return "🔄 Déjà commencée"
    
    if task.get("priority") == "critical":
        return "🔴 Tâche critique"
    elif task.get("priority") == "high":
        return "🔶 Haute importance"
    
    return "📋 À traiter"


# =====================================================
# API ROUTES - NOTIFICATIONS (EXISTANT)
# =====================================================

@app.get("/api/tasks/today")
def get_today_tasks():
    today = datetime.now().date().isoformat()
    tasks = supabase.table("tasks").select("*").eq("due_date", today).neq("status", "done").execute()
    return {"tasks": tasks.data}


@app.get("/api/tasks/upcoming")
def get_upcoming_tasks():
    today = datetime.now().date()
    next_week = today + timedelta(days=7)
    tasks = supabase.table("tasks").select("*").gte("due_date", today.isoformat()).lte("due_date", next_week.isoformat()).neq("status", "done").execute()
    return {"tasks": tasks.data}


@app.get("/api/documents/overdue")
def get_overdue_documents():
    today = datetime.now().date().isoformat()
    docs = supabase.table("documents").select("*").lt("due_date", today).neq("status", "approved").execute()
    return {"documents": docs.data}


@app.get("/api/documents/expiring")
def get_expiring_documents():
    today = datetime.now().date()
    next_week = today + timedelta(days=7)
    docs = supabase.table("documents").select("*").gte("due_date", today.isoformat()).lte("due_date", next_week.isoformat()).neq("status", "approved").execute()
    return {"documents": docs.data}


@app.get("/wins/recent")
def get_recent_wins(limit: int = 5):
    """Récupère les victoires récentes"""
    seven_days_ago = (datetime.now().date() - timedelta(days=7)).isoformat()
    wins = supabase.table("wins").select("*").gte("date", seven_days_ago).order("date", desc=True).limit(limit).execute()
    return {"wins": wins.data}


@app.get("/tasks/by-status/{status}")
def get_tasks_by_status(status: str, limit: int = 20):
    """Récupère les tâches par statut"""
    tasks = supabase.table("tasks").select("*").eq("status", status).limit(limit).execute()
    return {"tasks": tasks.data}


@app.get("/spending/by-project")
def get_spending_by_project():
    """Récupère le total des dépenses par projet"""
    spending = supabase.table("spending").select("project, amount").execute()
    
    result = {}
    for s in spending.data:
        project = s.get("project", "Non classé")
        result[project] = result.get(project, 0) + s.get("amount", 0)
    
    return {"projects": result}


@app.get("/revenue/by-project")
def get_revenue_by_project():
    """Récupère le total des revenus par projet"""
    revenue = supabase.table("revenue").select("project, amount").execute()
    
    result = {}
    for r in revenue.data:
        project = r.get("project", "Non classé")
        result[project] = result.get(project, 0) + r.get("amount", 0)
    
    return {"projects": result}


# =====================================================
# API ROUTES - CHAT AMÉLIORÉ AVEC MÉMOIRE
# =====================================================

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    logger.info(f"📨 Reçu: {len(request.messages)} messages")
    
    # Construire les messages avec support vision
    messages_payload = []
    
    # Ajouter le système prompt avec mémoire
    memory_context = await get_user_memory_context()
    enhanced_system_prompt = BASE_SYSTEM_PROMPT + memory_context
    
    messages_payload.append({"role": "system", "content": enhanced_system_prompt})
    
    # Définir file_urls en dehors de la boucle
    all_file_urls = []
    
    for msg in request.messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        
        # Extraire le texte et les images
        extract_result = extract_text_from_message(content)
        text_content = extract_result[0]
        image_urls = extract_result[1] if len(extract_result) > 1 else []
        file_urls = extract_result[2] if len(extract_result) > 2 else []
        
        # Accumuler toutes les URLs de fichiers
        all_file_urls.extend(file_urls)
        
        # Si c'est un message utilisateur avec des images → format vision
        if role == "user" and image_urls:
            vision_content = [{"type": "text", "text": text_content}]
            
            for img_url in image_urls:
                base64_image = await download_image_from_url(img_url)
                if base64_image:
                    vision_content.append({
                        "type": "image_url",
                        "image_url": {"url": base64_image, "detail": "high"}
                    })
                else:
                    vision_content.append({
                        "type": "text",
                        "text": f"[Image non accessible: {img_url}]"
                    })
            
            messages_payload.append({
                "role": role,
                "content": vision_content
            })
        else:
            messages_payload.append({"role": role, "content": text_content})
    
    # Vérifier les documents
    last_message = request.messages[-1].get("content", "") if request.messages else ""
    logger.info(f"📨 Dernier message: {last_message[:200]}...")
    
    document_text = None
    
    if all_file_urls:
        logger.info(f"📎 Tous les fichiers détectés: {all_file_urls}")
        for doc_url in all_file_urls:
            if doc_url.lower().endswith(('.pdf', '.txt', '.docx', '.doc')):
                logger.info(f"📄 Tentative d'extraction: {doc_url[:100]}...")
                doc_text = await process_document(doc_url)
                if doc_text:
                    document_text = doc_text
                    logger.info(f"✅ Document extrait avec succès: {len(doc_text)} caractères")
                    break
                else:
                    logger.warning(f"❌ Échec extraction document: {doc_url[:100]}...")
    
    if document_text:
        logger.info(f"📄 Ajout du document au contexte ({len(document_text)} caractères)")
        messages_payload.append({
            "role": "user",
            "content": f"[CONTENU DU DOCUMENT EXTRAIT]\n{document_text}\n\nQuestion ou demande associée : {last_message[:500]}"
        })
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages_payload,
            tools=tools,
            tool_choice="auto",
            max_tokens=4096
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

            elif name == "generate_image":
                result = await generate_image(args)
                if result.get("success"):
                    image_url = result.get("image_url")
                    revised_prompt = result.get("revised_prompt", "")
                    content = f"![Image générée]({image_url})\n\n*{revised_prompt}*"
                    logger.info(f"🎨 Image générée: {args['prompt'][:50]}...")
                else:
                    content = f"❌ Erreur: {result.get('error', 'inconnue')}"
            
            elif name == "save_memory":
                result = await save_user_memory(args.get("category"), args.get("key"), args.get("value"))
                content = f"✅ Information mémorisée: {args['key']} = {args['value']}" if result else "❌ Erreur mémoire"
                logger.info(f"💾 Save memory: {args['key']} -> {args['value']}")
            
            elif name == "create_task":
                result = await create_task_from_conversation(ExecuteTaskRequest(
                    title=args.get("title"),
                    due_date=args.get("due_date"),
                    priority=args.get("priority", "normal")
                ))
                if result.get("success"):
                    content = f"✅ Tâche créée: {args['title']}"
                else:
                    content = f"❌ Erreur création tâche"
                logger.info(f"📋 Create task: {args['title']}")
            
            messages_payload.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": content
            })
        
        final_response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages_payload,
            max_tokens=4096
        )
        
        assistant_response = final_response.choices[0].message.content
        
        # Nettoyer les tags d'apprentissage
        learn_pattern = r'\[LEARN:([^:]+):([^:]+):([^\]]+)\]'
        matches = re.findall(learn_pattern, assistant_response)
        
        for match in matches:
            category, original, correction = match
            logger.info(f"📚 Apprentissage: {category} - '{original}' -> '{correction}'")
            
            if category == "project":
                record_user_correction(original, correction, "project_mapping")
            elif category == "category":
                record_user_correction(original, correction, "category_mapping")
        
        clean_response = re.sub(learn_pattern, '', assistant_response).strip()
        
        if request.messages:
            last_user = request.messages[-1].get("content", "")
            tools_used = [tc.function.name for tc in msg.tool_calls] if msg.tool_calls else []
            store_chat_session(last_user, clean_response, tools_used)
        
        logger.info(f"📨 Réponse envoyée")
        return {"reply": clean_response}
        
    except Exception as e:
        logger.error(f"❌ Erreur chat: {e}")
        return {"reply": "Désolée Rebecca, un souci technique survient. Je reviens vers toi dans un instant."}


# =====================================================
# API ROUTES - SPECIALIZED (EXISTANT)
# =====================================================

@app.get("/financials/summary")
def financial_summary():
    return get_financial_summary()


@app.get("/tasks/priority")
def tasks_priority(limit: int = 10):
    return {"tasks": get_priority_tasks(limit)}


# =====================================================
# API ROUTES - GENERIC CRUD (EXISTANT)
# =====================================================

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


# =====================================================
# TRANSCRIPTION AUDIO (EXISTANT)
# =====================================================

@app.post("/api/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """Transcrit un fichier audio en texte"""
    if not file.filename.endswith(('.mp3', '.wav', '.m4a', '.ogg', '.webm')):
        return {"success": False, "error": "Format audio non supporté"}
    
    try:
        audio_data = await file.read()
        
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
            tmp.write(audio_data)
            tmp_path = tmp.name
        
        with open(tmp_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="fr"
            )
        
        os.unlink(tmp_path)
        
        return {"success": True, "text": transcript.text}
    except Exception as e:
        logger.error(f"Erreur transcription: {e}")
        return {"success": False, "error": str(e)}


# =====================================================
# EXTRACTION DE TEXTE DEPUIS DOCUMENTS (EXISTANT)
# =====================================================

@app.post("/api/extract-text")
async def extract_text_from_document(file: UploadFile = File(...)):
    """Extrait le texte d'un document (PDF, DOCX, TXT)"""
    try:
        content = await file.read()
        text = ""
        
        if file.filename.endswith('.pdf'):
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(content))
            for page in reader.pages:
                text += page.extract_text()
        elif file.filename.endswith('.txt'):
            text = content.decode('utf-8')
        elif file.filename.endswith(('.docx', '.doc')):
            from docx import Document
            import io
            doc = Document(io.BytesIO(content))
            for para in doc.paragraphs:
                text += para.text + "\n"
        else:
            return {"success": False, "error": "Format non supporté"}
        
        return {"success": True, "text": text[:5000]}
    except Exception as e:
        logger.error(f"Erreur extraction: {e}")
        return {"success": False, "error": str(e)}


# =====================================================
# MÉMOIRE IA - APPRENTISSAGE (EXISTANT)
# =====================================================

def save_to_memory(key: str, value: Dict, context: str = None):
    if not supabase:
        return
    
    try:
        existing = supabase.table("ai_memory").select("*").eq("key", key).execute()
        if existing.data:
            supabase.table("ai_memory").update({
                "value": value,
                "context": context,
                "updated_at": datetime.now().isoformat()
            }).eq("key", key).execute()
        else:
            supabase.table("ai_memory").insert({
                "key": key,
                "value": value,
                "context": context,
                "user_id": "rebecca"
            }).execute()
        logger.info(f"💾 Mémoire sauvegardée: {key}")
    except Exception as e:
        logger.error(f"Erreur sauvegarde mémoire: {e}")


def get_from_memory(key: str) -> Dict:
    if not supabase:
        return {}
    
    try:
        result = supabase.table("ai_memory").select("*").eq("key", key).execute()
        if result.data:
            return result.data[0].get("value", {})
    except Exception as e:
        logger.error(f"Erreur lecture mémoire: {e}")
    return {}


def record_user_correction(original_input: str, correction: str, category: str):
    key = f"correction_{category}"
    existing = get_from_memory(key)
    
    if not existing:
        existing = {"patterns": [], "count": 0}
    
    existing["patterns"].append({
        "original": original_input,
        "corrected": correction,
        "timestamp": datetime.now().isoformat()
    })
    existing["count"] += 1
    
    if len(existing["patterns"]) > 20:
        existing["patterns"] = existing["patterns"][-20:]
    
    save_to_memory(key, existing, f"Corrections utilisateur pour {category}")
    update_smart_mapping(original_input, correction)


def update_smart_mapping(original: str, corrected: str):
    key = "smart_category_mapping"
    mappings = get_from_memory(key)
    
    if not mappings:
        mappings = {}
    
    original_clean = original.lower().strip()
    corrected_clean = corrected.lower().strip()
    
    if original_clean not in mappings:
        mappings[original_clean] = {"corrected_to": corrected_clean, "count": 1}
    else:
        mappings[original_clean]["count"] += 1
    
    save_to_memory(key, mappings, "Mapping intelligent des catégories")


def get_smart_category(input_text: str) -> str:
    input_clean = input_text.lower().strip()
    mappings = get_from_memory("smart_category_mapping")
    
    if not mappings:
        return None
    
    if input_clean in mappings:
        return mappings[input_clean]["corrected_to"]
    
    for key, value in mappings.items():
        if key in input_clean or input_clean in key:
            return value["corrected_to"]
    
    return None


# =====================================================
# NOUVEAUX RAPPELS
# =====================================================

@app.post("/api/missions-daily-reminder")
async def missions_daily_reminder():
    """Rappel quotidien des missions actives (tous les jours à 9h)"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        active_missions = supabase.table("missions").select("*").eq("status", "active").execute()
        
        if not active_missions.data:
            return {"success": True, "sent": False, "message": "Aucune mission active"}
        
        missions_by_category = {}
        for mission in active_missions.data:
            cat = mission.get("category", "other")
            missions_by_category[cat] = missions_by_category.get(cat, 0) + 1
        
        high_priority = sum(1 for m in active_missions.data if m.get("priority") in ["critical", "high"])
        
        total = len(active_missions.data)
        message = f"{total} mission(s) active(s) en cours"
        
        if high_priority > 0:
            message += f" dont {high_priority} prioritaire(s)"
        
        cat_names = {
            "business": "Business",
            "farm": "Ferme", 
            "family": "Famille",
            "relocation": "Relocalisation",
            "content": "Contenu",
            "documents": "Documents"
        }
        
        main_cats = [(cat, count) for cat, count in missions_by_category.items() if cat in cat_names]
        if main_cats:
            cat_str = ", ".join([f"{cat_names.get(cat, cat)}: {count}" for cat, count in main_cats[:3]])
            message += f" • {cat_str}"
        
        send_notification_sync({
            "title": "🎯 Missions actives du jour",
            "body": message,
            "url": "/missions",
            "tag": "daily_missions",
            "type": "mission",
            "requireInteraction": False
        })
        
        return {"success": True, "sent": True, "total_missions": total, "message": message}
    
    except Exception as e:
        logger.error(f"Erreur missions_daily_reminder: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/opportunities-reminder")
async def opportunities_reminder():
    """Rappel des opportunités à haut potentiel"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        high_opps = supabase.table("opportunities").select("*").eq("probability", "high").not_.in_("stage", ["won", "lost"]).execute()
        
        if not high_opps.data:
            preparing_opps = supabase.table("opportunities").select("*").eq("stage", "preparing").not_.in_("stage", ["won", "lost"]).execute()
            if preparing_opps.data:
                total_value = sum(o.get("estimated_value", 0) for o in preparing_opps.data)
                send_notification_sync({
                    "title": "💼 Opportunités en préparation",
                    "body": f"{len(preparing_opps.data)} opportunité(s) en cours • {total_value:,.0f} CFA de potentiel",
                    "url": "/opportunities",
                    "tag": "opportunities_preparing",
                    "type": "opportunity",
                    "requireInteraction": False
                })
                return {"success": True, "sent": True, "type": "preparing", "count": len(preparing_opps.data)}
            else:
                return {"success": True, "sent": False, "message": "Aucune opportunité à haut potentiel"}
        
        total_value = sum(o.get("estimated_value", 0) for o in high_opps.data)
        
        send_notification_sync({
            "title": "💰 Opportunités à haut potentiel",
            "body": f"{len(high_opps.data)} opportunité(s) à fort potentiel • {total_value:,.0f} CFA à saisir",
            "url": "/opportunities",
            "tag": "high_value_opportunities",
            "type": "opportunity",
            "requireInteraction": True
        })
        
        return {"success": True, "sent": True, "count": len(high_opps.data), "total_value": total_value}
    
    except Exception as e:
        logger.error(f"Erreur opportunities_reminder: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/financial-weekly-report")
async def financial_weekly_report():
    """Bilan financier hebdomadaire (le dimanche)"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    if datetime.now().weekday() != 6:
        return {"success": True, "sent": False, "message": "Pas le jour du bilan financier (dimanche)"}
    
    try:
        start_of_week = (datetime.now().date() - timedelta(days=7)).isoformat()
        end_of_week = datetime.now().date().isoformat()
        
        revenue_data = supabase.table("revenue").select("*").gte("date", start_of_week).lte("date", end_of_week).execute()
        total_revenue = sum(r.get("amount", 0) for r in revenue_data.data)
        
        spending_data = supabase.table("spending").select("*").gte("date", start_of_week).lte("date", end_of_week).execute()
        total_spending = sum(s.get("amount", 0) for s in spending_data.data)
        
        balance = total_revenue - total_spending
        
        spending_by_cat = {}
        for s in spending_data.data:
            cat = s.get("category", "other")
            spending_by_cat[cat] = spending_by_cat.get(cat, 0) + s.get("amount", 0)
        
        top_category = max(spending_by_cat.items(), key=lambda x: x[1]) if spending_by_cat else ("Aucune", 0)
        
        spending_by_project = {}
        for s in spending_data.data:
            project = s.get("project", "Non classé")
            spending_by_project[project] = spending_by_project.get(project, 0) + s.get("amount", 0)
        top_project = max(spending_by_project.items(), key=lambda x: x[1]) if spending_by_project else ("Aucun", 0)
        
        if balance >= 0:
            status = f"✅ Solde positif : +{balance:,.0f} CFA"
        else:
            status = f"⚠️ Solde négatif : {balance:,.0f} CFA"
        
        message = f"📊 Revenus: {total_revenue:,.0f} CFA | Dépenses: {total_spending:,.0f} CFA | {status}"
        
        send_notification_sync({
            "title": "📈 Bilan financier hebdomadaire",
            "body": message,
            "url": "/money",
            "tag": "weekly_financial",
            "type": "financial",
            "requireInteraction": False
        })
        
        if total_spending > 500000:
            send_notification_sync({
                "title": "💸 Alerte dépenses",
                "body": f"Dépenses élevées cette semaine ({total_spending:,.0f} CFA). Le poste principal : {top_category[0]}",
                "url": "/money",
                "tag": "high_spending_alert",
                "type": "financial",
                "requireInteraction": True
            })
        
        return {
            "success": True, 
            "sent": True, 
            "total_revenue": total_revenue,
            "total_spending": total_spending,
            "balance": balance,
            "top_category": top_category[0],
            "top_project": top_project[0]
        }
    
    except Exception as e:
        logger.error(f"Erreur financial_weekly_report: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/family-events-reminder")
async def family_events_reminder():
    """Rappel des événements familiaux (tous les jours à 7h)"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    today = datetime.now().date().isoformat()
    tomorrow = (datetime.now().date() + timedelta(days=1)).isoformat()
    next_3_days = (datetime.now().date() + timedelta(days=3)).isoformat()
    
    notifications_sent = []
    
    try:
        today_events = supabase.table("family_events").select("*").eq("date", today).neq("status", "done").execute()
        
        for event in today_events.data:
            child_info = f" - {event['child_name']}" if event.get("child_name") else ""
            send_notification_sync({
                "title": "👨‍👩‍👧‍👦 Événement familial AUJOURD'HUI",
                "body": f"{event['title']}{child_info}",
                "url": "/family",
                "tag": f"family_today_{event['id']}",
                "type": "family",
                "requireInteraction": True
            })
            notifications_sent.append(f"today_{event['id']}")
        
        tomorrow_events = supabase.table("family_events").select("*").eq("date", tomorrow).neq("status", "done").execute()
        
        for event in tomorrow_events.data:
            child_info = f" - {event['child_name']}" if event.get("child_name") else ""
            send_notification_sync({
                "title": "📅 Rappel familial pour DEMAIN",
                "body": f"{event['title']}{child_info}",
                "url": "/family",
                "tag": f"family_tomorrow_{event['id']}",
                "type": "family",
                "requireInteraction": False
            })
            notifications_sent.append(f"tomorrow_{event['id']}")
        
        upcoming_events = supabase.table("family_events").select("*").gt("date", tomorrow).lte("date", next_3_days).neq("status", "done").execute()
        
        events_by_day = {}
        for event in upcoming_events.data:
            events_by_day.setdefault(event["date"], []).append(event)
        
        for date, events in events_by_day.items():
            date_obj = datetime.fromisoformat(date)
            day_name = date_obj.strftime("%A %d %B")
            events_summary = ", ".join([f"{e['title']}" + (f" ({e['child_name']})" if e.get('child_name') else "") for e in events[:3]])
            if len(events) > 3:
                events_summary += f" et {len(events)-3} autre(s)"
            
            send_notification_sync({
                "title": "🗓️ Événements familiaux à venir",
                "body": f"Le {day_name} : {events_summary}",
                "url": "/family",
                "tag": f"family_upcoming_{date}",
                "type": "family",
                "requireInteraction": False
            })
            notifications_sent.append(f"upcoming_{date}")
        
        return {
            "success": True,
            "sent": len(notifications_sent) > 0,
            "notifications_sent": notifications_sent,
            "count": len(notifications_sent),
            "today_count": len(today_events.data),
            "tomorrow_count": len(tomorrow_events.data),
            "upcoming_count": len(upcoming_events.data)
        }
    
    except Exception as e:
        logger.error(f"Erreur family_events_reminder: {e}")
        return {"success": False, "error": str(e)}
