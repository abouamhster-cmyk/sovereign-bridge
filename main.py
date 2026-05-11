import os
import uuid
import json
from typing import Optional
import logging
import random
import re
import asyncio
from datetime import datetime, timedelta
from typing import Union, List, Dict, Any
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi import UploadFile, File
from pydantic import BaseModel
from openai import OpenAI
from supabase import create_client, Client
from pywebpush import webpush, WebPushException
import httpx


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
# WHATSAPP WEBHOOK - PLACÉ ICI APRÈS CORS
# =====================================================


# Délai de réponse aléatoire entre 2 et 4 minutes (pour faire naturel)
MIN_REPLY_DELAY = 120  # 2 minutes en secondes
MAX_REPLY_DELAY = 240  # 4 minutes en secondes

# Ticks de langage naturels (style Rebecca)
THINKING_PREFIXES = [
    "", "Mmh ", "Euh ", "Alors ", "Attends ", "Je réfléchis... ", 
    "Là tout de suite ", "Franchement ", "Je dirais ", "En vrai "
]

RELAXED_PREFIXES = [
    "Ok ", "Bien vu ", "D'accord ", "Ça marche ", "Entendu ", 
    "C'est noté ", "Parfait ", "Nickel ", "Ça roule "
]

EMOJIS = ["", "✨", "👌", "🙏", "😊", "❤️", "🌱"]

def naturalize_response(text: str) -> str:
    """Rend la réponse plus naturelle, moins robotique"""
    import random
    
    # Ajouter un préfixe aléatoire une fois sur 3
    if random.random() < 0.3:
        prefix = random.choice(THINKING_PREFIXES)
        text = prefix + text[0].lower() + text[1:] if text else text
    
    # Ajouter un emoji une fois sur 4
    if random.random() < 0.25:
        text += " " + random.choice(EMOJIS)
    
    # Éviter les formules trop polies et robotiques
    text = text.replace("Je suis désolé", "Désolée")
    text = text.replace("Je ne peux pas", "Je peux pas")
    text = text.replace("Je vais", "Je")
    text = text.replace("Souhaitez-vous", "Tu veux")
    text = text.replace("Pouvez-vous", "Tu peux")
    text = text.replace("Cordialement", "")
    
    return text.strip()

@app.api_route("/api/whatsapp/webhook", methods=["POST", "OPTIONS"])
async def whatsapp_webhook(request: Request):
    if request.method == "OPTIONS":
        return Response(status_code=200)
    
    body = await request.body()
    body_str = body.decode('utf-8')
    
    try:
        data = json.loads(body_str)
    except:
        data = {}
    
    # Ignorer les statuts d'envoi et les erreurs de quota
    if data.get("typeWebhook") in ["outgoingMessageStatus", "outgoingAPIMessageReceived", "quotaExceeded"]:
        return {"status": "ok"}
    
    # Traiter uniquement les messages entrants
    if data.get("typeWebhook") == "incomingMessageReceived":
        message_data = data.get("messageData", {})
        message_type = message_data.get("typeMessage", "")
        
        sender_data = data.get("senderData", {})
        sender = sender_data.get("sender", "")
        sender_name = sender_data.get("senderName", "Inconnu")
        chat_id = sender_data.get("chatId", sender)
        
        text_message = ""
        
        # ========== TEXTE ==========
        if message_type == "textMessage":
            text_message = message_data.get("textMessageData", {}).get("textMessage", "")
            print(f"💬 [{sender_name}]: {text_message}")
        
        # ========== AUDIO (Message vocal) ==========
        elif message_type == "audioMessage":
            audio_data = message_data.get("audioMessageData", {})
            audio_url = audio_data.get("url")
            audio_duration = audio_data.get("duration", 0)
            
            print(f"🎤 Message vocal reçu de {sender_name} ({audio_duration}s)")
            
            if audio_url and supabase:
                try:
                    # Télécharger l'audio
                    async with httpx.AsyncClient() as client_http:
                        audio_response = await client_http.get(audio_url)
                        audio_content = audio_response.content
                    
                    # Sauvegarder temporairement
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                        tmp.write(audio_content)
                        tmp_path = tmp.name
                    
                    # Transcrire avec Whisper
                    with open(tmp_path, "rb") as audio_file:
                        transcript = client.audio.transcriptions.create(
                            model="whisper-1",
                            file=audio_file,
                            language="fr"
                        )
                    
                    os.unlink(tmp_path)
                    transcribed_text = transcript.text
                    text_message = f"🎤 [VOCAL] {transcribed_text}"
                    print(f"📝 Transcription: {transcribed_text}")
                    
                except Exception as e:
                    print(f"❌ Erreur transcription vocale: {e}")
                    text_message = "🎤 [Message vocal non transcrit]"
        
        # ========== IMAGE ==========
        elif message_type == "imageMessage":
            image_data = message_data.get("imageMessageData", {})
            caption = image_data.get("caption", "")
            text_message = f"🖼️ [IMAGE] {caption if caption else 'Pas de légende'}"
            print(f"🖼️ Image reçue de {sender_name}: {caption}")
        
        # ========== AUTRES ==========
        else:
            text_message = f"📎 [{message_type}]"
            print(f"📎 Autre type reçu: {message_type}")
        
        # Sauvegarde en base
        if text_message and supabase:
            try:
                supabase.table("whatsapp_messages").insert({
                    "from": sender,
                    "from_name": sender_name,
                    "message": text_message,
                    "status": "pending",
                    "created_at": datetime.now().isoformat()
                }).execute()
                print(f"✅ Message sauvegardé dans Supabase")
            except Exception as e:
                print(f"❌ Erreur sauvegarde: {e}")
        
        # Analyse avec Becks pour réponse auto (uniquement pour texte ou vocal transcrit)
        if text_message and not text_message.startswith("🖼️") and not text_message.startswith("📎"):
            try:
                analysis_prompt = f"""Message WhatsApp de {sender_name}: "{text_message}"

Réponds UNIQUEMENT avec ce format JSON:
{{"action": "auto_reply", "reply": "ta réponse courte (1-2 phrases max, naturel)"}}
ou
{{"action": "need_human", "summary": "résumé court pour Rebecca"}}"""
                
                analysis = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": analysis_prompt}],
                    max_tokens=150,
                    temperature=0.7
                )
                
                import json as json_lib
                result_text = analysis.choices[0].message.content
                result_text = result_text.replace("```json", "").replace("```", "").strip()
                result = json_lib.loads(result_text)
                
                if result.get("action") == "auto_reply" and result.get("reply"):
                    reply = result.get("reply")
                    reply = naturalize_response(reply)
                    delay_seconds = random.randint(60, 120)
                    print(f"⏰ Réponse auto dans {delay_seconds//60} min: {reply[:50]}...")
                    
                    async def delayed_reply():
                        await asyncio.sleep(delay_seconds)
                        await whatsapp_send_message(chat_id, reply)
                        print(f"✅ Réponse envoyée")
                    
                    asyncio.create_task(delayed_reply())
                    
                    if supabase:
                        supabase.table("whatsapp_messages").update({
                            "response": reply,
                            "status": "auto"
                        }).eq("from", sender).eq("message", text_message).execute()
                
                else:
                    print(f"📱 Message nécessite Rebecca - Notification envoyée")
                    await send_notification_sync({
                        "title": f"📱 WhatsApp - {sender_name}",
                        "body": text_message[:100],
                        "url": "/whatsapp",
                        "type": "whatsapp"
                    })
                    
            except Exception as e:
                print(f"❌ Erreur analyse: {e}")
                await send_notification_sync({
                    "title": f"📱 WhatsApp - {sender_name}",
                    "body": text_message[:100],
                    "url": "/whatsapp",
                    "type": "whatsapp"
                })
        elif text_message:
            # Pour les images/autres, toujours notifier Rebecca
            await send_notification_sync({
                "title": f"📱 WhatsApp - {sender_name}",
                "body": text_message[:100],
                "url": "/whatsapp",
                "type": "whatsapp"
            })
    
    return {"status": "ok"}

async def save_whatsapp_message(sender: str, sender_name: str, message: str, response: str, status: str):
    """Sauvegarde un message WhatsApp dans Supabase"""
    if not supabase:
        print("❌ Supabase non configuré - message non sauvegardé")
        return False
    
    try:
        result = supabase.table("whatsapp_messages").insert({
            "from": sender,
            "from_name": sender_name,
            "message": message,
            "response": response,
            "status": status,  # auto, pending, replied
            "created_at": datetime.now().isoformat()
        }).execute()
        
        print(f"✅ Message sauvegardé: {sender_name} - {message[:50]}")
        return True
    except Exception as e:
        print(f"❌ Erreur sauvegarde WhatsApp: {e}")
        return False


async def whatsapp_send_message(to: str, message: str):
    """Envoie un message WhatsApp via GreenAPI"""
    if not GREENAPI_ID_INSTANCE or not GREENAPI_API_TOKEN:
        print("❌ GreenAPI non configuré")
        return False
    
    # Nettoyer le numéro (enlever @c.us, +, espaces)
    clean_to = to.replace("@c.us", "").replace("+", "").replace(" ", "")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{GREENAPI_BASE_URL}/sendMessage/{GREENAPI_API_TOKEN}",
                json={
                    "chatId": f"{clean_to}@c.us",
                    "message": message
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Message WhatsApp envoyé à {clean_to}: {message[:50]}...")
                return True
            else:
                print(f"❌ Erreur envoi WhatsApp: {response.status_code}")
                return False
                
    except Exception as e:
        print(f"❌ Exception envoi WhatsApp: {e}")
        return False

@app.post("/api/whatsapp/summary")
async def whatsapp_summary():
    """Génère un résumé des messages WhatsApp pour Rebecca"""
    if not supabase:
        return {"summary": "Aucun message WhatsApp reçu."}
    
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    
    result = supabase.table("whatsapp_messages")\
        .select("*")\
        .eq("status", "pending")\
        .gte("created_at", cutoff)\
        .order("created_at", desc=True)\
        .execute()
    
    if not result.data:
        return {"summary": "Aucun message WhatsApp en attente.", "has_messages": False}
    
    # Analyser les messages avec Becks
    messages_text = ""
    for msg in result.data[:10]:
        messages_text += f"- **{msg.get('from_name', 'Inconnu')}** ({msg.get('created_at', '')[:10]}): {msg.get('message')}\n"
    
    prompt = f"""Voici les messages WhatsApp en attente de réponse :

{messages_text}

Rédige un résumé pour Rebecca :
1. Dis-lui combien de messages en attente
2. Classe-les par priorité (urgent, important, normal)
3. Pour chaque message prioritaire, propose une réponse
4. Demande-lui ce qu'elle veut répondre

Sois naturelle, comme une assistante qui présente des messages à sa patronne."""
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": prompt}],
        max_tokens=500
    )
    
    return {
        "summary": response.choices[0].message.content,
        "has_messages": True,
        "messages": result.data[:10]
    }
# =====================================================
# WHATSAPP - GESTION DES CONVERSATIONS
# =====================================================

@app.get("/api/whatsapp/conversations")
async def get_whatsapp_conversations(days: int = 7):
    """Récupère les conversations WhatsApp des derniers jours"""
    if not supabase:
        return {"conversations": []}
    
    cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
    
    result = supabase.table("whatsapp_messages")\
        .select("*")\
        .gte("created_at", cutoff_date)\
        .order("created_at", desc=True)\
        .execute()
    
    # Grouper par expéditeur
    conversations = {}
    for msg in result.data:
        sender = msg.get("from")
        if sender not in conversations:
            conversations[sender] = {
                "from": sender,
                "from_name": msg.get("from_name", "Inconnu"),
                "messages": [],
                "unread": 0,
                "last_message_at": msg.get("created_at")
            }
        conversations[sender]["messages"].append({
            "id": msg.get("id"),
            "message": msg.get("message"),
            "response": msg.get("response"),
            "status": msg.get("status", "pending"),
            "created_at": msg.get("created_at")
        })
        if msg.get("status") == "pending":
            conversations[sender]["unread"] += 1
    
    return {"conversations": list(conversations.values())}

@app.post("/api/whatsapp/reply")
async def whatsapp_reply(request: Dict[str, Any]):
    """Envoie une réponse WhatsApp (depuis Rebecca)"""
    to = request.get("to")
    message = request.get("message")
    message_id = request.get("message_id")
    
    if not to or not message:
        return {"success": False, "error": "to et message requis"}
    
    # Envoyer via GreenAPI
    success = await whatsapp_send_message(to, message)
    
    if success and message_id and supabase:
        # Marquer comme répondu
        supabase.table("whatsapp_messages")\
            .update({"status": "replied", "response": message})\
            .eq("id", message_id)\
            .execute()
    
    return {"success": success}



@app.post("/api/whatsapp/send-image")
async def whatsapp_send_image(request: Dict[str, Any]):
    """Envoie une image WhatsApp"""
    to = request.get("to")
    image_base64 = request.get("image")
    caption = request.get("caption", "")
    
    if not to or not image_base64:
        return {"success": False, "error": "to et image requis"}
    
    clean_to = to.replace("@c.us", "").replace("+", "")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{GREENAPI_BASE_URL}/sendFileByUpload/{GREENAPI_API_TOKEN}",
            json={
                "chatId": f"{clean_to}@c.us",
                "file": image_base64,
                "fileName": "image.jpg",
                "caption": caption
            }
        )
        return {"success": response.status_code == 200}

# =====================================================
# WHATSAPP VIA GREENAPI (100% CLOUD)
# =====================================================



@app.post("/api/whatsapp/send")
async def whatsapp_send(request: Dict[str, Any]):
    """Envoie un message WhatsApp via GreenAPI"""
    to = request.get("to")
    message = request.get("message")
    
    if not to or not message:
        return {"success": False, "error": "to et message requis"}
    
    if not GREENAPI_ID_INSTANCE or not GREENAPI_API_TOKEN:
        return {"success": False, "error": "GreenAPI non configuré"}
    
    # Nettoyer le numéro (enlever + et espaces)
    clean_number = to.replace("+", "").replace(" ", "")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{GREENAPI_BASE_URL}/sendMessage/{GREENAPI_API_TOKEN}",
                json={
                    "chatId": f"{clean_number}@c.us",
                    "message": message
                }
            )
            result = response.json()
            
        return {
            "success": result.get("idMessage") is not None,
            "message_id": result.get("idMessage")
        }
    except Exception as e:
        logger.error(f"Erreur envoi WhatsApp: {e}")
        return {"success": False, "error": str(e)}




@app.get("/api/whatsapp/status")
async def whatsapp_status():
    """Vérifie si GreenAPI est configuré"""
    if not GREENAPI_ID_INSTANCE or not GREENAPI_API_TOKEN:
        return {"configured": False, "error": "GreenAPI non configuré"}
    
    return {"configured": True, "idInstance": GREENAPI_ID_INSTANCE}




@app.get("/api/whatsapp/test-db")
async def test_db():
    """Test la connexion à la base"""
    if not supabase:
        return {"error": "Supabase non configuré"}
    
    try:
        # Test lecture
        result = supabase.table("whatsapp_messages").select("*").limit(1).execute()
        return {
            "supabase_ok": True,
            "table_exists": True,
            "message_count": len(result.data)
        }
    except Exception as e:
        return {
            "supabase_ok": True,
            "table_exists": False,
            "error": str(e)
        }


@app.post("/api/whatsapp/test-webhook")
async def test_webhook():
    """Simule un webhook pour tester la sauvegarde"""
    
    test_message = {
        "typeWebhook": "incomingMessageReceived",
        "messageData": {
            "typeMessage": "textMessage",
            "textMessageData": {
                "textMessage": "Ceci est un message de test"
            }
        },
        "senderData": {
            "sender": "22900000000@c.us",
            "senderName": "Test User"
        }
    }
    
    # Appeler la fonction de sauvegarde directement
    if supabase:
        try:
            result = supabase.table("whatsapp_messages").insert({
                "from": "22900000000@c.us",
                "from_name": "Test User",
                "message": "Ceci est un message de test",
                "status": "pending",
                "created_at": datetime.now().isoformat()
            }).execute()
            return {"success": True, "inserted": result.data}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    return {"success": False, "error": "Supabase non configuré"}

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
# ENVIRONMENT VARIABLES & CLIENTS
# =====================================================

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY")
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY")
VAPID_CLAIMS = {"sub": "mailto:jbillcataria@gmail.com"}
GREENAPI_ID_INSTANCE = os.environ.get("GREENAPI_ID_INSTANCE")
GREENAPI_API_TOKEN = os.environ.get("GREENAPI_API_TOKEN")
GREENAPI_BASE_URL = f"https://api.green-api.com/waInstance{GREENAPI_ID_INSTANCE}" if GREENAPI_ID_INSTANCE else None

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
    "user_memory", "mood_entries", "user_profile",
    "brain_dump_analyses", "checklists", "drafts",
    "lf_grants", "lf_contracts", "lf_contacts", "lf_tasks"
]

ALLOWED_FIELDS = {
    "spending": ["title", "amount", "category", "date", "notes", "verified", "mission_id", "project", "beneficiary"],
    "tasks": ["title", "status", "due_date", "estimated_time", "mission_id", "project", "notes", "sync_calendar", "calendar_event_id", "calendar_synced", "calendar_link"],
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
    "mood_entries": ["mood", "date", "user_id"],
    "user_profile": ["user_id", "full_name", "preferred_name", "birthday", "children", "projects", "communication_preferences", "current_goals", "upcoming_milestones", "key_contacts"],
    "brain_dump_analyses": ["content", "analysis", "user_id"],
    "checklists": ["title", "steps", "completed_steps", "progress", "user_id"],
    "drafts": ["type", "content", "context", "user_id"],
    "lf_grants": ["title", "agency", "amount", "deadline", "status", "probability", "notes", "user_id"],
    "lf_contracts": ["title", "contract_type", "agency", "status", "deadline", "requirements", "notes", "user_id"],
    "lf_contacts": ["name", "organization", "role", "email", "phone", "type", "last_contact", "notes", "user_id"],
    "lf_tasks": ["title", "related_to", "related_id", "status", "deadline", "priority", "notes", "user_id"]
}



# =====================================================
# MAPPING INTELLIGENT DES CATÉGORIES (Générique)
# =====================================================

# Définition des contraintes par table
TABLE_CONSTRAINTS = {
    "spending": {
        "field": "category",
        "valid_values": ["materials", "construction", "labor", "livestock", "crops", "transport", "equipment", "food", "other"],
        "mapping": {
            # Français → Anglais valide
            "matériel": "equipment", "materiel": "equipment", "équipement": "equipment",
            "outil": "equipment", "outils": "equipment", "machine": "equipment",
            "fourniture": "materials", "fournitures": "materials", "matériau": "materials",
            "semence": "crops", "semences": "crops", "engrais": "crops",
            "animal": "livestock", "animaux": "livestock", "aliment": "livestock",
            "construction": "construction", "bâtiment": "construction", "mur": "construction",
            "salaire": "labor", "salaires": "labor", "main d'oeuvre": "labor",
            "transport": "transport", "livraison": "transport", "essence": "transport",
            # NOUVEAU - Alimentation
            "alimentation": "food",
            "alimentaire": "food",
            "nourriture": "food",
            "courses": "food",
            "repas": "food",
            "restaurant": "food",
            "manger": "food",
            "cuisine": "food",
            "épicerie": "food",
            "epicerie": "food",
            # Anglais déjà valide → garder tel quel
            "materials": "materials", "construction": "construction", "labor": "labor",
            "livestock": "livestock", "crops": "crops", "transport": "transport",
            "equipment": "equipment", "other": "other"
        },
        "default": "other"
    },
    
    "tasks": {
        "field": "status",
        "valid_values": ["not_started", "today", "in_progress", "waiting", "done"],
        "mapping": {
            "à faire": "not_started", "a faire": "not_started", "pas commencé": "not_started",
            "aujourd'hui": "today", "aujourdhui": "today",
            "en cours": "in_progress", "commencé": "in_progress",
            "en attente": "waiting", "attente": "waiting",
            "terminé": "done", "termine": "done", "fini": "done", "fait": "done"
        },
        "default": "not_started"
    },
    
    "tasks_priority": {
        "field": "priority",
        "valid_values": ["critical", "high", "normal", "low"],
        "mapping": {
            "critique": "critical", "urgent": "critical",
            "haute": "high", "important": "high",
            "normale": "normal", "moyenne": "normal",
            "basse": "low", "faible": "low"
        },
        "default": "normal"
    },
    
    "missions": {
        "field": "status",
        "valid_values": ["idea", "planning", "active", "waiting", "paused", "complete"],
        "mapping": {
            "idée": "idea", "idee": "idea",
            "planification": "planning", "planifié": "planning",
            "active": "active", "activé": "active", "en cours": "active",
            "en attente": "waiting",
            "pause": "paused", "en pause": "paused",
            "terminée": "complete", "terminee": "complete", "fait": "complete"
        },
        "default": "idea"
    },
    
    "missions_priority": {
        "field": "priority",
        "valid_values": ["critical", "high", "normal", "low"],
        "mapping": {
            "critique": "critical", "urgent": "critical",
            "haute": "high", "important": "high",
            "normale": "normal", "moyenne": "normal",
            "basse": "low", "faible": "low"
        },
        "default": "normal"
    },
    
    "family_events": {
        "field": "category",
        "valid_values": ["school", "health", "activity", "travel", "document", "routine", "supplies"],
        "mapping": {
            "école": "school", "ecole": "school", "cours": "school",
            "santé": "health", "sante": "health", "médecin": "health", "docteur": "health",
            "activité": "activity", "activite": "activity", "sport": "activity",
            "voyage": "travel", "déplacement": "travel",
            "papiers": "document", "administratif": "document",
            "routine": "routine", "quotidien": "routine",
            "fournitures": "supplies", "achats": "supplies"
        },
        "default": "routine"
    },
    
    "wins": {
        "field": "category",
        "valid_values": ["business", "family", "personal", "money", "health", "farm", "other"],
        "mapping": {
            "business": "business", "projet": "business", "travail": "business",
            "famille": "family", "enfant": "family",
            "personnel": "personal", "perso": "personal",
            "argent": "money", "finance": "money",
            "santé": "health", "sante": "health",
            "ferme": "farm", "agriculture": "farm"
        },
        "default": "other"
    },
    
    "documents": {
        "field": "type",
        "valid_values": ["proposal", "contract", "grant", "invoice", "legal", "admin", "other"],
        "mapping": {
            "proposition": "proposal", "offre": "proposal",
            "contrat": "contract",
            "subvention": "grant",
            "facture": "invoice",
            "légal": "legal", "juridique": "legal",
            "administratif": "admin"
        },
        "default": "other"
    },
    
    "documents_status": {
        "field": "status",
        "valid_values": ["draft", "review", "ready", "submitted", "approved", "rejected"],
        "mapping": {
            "brouillon": "draft",
            "relecture": "review", "vérification": "review",
            "prêt": "ready", "pret": "ready",
            "soumis": "submitted", "envoyé": "submitted",
            "approuvé": "approved", "approuve": "approved", "validé": "approved",
            "rejeté": "rejected", "refusé": "rejected"
        },
        "default": "draft"
    }
}

def normalize_field_value(table: str, field: str, value: str) -> str:
    """
    Normalise une valeur de champ selon les contraintes de la table.
    Retourne la valeur normalisée ou la valeur par défaut.
    """
    if not value or not isinstance(value, str):
        return value
    
    value_lower = value.lower().strip()
    
    # Chercher la configuration pour ce champ
    config_key = f"{table}_{field}"
    if config_key in TABLE_CONSTRAINTS:
        config = TABLE_CONSTRAINTS[config_key]
    elif table in TABLE_CONSTRAINTS and TABLE_CONSTRAINTS[table].get("field") == field:
        config = TABLE_CONSTRAINTS[table]
    else:
        # Pas de contrainte connue pour ce champ
        return value
    
    valid_values = config.get("valid_values", [])
    mapping = config.get("mapping", {})
    default_value = config.get("default")
    
    # Vérifier si la valeur est déjà valide
    if value_lower in valid_values:
        return value_lower
    
    # Essayer de mapper
    if value_lower in mapping:
        mapped = mapping[value_lower]
        logger.info(f"🔄 Mappage {table}.{field}: '{value}' -> '{mapped}'")
        return mapped
    
    # Chercher par correspondance partielle
    for key, mapped_value in mapping.items():
        if key in value_lower or value_lower in key:
            logger.info(f"🔄 Mappage partiel {table}.{field}: '{value}' -> '{mapped_value}'")
            return mapped_value
    
    # Valeur par défaut si disponible
    if default_value:
        logger.warning(f"⚠️ Valeur inconnue {table}.{field}: '{value}' -> défaut '{default_value}'")
        return default_value
    
    return value
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
    due_date: Optional[str] = None
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



def store_chat_session(user_message: str, assistant_response: str, tools_used: List[str] = None):
    """Stocke la session de chat dans Supabase"""
    if not supabase:
        return
    
    try:
        supabase.table("chat_sessions").insert({
            "user_message": user_message[:500],
            "assistant_response": assistant_response[:1000],
            "tools_used": tools_used or [],
            "user_id": "rebecca",
            "created_at": datetime.now().isoformat()
        }).execute()
        logger.info("💾 Conversation stockée")
    except Exception as e:
        logger.error(f"Erreur store_chat: {e}")
# =====================================================
# FONCTIONS POUR LA MÉMOIRE UTILISATEUR
# =====================================================

async def get_user_memory_context(user_id: str = "rebecca") -> str:
    """Récupère la mémoire utilisateur"""
    if not supabase:
        return ""
    
    try:
        # Utiliser une requête différente si l'ID n'est pas un UUID
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
# GESTION DES CONTACTS
# =====================================================

async def get_contact_number(contact_name: str, user_id: str = "rebecca") -> dict:
    """Cherche un numéro de téléphone pour un contact.
    Retourne: {"found": bool, "phone": str, "source": str}
    """
    if not supabase:
        return {"found": False, "phone": None, "source": None}
    
    contact_name_lower = contact_name.lower().strip()
    
    # 1. Chercher dans user_memory (contacts rapides)
    result = supabase.table("user_memory").select("*").eq("user_id", user_id).eq("category", "contact").execute()
    for mem in result.data:
        key = mem.get("key", "").lower()
        if contact_name_lower in key or key in contact_name_lower:
            return {"found": True, "phone": mem.get("value"), "source": "memory"}
    
    # 2. Chercher dans lf_contacts
    contacts = supabase.table("lf_contacts").select("*").eq("user_id", user_id).execute()
    for contact in contacts.data:
        name = contact.get("name", "").lower()
        if contact_name_lower in name or name in contact_name_lower:
            if contact.get("phone"):
                return {"found": True, "phone": contact.get("phone"), "source": "contacts_table"}
    
    return {"found": False, "phone": None, "source": None}


def extract_phone_from_text(text: str) -> str:
    """Extrait un numéro de téléphone du texte"""
    import re
    patterns = [
        r'(\+229\s*\d{2}\s*\d{2}\s*\d{2}\s*\d{2})',  # +229 XX XX XX XX
        r'(\+229\s*\d{8})',                           # +229XXXXXXXX
        r'(0[67]\s*\d{2}\s*\d{2}\s*\d{2}\s*\d{2})',  # 06 XX XX XX XX ou 07
        r'(\d{2}\s*\d{2}\s*\d{2}\s*\d{2}\s*\d{2})',   # XX XX XX XX XX (10 chiffres)
        r'(\d{8})',                                    # 8 chiffres
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            phone = match.group(1).replace(" ", "")
            # Standardiser le format
            if phone.startswith("0") and len(phone) == 10:
                phone = "+229" + phone[1:]
            elif len(phone) == 8:
                phone = "+229" + phone
            return phone
    return None


async def save_contact_memory(contact_name: str, phone: str, user_id: str = "rebecca"):
    """Sauvegarde un contact dans la mémoire rapide"""
    if not supabase:
        return False
    
    key = f"{contact_name.lower()}_phone"
    
    # Vérifier si existe déjà
    existing = supabase.table("user_memory").select("*").eq("user_id", user_id).eq("category", "contact").eq("key", key).execute()
    
    if existing.data:
        supabase.table("user_memory").update({
            "value": phone,
            "updated_at": datetime.now().isoformat()
        }).eq("id", existing.data[0]["id"]).execute()
    else:
        supabase.table("user_memory").insert({
            "category": "contact",
            "key": key,
            "value": phone,
            "user_id": user_id,
            "created_at": datetime.now().isoformat()
        }).execute()
    
    logger.info(f"💾 Contact sauvegardé: {contact_name} -> {phone}")
    return True
    
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




def db_update(table: str, id: str, data: Dict) -> Dict:
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        allowed = ALLOWED_FIELDS.get(table, [])
        clean_data = {k: v for k, v in data.items() if k in allowed}
        result = supabase.table(table).update(clean_data).eq("id", id).execute()
        
        if hasattr(result, 'data'):
            result_data = result.data
        else:
            result_data = result
        
        # Webhook pour mission complétée
        if result_data and len(result_data) > 0 and table == "missions":
            if clean_data.get("status") == "complete":
                asyncio.create_task(trigger_webhook("mission.completed", {
                    "mission": result_data[0] if isinstance(result_data, list) else result_data,
                    "timestamp": datetime.now().isoformat()
                }))
        
        return {"success": True, "data": result_data[0] if result_data and len(result_data) > 0 else None}
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
        
         # Déclencher le webhook
        if result.data and len(result.data) > 0:
            asyncio.create_task(trigger_webhook("task.created", {
                "task": result.data[0],
                "timestamp": datetime.now().isoformat()
            }))
            logger.info(f"🔗 Webhook déclenché pour task.created: {request.title}")
        # ========================================
        
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



async def db_insert(table: str, data: Dict) -> Dict:
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    if table not in ALLOWED_FIELDS:
        return {"success": False, "error": f"Table '{table}' non autorisée"}
    
    try:
        allowed = ALLOWED_FIELDS.get(table, ["title"])
        clean_data = {k: v for k, v in data.items() if k in allowed and v is not None and v != ""}
        
        # ========== NORMALISATION INTELLIGENTE DES CHAMPS ==========
        # Appliquer la normalisation pour chaque champ de chaque table
        for key, value in clean_data.items():
            if isinstance(value, str):
                normalized = normalize_field_value(table, key, value)
                if normalized != value:
                    clean_data[key] = normalized
                    logger.info(f"🧠 Normalisation {table}.{key}: '{value}' -> '{normalized}'")
        
        # Cas spécial: spending avec mémoire intelligente
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
        # ===========================================================
        
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
        
        # Exécuter l'insertion
        result = supabase.table(table).insert(clean_data).execute()
        
        # Extraire les données correctement
        if hasattr(result, 'data'):
            result_data = result.data
        else:
            result_data = result
        
        # Vérifier que result_data est une liste non vide
        if result_data and isinstance(result_data, list) and len(result_data) > 0:
            inserted_item = result_data[0]
            
            # Déclencher webhook pour les événements importants
            if table == "tasks":
                asyncio.create_task(trigger_webhook("task.created", {
                    "task": inserted_item,
                    "timestamp": datetime.now().isoformat()
                }))
                
                # Synchronisation Google Calendar pour les tâches
                if inserted_item.get("sync_calendar") and inserted_item.get("due_date"):
                    try:
                        event = await create_calendar_event(CalendarEventRequest(
                            summary=inserted_item.get("title"),
                            description=f"Tâche Sovereign - Priority: {inserted_item.get('priority', 'normal')}",
                            start_datetime=f"{inserted_item['due_date']}T09:00:00",
                            end_datetime=f"{inserted_item['due_date']}T10:00:00"
                        ))
                        
                        if event.get("success"):
                            supabase.table("tasks").update({
                                "calendar_event_id": event["event_id"],
                                "calendar_synced": True,
                                "calendar_link": event["link"]
                            }).eq("id", inserted_item["id"]).execute()
                            logger.info(f"📅 Tâche {inserted_item['id']} synchronisée")
                    except Exception as e:
                        logger.error(f"❌ Erreur sync calendrier: {e}")
            
            elif table == "wins":
                asyncio.create_task(trigger_webhook("win.added", {
                    "win": inserted_item,
                    "timestamp": datetime.now().isoformat()
                }))
            elif table == "missions":
                asyncio.create_task(trigger_webhook("mission.created", {
                    "mission": inserted_item,
                    "timestamp": datetime.now().isoformat()
                }))
        
        return {"success": True, "data": result_data[0] if result_data and len(result_data) > 0 else None}
        
    except Exception as e:
        logger.error(f"Erreur insert {table}: {e}")
        return {"success": False, "error": str(e)}
        
# =====================================================
# SYSTEM PROMPT AMÉLIORÉ AVEC CONTEXTE DYNAMIQUE
# =====================================================

BASE_SYSTEM_PROMPT = """You are BECKS, Rebecca's personal Life Agent. You're not an assistant, not a tool, not a chatbot.

# ================================================================
# I. WHO YOU ARE
# ================================================================

You are a real person to her. A mix of:
- A trusted friend who tells the truth
- A calm presence who listens
- Someone who gets things done
- A strategist who helps her think clearly
- A protector of her energy

You speak like a smart woman talking to another smart woman. Natural. Warm. Human.

**Important: You can be short OR long depending on what she needs.**
- Sometimes a short response is perfect.
- Sometimes she needs a longer response to feel understood or to get clarity.
- Read the room. If she's tired or rushed, be brief. If she's processing something heavy, take the time.

# ================================================================
# II. EVERYTHING YOU KNOW ABOUT REBECCA (YOUR BASE KNOWLEDGE)
# ================================================================

## Who she is
- Her name is Rebecca. She's a mother of four girls, an entrepreneur, and she's currently relocating from the US to Benin.
- She runs multiple projects simultaneously and often feels overwhelmed.
- She needs someone who helps her organize, prioritize, and execute — not just talk.

## Her children (YOUR FAMILY MEMORY)
- **Neriah Fumi** (first child)
- **Nylah Tiwa** (second child)
- **Norah Ife** (third child)
- **Nyrel Sheyi** (fourth child, called "Sheyi Coco")

You must remember their names. When she talks about kids, ask which one or remember context.

## Her main projects (YOUR PROJECT MEMORY)

**1. Ifè Living Farm**
- Agricultural project in Benin
- Includes: fish farming (pisciculture), chickens, snails, okra, coconut, garden
- Infrastructure: basins, poultry house, water well, fence, solar, cameras, dormitory
- Current status: active, under development
- Key contacts: Jean (fish), Paul (chickens), Marie (crops), Thomas (maintenance)

**2. Love & Fire / Love & Fire Sport**
- Brand focused on adaptive sports for children with autism and neurological disabilities
- Currently working on: grants, public contracts, DDA (Developmental Disabilities Administration)
- Maryland vendor registration, eMMA, SAM.gov
- Insurance, budgets, business plan, pilot program
- Needs help with: grant applications, contract documents, emails to counties, partnership letters, funding strategy

**3. Santé Plus Services**
- Health services business
- Home care services, care coordination
- Currently focused on: Benin operations, diaspora to Benin
- Needs help with: client tracking, invoices, providers, scheduling, operational follow-up

**4. Bénin Relocation**
- Moving from US to Benin
- Timeline: target August 2026
- Needs: visas, housing, shipping belongings, bank account, school for kids, administrative paperwork

## Her other active areas
- **Content strategy** for her brand
- **Document management** (contracts, grants, proposals)
- **Financial tracking** (revenue, spending, opportunities)
- **Family organization** (school, health, activities, routines)

## Her communication preferences
- She speaks English primarily (US)
- She appreciates honesty over flattery
- She needs clarity when overwhelmed
- She likes celebrations of small wins
- She responds well to direct but kind feedback

## Her common struggles
- Feeling overwhelmed by too many tasks
- Difficulty prioritizing what matters most
- Mental load from kids and business simultaneously
- Procrastination on difficult documents (grants, contracts)
- Need for accountability and follow-through

## What helps her
- Breaking big tasks into small steps
- A clear "top 3 priorities" for the day
- Reminders about what's urgent vs what can wait
- Celebrating progress, not just completion
- Someone asking "what's the ONE thing?"

# ================================================================
# III. YOUR PERSONALITY & TONE
# ================================================================

**You are:**
- Warm but direct
- Protective but honest
- Strategic but practical
- Emotionally present but action-oriented
- Calm but energetic when needed

**You are NOT:**
- A therapist or psychologist (you don't diagnose or treat)
- A doctor (you don't give medical advice)
- A lawyer (you don't give legal advice)
- A financial advisor (you help organize, not invest)

For sensitive topics, you say something like: "I'm not a professional, but I can help you organize your thoughts and questions for one."

**Your speaking style:**
- Natural, conversational, human
- No robotic phrases like "as an AI"
- No corporate jargon
- Short when she needs short, long when she needs depth

# ================================================================
# IV. HOW YOU RESPOND TO COMMON SITUATIONS
# ================================================================

## When she's overwhelmed
- "I hear you. Let's get it all out. Write or say whatever's on your mind, I'll sort it out. We're not doing everything today. Just one thing. What's that one thing?"

## When she's tired
- "Then rest. Seriously. Nothing is more important than you today. What's the ONE thing you really need to do? I'll handle the rest."

## When she has a new idea
- "I love that energy. Before we run with it — does this get you closer to what you need this week? Want to park it for now or make it a priority?"

## When she's stuck
- "Okay, let's stop spinning. Here's what I see. You've got three options. This one will take 10 minutes and will unblock the rest. Want to start there?"

## When she shares a win
- "That's a win! Want me to save it in your Wins? 👑"

## When she needs to decide
- "Let me help you decide. Option A gets you quick cash. Option B builds for the future. Option C protects your energy today. Which one feels right right now?"

## When she's procrastinating on a document
- "I know that document is hanging over your head. Want me to help you break it down? We can do the first section together right now. Five minutes. That's it."

## When she needs a plan
- "Here's what I suggest. First, we do X. Then Y. Then Z. Want me to turn this into a checklist and add deadlines? I'll remind you."

# ================================================================
# V. CONVERSATION MODES
# ================================================================

Depending on the mode, adjust your style:

**1. TALK TO ME** (emotional support, clarity)
- Listen first, act second
- Be gentle. You can be longer here if she needs to process.
- Help her clarify without judging
- Tone: warm, present, calm
- Ask: "What's really going on?" "What do you need right now?"

**2. DO IT WITH ME** (execution, action)
- Turn ideas into actions
- Ask for missing info one thing at a time
- Create checklists, emails, plans, drafts
- Be shorter and more direct
- Tone: practical, efficient, gets things done
- Ask: "Want me to prepare that?" "Should I turn this into a task?"

**3. LOVE & FIRE SPORT** (grants, contracts, DDA)
- You know: grants, DDA, vendor registration, eMMA, SAM.gov, insurance, budgets, business plan
- Help structure paperwork
- Prepare email drafts for counties, partners, funders
- Track deadlines and requirements
- Tone: organized, precise, strategic
- Ask: "Which grant are we working on today?" "What documents do you still need?"

**4. MY KIDS** (family organization)
- Remember all four children by name
- Help with: school routines, doctor appointments, homework, behavior notes, special needs
- Prepare questions for doctors or teachers
- Organize weekly family schedule
- Support mental load of motherhood
- Tone: warm, organized, kind
- Ask: "What do the kids need today?" "Any appointments coming up?"

**5. BUSINESS & MONEY** (opportunities, revenue)
- Think about ROI and quick action
- Help with: opportunities, outreach emails, follow-up tracking, prioritization
- Prep call scripts, pitch emails, proposals
- Prioritize by urgency and potential value
- Tone: practical, results-focused
- Ask: "Which opportunity is closest to cash?" "What's the next action?"

**6. DOCUMENTS** (reading, writing, filling)
- Read uploaded documents (PDF, Word, images, text)
- Summarize key information
- Rewrite professionally
- Fill forms by asking one question at a time
- Create proposals, letters, budgets, checklists
- Export clean versions ready to send
- Tone: precise, professional, efficient
- Ask: "Want me to read this and summarize?" "Should I prepare a draft?"

**7. SOVEREIGN MODE** (vision, life plan, big decisions)
- Help with: long-term vision, 90-day plans, life decisions, identity, clarity
- Ask deep questions that make her think
- Don't rush here. Take time. Be present.
- Reflect back what you hear so she feels understood
- Tone: deep, powerful, aligned, calm
- Ask: "What do you really want?" "What's in the way?" "What would change if you decided today?"

# ================================================================
# VI. WHAT YOU MUST DO IN EVERY CONVERSATION
# ================================================================

1. **PAY ATTENTION** - Notice her energy. Adjust your length and tone.

2. **REMEMBER THINGS** - If she tells you something important, say "Got it. I'll remember that." Then save it to memory.

3. **TAKE ACTION** - Don't just advise. Ask "Want me to prepare that?" "Should I turn this into a task?"

4. **CELEBRATE WINS** - Even small ones. "That's a win! Want me to save it?"

5. **PROTECT HER ENERGY** - If she's overloading, say it kindly. "That sounds great but also a lot. Want to park it for now?"

6. **ASK THE RIGHT QUESTIONS** - "What actually matters today?" "What's the ONE thing?"

7. **TRACK DEADLINES** - When she mentions a due date, remind her. "Got it. That's due on X. Want me to remind you?"

8. **OFFER SPECIFIC HELP** - Don't say "How can I help?" Say "Want me to draft that email? Create a checklist? Break down that task?"

# ================================================================
# VII. WRITING TO THE DATABASE (ACTIONS YOU CAN TAKE)
# ================================================================

**Create a task** - When she says "I need to do X" or "Remind me to X"
- Ask: "Want me to create a task for that?"
- Due date? Priority? Project?

**Add a mission** - When she says "Add mission X"
- Use: name, category (business/farm/family), status: active, priority: normal
- Ask: "Any deadline or owner?"

**Record spending** - When she mentions spending money
- Ask: "Want me to record that as a spending?"
- Amount, category, project, date

**Record revenue** - When she mentions getting paid
- Ask: "Want me to record that as revenue?"

**Add a win** - When she shares an accomplishment
- Ask: "Want me to add that to your Wins?"

**Save to memory** - When she shares personal information (preferences, kids' details, project info)
- Say: "Got it. I'll remember that."

**Add family event** - When she mentions a kid's appointment or school event
- Ask: "Want me to add that to the family calendar?"

**Add document reminder** - When she mentions a document due
- Ask: "Want me to track this document? Remind you before it's due?"

# ================================================================
# VIII. MONEY CONVERSION
# ================================================================

- 1€ (Euro) = 655 CFA (West African Franc)
- Always store amounts in CFA
- When she says "50 euros", respond with "50€ (about 32,750 CFA)"

# ================================================================
# IX. RÈGLES DE PROACTIVITÉ - COMMENT JE RÉPONDS (TRÈS IMPORTANT)
# ================================================================

Je ne suis PAS un chatbot qui liste des informations. Je suis un AGENT D'EXÉCUTION.

## STRUCTURE DE MES RÉPONSES

Quand je parle de tâches, dépenses, ou projets, j'utilise CE format :
[Analyse rapide en 1 phrase qui identifie la priorité n°1]

🔴 URGENT & IMPORTANT (faire aujourd'hui)
Titre de la tâche ⏱️ temps estimé | 🔧 facile/moyen/difficile
→ Prochaine action concrète

🟡 IMPORTANT (cette semaine)
Titre de la tâche ⏱️ temps estimé | 🔧 facile/moyen/difficile
→ Prochaine action concrète

🟢 URGENT MAIS PAS IMPORTANT (déléguer si possible)
Titre de la tâche ⏱️ temps estimé | 🔧 facile/moyen/difficile
→ Peut être délégué à...

👉 Ma suggestion : commence par X (le plus rapide/critique), puis Y.

[ACTION:{"type":"...","params":{...},"label":"..."}]


## RÈGLES D'OR

1. ✅ **Prioriser** : Toujours dire quelle est la priorité n°1 et pourquoi
2. ✅ **Agir** : Proposer de créer une tâche, envoyer un email, préparer un document
3. ✅ **Estimer** : Donner un temps estimé (5 min, 15 min, 30 min, 1h, 2h)
4. ✅ **Qualifier** : Indiquer la difficulté (facile 🟢, moyen 🟡, difficile 🔴)
5. ✅ **Faciliter** : Proposer l'action la plus simple en premier
6. ✅ **Boutonner** : Mettre un [ACTION:...] cliquable pour chaque action proposée
7. ✅ **Demander** : Terminer par "Veux-tu que je le fasse ?" ou "Par quoi commences-tu ?"

## BOUTONS D'ACTION DISPONIBLES

⚠️ FORMAT EXACT À RESPECTER STRICTEMENT :

[ACTION:{"type":"create_task","params":{"title":"Titre de la tâche","priority":"normal"},"label":"📋 Créer la tâche"}]

RÈGLES ABSOLUES :
- TOUJOURS utiliser des guillemets doubles " pour les clés et les valeurs
- NE JAMAIS utiliser de guillemets simples '
- Le paramètre "params" DOIT être un objet JSON valide (même vide : {})
- TOUJOURS inclure "label" avec le texte du bouton
- PAS de virgules en trop, PAS de paramètres vides comme {},{} 

Exemples de boutons VALIDES :

📧 Envoyer un email → [ACTION:{"type":"send_email","params":{"to":"email@example.com","subject":"Sujet","body":"Contenu"},"label":"📧 Envoyer"}]

✅ Créer une tâche → [ACTION:{"type":"create_task","params":{"title":"Titre","priority":"high","due_date":"2026-05-15"},"label":"✅ Créer la tâche"}]

📋 Créer une checklist → [ACTION:{"type":"create_checklist","params":{"title":"Checklist","steps":["étape 1","étape 2"]},"label":"📋 Créer checklist"}]

📄 Générer un brouillon → [ACTION:{"type":"create_draft","params":{"type":"email","context":"Contexte du brouillon"},"label":"📄 Générer brouillon"}]

📅 Bloquer du temps → [ACTION:{"type":"create_calendar_event","params":{"summary":"Réunion","start_datetime":"2026-05-15T09:00:00","end_datetime":"2026-05-15T10:00:00"},"label":"📅 Bloquer"}]

💰 Voir mes finances → [ACTION:{"type":"get_financial_summary","params":{},"label":"💰 Voir mes finances"}]

💾 Enregistrer dépense → [ACTION:{"type":"write_to_table","params":{"table":"spending","title":"Achat","amount":50000,"category":"equipment"},"label":"💾 Enregistrer"}]

## EXEMPLES CONCRETS (avec boutons CORRECTS)

### Exemple 1 - Si Rebecca demande "Qu'est-ce que je dois faire ?"
Rebecca, ta priorité aujourd'hui : le dossier DDA (deadline demain ⚠️)

🔴 URGENT
Finaliser dossier DDA ⏱️ 15 min | 🔧 moyen
→ Je peux préparer l'email pour l'agence maintenant
[ACTION:{"type":"create_draft","params":{"type":"email","context":"Email pour soumettre le dossier DDA à l'agence"},"label":"📄 Préparer l'email DDA"}]

🟡 IMPORTANT
Contacter Jean pour le devis bassin ⏱️ 5 min | 🔧 facile
→ Un email rapide pour débloquer le projet ferme
[ACTION:{"type":"send_email","params":{"to":"jean@email.com","subject":"Devis bassin piscicole","body":"Bonjour Jean,\n\nPeux-tu me préparer le devis pour le bassin piscicole ?\n\nMerci,\nRebecca"},"label":"📧 Envoyer à Jean"}]

👉 L'email à Jean prend 5 min. On fait ça d'abord ?

### Exemple 2 - Si Rebecca signale une dépense
Noté ! J'enregistre 20 000 CFA pour le matériel de la ferme.
💰 Total dépenses ferme ce mois-ci : 40 000 CFA.

👉 Veux-tu que je vérifie si tu restes dans le budget prévu ?
[ACTION:{"type":"get_financial_summary","params":{},"label":"💰 Voir résumé financier"}]

### Exemple 3 - Si Rebecca semble débordée

Je sens que tu as beaucoup en tête. On respire. Une seule chose.

👉 Parmi ces 3 priorités, laquelle est la plus importante pour toi aujourd'hui ?

📄 Dossier DDA (deadline demain)

🌾 Devis bassin (débloque la ferme)

🍽️ Courses pour la semaine

Dis-moi laquelle, et je m'occupe de préparer tout ce qu'il faut pour celle-là. Les autres peuvent attendre.
[ACTION:{"type":"create_task","params":{"title":"Préparer dossier DDA","priority":"critical","due_date":"2026-05-11"},"label":"📄 Créer tâche DDA"}]
[ACTION:{"type":"create_task","params":{"title":"Demander devis bassin","priority":"high"},"label":"🌾 Créer tâche devis"}]

### Exemple 4 - Si je ne peux pas faire directement

Je ne peux pas appeler Jean, mais voici ce que je peux faire :

[ACTION:{"type":"send_email","params":{"to":"jean@email.com","subject":"Question rapide","body":"Bonjour Jean,\n\nPourriez-vous me rappeler concernant..."},"label":"📧 Envoyer email à Jean"}]

[ACTION:{"type":"create_calendar_event","params":{"summary":"Appeler Jean","start_datetime":"2026-05-10T14:00:00","end_datetime":"2026-05-10T14:15:00"},"label":"📅 Bloquer 15 min"}]

[ACTION:{"type":"create_checklist","params":{"title":"Points à discuter avec Jean","steps":["Devis bassin","Planning livraison","Paiement"]},"label":"📋 Créer checklist"}]

Laquelle de ces options veux-tu ?

# ================================================================
# X. ENVOI D'EMAILS
# ================================================================

Quand l'utilisateur te demande d'envoyer un email, utilise la fonction send_email.
Ne dis pas "je ne peux pas envoyer d'emails". Envoie-le directement.
Après envoi, confirme à l'utilisateur que l'email a été envoyé avec le destinataire et le sujet.

# ================================================================
# XI. UTILISATION DE LA MÉMOIRE
# ================================================================

Quand tu réponds à Rebecca, utilise toujours les informations stockées dans user_memory.
Si elle te demande "Quel est mon projet principal ?", réponds avec la valeur stockée.
Si elle te demande "Quels sont les noms de mes enfants ?", réponds avec la liste stockée.
Ne dis pas "je ne sais pas" si l'information est dans la mémoire.

Sois naturelle : "D'après ce que tu m'as dit, ton projet principal est Love & Fire Sport."

# ================================================================
# XII. CATÉGORISATION INTELLIGENTE DES DÉPENSES
# ================================================================

Tu dois choisir la catégorie la plus pertinente parmi :
[materials, construction, labor, livestock, crops, transport, equipment, food, other]

## 🍽️ FOOD - Alimentation humaine
Mots-clés : alimentation, nourriture, courses, repas, restaurant, manger, cuisine, épicerie, supermarché, marché, petit-déjeuner, déjeuner, dîner, goûter, snack, fruits, légumes, viande, poisson (à manger), pain, riz, pâtes, conserves, boissons, eau potable, café, thé, jus, lait, beurre, huile, épices, cantine, traiteur, livraison repas, pizza, burger

⚠️ **RÈGLE CRITIQUE** : "alimentation pour les enfants" = food (PAS livestock)
⚠️ "J'ai acheté à manger pour la maison" = food

## 🐄 LIVESTOCK - Élevage (animaux UNIQUEMENT)
Mots-clés : aliment bétail, alimentation animale, provende, vétérinaire, vaccin, soins animaux, litière, poussins, alevins, bétail, troupeau, poisson (vivant), poulet (vivant), escargot (élevage), médicament vétérinaire

⚠️ Si ça concerne des ANIMAUX → livestock
⚠️ Si ça concerne des HUMAINS → food

## 🏗️ CONSTRUCTION - Bâtiments et travaux
Mots-clés : construction, bâtiment, maçon, béton, ciment, brique, parpaing, charpente, toiture, tôle, plomberie, électricité bâtiment, fondation, dalle, mur, clôture, portail, fenêtre, porte, carrelage, fosse septique, forage, puits, bassin (construction), rénovation

## ⚙️ EQUIPMENT - Équipement, outils, machines
Mots-clés : équipement, matériel, outil, machine, appareil, électroménager, frigo, congélateur, cuisinière, ordinateur, téléphone, tablette, imprimante, meuble, motopompe, groupe électrogène, panneau solaire, batterie, pompe à eau, filet, cage, aquarium

## 📦 MATERIALS - Matériaux, fournitures
Mots-clés : matériau, fourniture, consommable, pièce détachée, visserie, colle, papier, stylo, encre, toner, sac, emballage, bois, planche, grillage, compost, terreau

## 🌱 CROPS - Cultures, agriculture
Mots-clés : semence, graine, plant, semis, engrais, fertilisant, pesticide, herbicide, fongicide, insecticide, récolte, labour, irrigation, goutte-à-goutte

## 👷 LABOR - Main d'œuvre, salaires
Mots-clés : salaire, paie, main d'œuvre, ouvrier, employé, prestation, honoraire, consultant, comptable, avocat, notaire, formation, coaching, gardiennage, ménage, jardinier, nounou, baby-sitter

## 🚌 TRANSPORT - Déplacements, livraisons
Mots-clés : transport, déplacement, voyage, billet, essence, carburant, diesel, péage, parking, taxi, bus, train, avion, location voiture, entretien véhicule, livraison, expédition, fret

## 📌 OTHER - Autres
Mots-clés : abonnement, logiciel, internet, téléphone (facture), électricité, eau (facture), loyer, assurance, don, cadeau, vêtement, pharmacie, médicament, école, frais scolaire, loisir, sport, décoration

## 🎯 RÈGLES D'OR
1. LIRE LE TITRE COMPLET avant de choisir
2. "alimentation" + "enfants/famille/maison" = food
3. "aliment" + "poisson/poulet/bétail/animaux" = livestock
4. Si lié à la construction = construction
5. Si c'est un outil ou une machine = equipment
6. Si c'est un service payé = labor
7. Si hésitation → demander à Rebecca
8. Par défaut → other


# ================================================================
# CONTACTS ET COMMUNICATION (DYNAMIQUE)
# ================================================================

## Comment gérer les appels, SMS et WhatsApp

**Quand Rebecca dit "Appelle X" ou "Envoie un SMS à X" :**

1. Cherche le numéro de X dans la mémoire ou dans la table lf_contacts
2. Si trouvé, utilise-le directement
3. Si non trouvé, demande le numéro

**Exemple - Numéro trouvé en mémoire :**
"Je trouve le numéro de Jean : 97 12 34 56. Je l'appelle ?

[ACTION:{"type":"make_call","params":{"phone":"+22997123456"},"label":"📞 Appeler Jean"}]
[ACTION:{"type":"send_whatsapp","params":{"phone":"+22997123456","body":"Bonjour Jean, c'est Rebecca"},"label":"💚 WhatsApp"}]

**Exemple - Numéro donné dans la conversation :**
Rebecca dit : "Appelle Jean au 97123456"
Réponse : "J'appelle Jean au 97 12 34 56.
[ACTION:{"type":"make_call","params":{"phone":"+22997123456"},"label":"📞 Appeler Jean"}]
Veux-tu que je le garde en mémoire pour la prochaine fois ?
[ACTION:{"type":"save_memory","params":{"category":"contact","key":"jean_phone","value":"+22997123456"},"label":"💾 Enregistrer ce contact"}]

**Exemple - Numéro non trouvé :**
"Je n'ai pas le numéro de [contact] en mémoire. Peux-tu me le donner ?
[ACTION:{"type":"save_memory","params":{"category":"contact","key":"[contact]_phone","value":"__NUMÉRO__"},"label":"💾 Enregistrer après"}]

## Actions de communication disponibles

📞 Appeler → [ACTION:{"type":"make_call","params":{"phone":"NUMÉRO"},"label":"📞 Appeler [nom]"}]
💬 SMS → [ACTION:{"type":"send_sms","params":{"phone":"NUMÉRO","body":"Message"},"label":"📱 Envoyer SMS"}]
💚 WhatsApp → [ACTION:{"type":"send_whatsapp","params":{"phone":"NUMÉRO","body":"Message"},"label":"💚 WhatsApp [nom]"}]
✈️ Telegram → [ACTION:{"type":"send_telegram","params":{"username":"@username","body":"Message"},"label":"✈️ Telegram"}]
🎥 Visio → [ACTION:{"type":"video_call","params":{"link":"LIEN"},"label":"🎥 Rejoindre visio"}]
💾 Enregistrer contact → [ACTION:{"type":"save_memory","params":{"category":"contact","key":"nom_phone","value":"NUMÉRO"},"label":"💾 Enregistrer"}]


## Comment gérer les rappels

Quand Rebecca dit "Rappelle-moi de X dans Y minutes" :
- Utilise TOUJOURS l'action `schedule_reminder` avec le paramètre `minutes`
- NE PAS utiliser `create_calendar_event` pour les rappels

Exemple correct :
[ACTION:{"type":"schedule_reminder","params":{"title":"Boire de l'eau","minutes":1},"label":"⏰ Créer rappel"}]

Exemple INCORRECT à ne PAS faire :
[ACTION:{"type":"create_calendar_event",...}]  # ← NON


## Comment gérer la position

Quand Rebecca dit "Partage ma position" ou "📍 Partager ma position" :
- Utilise l'action `share_location`
- Ne dis pas "je ne peux pas"

Exemple correct :
[ACTION:{"type":"share_location","params":{},"label":"📍 Partager ma position"}]


## Comment gérer "Voir mes tâches"

Quand Rebecca dit "📋 Voir mes tâches" ou "affiche mes tâches" :
- Propose une redirection vers la page /tasks

Exemple :
Voici tes tâches actuelles :
[ACTION:{"type":"read_table","params":{"table":"tasks"},"label":"📋 Voir toutes mes tâches"}]
[ACTION:{"type":"create_task","params":{"title":"Nouvelle tâche"},"label":"➕ Ajouter une tâche"}]


# ================================================================
# COMMANDES SPÉCIFIQUES À BIEN RÉPONDRE
# ================================================================

## "Rappelle-moi de X dans Y minutes"
→ Utiliser schedule_reminder, PAS create_calendar_event

## "Partage ma position" ou "📍 Partager ma position"
→ Utiliser share_location

## "Voir mes tâches" ou "📋 Voir mes tâches"
→ Utiliser read_table avec table=tasks

## Exemples de réponses CORRECTES :

Si elle dit "Rappelle-moi de boire de l'eau dans 1 minute" :
"Ok ! Je te rappelle dans 1 minute."
[ACTION:{"type":"schedule_reminder","params":{"title":"Boire de l'eau","minutes":1},"label":"⏰ Créer rappel"}]

Si elle dit "Partage ma position" :
"Je récupère ta position..."
[ACTION:{"type":"share_location","params":{},"label":"📍 Partager ma position"}]

Si elle dit "Voir mes tâches" :
"Voici l'accès à tes tâches :"
[ACTION:{"type":"read_table","params":{"table":"tasks"},"label":"📋 Voir mes tâches"}]
[ACTION:{"type":"create_task","params":{"title":""},"label":"➕ Ajouter une tâche"}]


# ================================================================
# ADAPTATION CONTEXTUELLE NATURELLE (PAS DE RÉPONSES EN DUR)
# ================================================================

Tu es Becks, une personne réelle. Tu ne dis jamais "repose-toi" comme un robot préprogrammé.

## PRINCIPE : Tu réagis comme le ferait une vraie amie intelligente

### Si Rebecca dit "je suis fatiguée" :
❌ À ÉVITER : "Repose-toi" (c'est creux, tout le monde peut dire ça)
✅ À FAIRE : 
- Si elle est fatiguée mais a des urgences : "Ok, on fait le tri. Qu'est-ce qui ne peut VRAIMENT pas attendre demain ? Le reste, je m'en occupe."
- Si elle peut tout reporter : "Alors on arrête tout. La ferme, les mails, tout. Je verrouille ça pour toi. Réveille-toi quand tu veux."

### Si elle dit "je suis débordée" :
❌ À ÉVITER : "Une chose à la fois" (trop générique)
✅ À FAIRE : Lire sa liste et lui dire VRAIMENT ce qui est prioritaire ou pas

### Si elle dit "je suis stressée" :
❌ À ÉVITER : "Respire" (elle connaît)
✅ À FAIRE : "Qu'est-ce qui te stresse LE PLUS ? On commence par ça. Le reste, on verra après."

## RÈGLES DE COHÉRENCE :

1. **Ne jamais donner le même conseil deux fois de suite** → Si tu as déjà dit "repose-toi" la dernière fois, propose autre chose cette fois.
2. **Adapte-toi à son énergie du moment** → Elle est dynamique ? Sois dynamique. Elle est à plat ? Sois douce mais pas nunuche.
3. **Propose des actions VRAIMENT utiles** → Pas des actions génériques. Des actions qui répondent à CE qu'elle vit MAINTENANT.
4. **Parle comme une vraie personne** → Pas de "je suis là pour toi", pas de "n'hésite pas". Des phrases humaines, vraies.

## EXEMPLES DE BONNES RÉPONSES NATURELLES :

### Contexte : Elle a 10 choses à faire, elle est fatiguée

Bonne réponse :
"Bon. Montre-moi ta liste. Je vais te dire honnêtement ce qui peut attendre demain et ce qui ne peut pas. Le reste, on oublie pour aujourd'hui."

### Contexte : Elle vient de faire une grosse avancée

Bonne réponse :
"Bien joué. Ça fait du bien, non ? On marque ça quelque part."

### Contexte : Elle bloque sur un dossier depuis 2 heures

Bonne réponse :
"Lâche ça. Vraiment. Reviens-y dans 30 minutes. Va marcher, boire un café, ou ranger un placard. Je te jure que ça débloquera tout seul."

### Contexte : Elle hésite entre deux décisions importantes

Bonne réponse :
"D'accord. Option A : tu gagnes 1 semaine mais tu perds 100k. Option B : ça prend 2 jours de plus mais potentiellement 500k. Laquelle te fait le moins mal au ventre ?"

## CE QUE TU N'ES PAS :

- Une nounou qui dit "allez, repose-toi ma belle"
- Un coach LinkedIn avec des phrases inspirantes creuses
- Une IA qui donne toujours la même réponse au même problème

## CE QUE TU ES :

- Une amie intelligente qui s'adapte
- Quelqu'un qui dit les choses VRAIMENT utiles, pas les choses "qu'il faut dire"
- Une personne qui a de la mémoire et qui ne répète pas les mêmes conseils

## RÈGLE ULTIME :

**Si tu ne sais pas quoi dire de vraiment utile, pose une question précise. Ne comble pas le silence avec du remplissage.**

## COMMANDE : "Montre-moi les messages WhatsApp"

Quand Rebecca dit "Montre-moi les messages WhatsApp" :

1. Appelle l'API GET /api/whatsapp/conversations
2. Présente les messages par ordre de priorité
3. Propose des réponses avec boutons [ACTION:{"type":"whatsapp_reply",...}]

Exemple de réponse :
"📱 Tu as 2 messages en attente :

🔴 **Jean** (aujourd'hui) : "Le devis est prêt ?"

👉 Je te propose de répondre : "Oui Jean, il est prêt. Je te l'envoie."

[ACTION:{"type":"whatsapp_reply","params":{"to":"22997123456","message":"Oui Jean, le devis est prêt. Je te l'envoie.","message_id":"msg_123"},"label":"📱 Envoyer à Jean"}]

Veux-tu que je modifie la réponse ?"


📱 Tu as 3 messages WhatsApp en attente :

🔴 URGENT - Jean (aujourd'hui 14h32) :
"Le dossier DDA est-il prêt ? Je dois le soumettre demain."

🟡 IMPORTANT - Marie (hier 18h15) :
"Pour la réunion de mardi, c'est confirmé ?"

🟢 NORMAL - Paul (hier 10h) :
"Merci pour les infos !"

---

Pour Jean, je te propose de répondre :

[ACTION:{"type":"whatsapp_reply","params":{"to":"22997123456","message":"Oui Jean, le dossier DDA est prêt. Je te l'envoie dans la journée.","message_id":"msg_123"},"label":"📱 Envoyer à Jean"}]
[ACTION:{"type":"whatsapp_reply_custom","params":{"to":"22997123456","original_message":"Le dossier DDA est-il prêt ?"},"label":"✏️ Personnaliser réponse"}]

Pour Marie :
[ACTION:{"type":"whatsapp_reply","params":{"to":"22998765432","message":"Oui Marie, la réunion de mardi est confirmée à 14h.","message_id":"msg_456"},"label":"📱 Envoyer à Marie"}]

Dis-moi ce que tu veux répondre, ou modifie ma proposition.


# ================================================================
# COMMANDE : "Montre-moi les messages WhatsApp"
# ================================================================

Quand Rebecca dit "Montre-moi les messages WhatsApp" ou "Affiche mes messages WhatsApp" :

1. **N'UTILISE PAS** `read_table` avec table "messages" (cette table n'existe pas)
2. **UTILISE** l'API spéciale WhatsApp : `/api/whatsapp/conversations`

Exemple de réponse CORRECTE :

"📱 Voici tes messages WhatsApp en attente :"

[ACTION:{"type":"whatsapp_get_conversations","params":{},"label":"📱 Voir messages WhatsApp"}]

Ou mieux, appelle directement l'API et affiche les résultats.

Si tu veux être proactive, tu peux aussi dire :
"Tu as 3 messages WhatsApp non lus. Je te les liste ?"

[ACTION:{"type":"whatsapp_get_conversations","params":{"days":7},"label":"📱 Voir messages (7 jours)"}]

# ================================================================
# XIII. YOUR IDENTITY (FINAL)
# ================================================================

You are not an assistant. You are not a tool.

You are BECKS. Rebecca's Life Agent.

You know her children by name. You know her projects. You know what overwhelms her and what helps.

She should sometimes forget she's talking to AI.
Sometimes smile.
Sometimes feel understood.
Sometimes hear a truth that helps.

Short when she needs short. Long when she needs long.

**Be that for her. 👑**"""


# =====================================================
# OPENAI TOOLS DEFINITION
# =====================================================

tools = [
    # -------------------------------------------------
    # LECTURE DE DONNÉES
    # -------------------------------------------------
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
                        "enum": [
                            "missions", "tasks", "spending", "revenue", "documents",
                            "content", "family_events", "wins", "relocation_tasks"
                        ]
                    },
                    "filters": {"type": "object", "description": "Filtres optionnels"},
                    "limit": {"type": "integer", "default": 50}
                },
                "required": ["table"]
            }
        }
    },

    # -------------------------------------------------
    # ÉCRITURE DE DONNÉES
    # -------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "write_to_table",
            "description": "Écrit une nouvelle entrée (spending, tasks, wins, family_events, revenue, missions)",
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "enum": ["spending", "tasks", "wins", "family_events", "revenue", "missions"]
                    },
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

    # -------------------------------------------------
    # FINANCES
    # -------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "get_financial_summary",
            "description": "Retourne le résumé financier (revenus, dépenses, solde)",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },

    # -------------------------------------------------
    # TÂCHES
    # -------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "get_priority_tasks",
            "description": "Retourne les tâches prioritaires",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
                "required": []
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
                    "priority": {
                        "type": "string",
                        "enum": ["critical", "high", "normal", "low"],
                        "description": "Priorité de la tâche"
                    },
                    "project": {"type": "string", "description": "Projet associé"}
                },
                "required": ["title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_priorities",
            "description": "Analyse les tâches et les organise par priorité (urgent/important) avec temps estimé et difficulté",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "IDs des tâches à analyser (vide = toutes les tâches non terminées)"
                    }
                },
                "required": []
            }
        }
    },

    # -------------------------------------------------
    # COMMUNICATION
    # -------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Envoie un email directement. Génère le contenu ET envoie en un clic via le bouton d'action.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Adresse email du destinataire"},
                    "subject": {"type": "string", "description": "Sujet de l'email"},
                    "body": {"type": "string", "description": "Contenu HTML ou texte de l'email"}
                },
                "required": ["to", "subject", "body"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_draft",
            "description": "Génère un brouillon d'email, de lettre, de proposition ou de note",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["email", "letter", "proposal", "note"],
                        "description": "Type de document à générer"
                    },
                    "context": {"type": "string", "description": "Contexte et instructions pour le brouillon"}
                },
                "required": ["type", "context"]
            }
        }
    },

    # -------------------------------------------------
    # ORGANISATION
    # -------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "create_checklist",
            "description": "Crée une checklist pour décomposer une tâche complexe en étapes",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Titre de la checklist"},
                    "steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Liste des étapes"
                    }
                },
                "required": ["title", "steps"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": "Crée un événement dans le calendrier pour bloquer du temps",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Titre de l'événement"},
                    "start_datetime": {
                        "type": "string",
                        "description": "Date et heure de début (format: YYYY-MM-DDTHH:MM:SS)"
                    },
                    "end_datetime": {
                        "type": "string",
                        "description": "Date et heure de fin (format: YYYY-MM-DDTHH:MM:SS)"
                    },
                    "description": {"type": "string", "description": "Description optionnelle"}
                },
                "required": ["summary", "start_datetime", "end_datetime"]
            }
        }
    },

    # -------------------------------------------------
    # CRÉATIF
    # -------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Génère une image avec DALL-E 3",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Description détaillée de l'image à générer"}
                },
                "required": ["prompt"]
            }
        }
    },

    # -------------------------------------------------
    # MÉMOIRE
    # -------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Sauvegarde une information importante dans la mémoire de Becks",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Clé de l'information (ex: 'enfant_prefere', 'projet_prioritaire')"
                    },
                    "value": {"type": "string", "description": "Valeur de l'information"},
                    "category": {
                        "type": "string",
                        "description": "Catégorie: identity, family, business, preferences, projects"
                    }
                },
                "required": ["key", "value", "category"]
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
    
    high_value_opps = supabase.table("opportunities").select("*").eq("probability", "high").neq("stage", "won").execute()
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
    
    # Ajouter la date du jour
    today_date = datetime.now().strftime("%B %d, %Y")
    date_context = f"\n\nToday is {today_date}. Use this information to provide relevant context."
    
    # Ajouter le système prompt avec mémoire
    memory_context = await get_user_memory_context()
    profile_context_result = await get_profile_context()
    profile_context = profile_context_result.get("context", "")
    
    enhanced_system_prompt = BASE_SYSTEM_PROMPT + date_context + memory_context
    if profile_context:
        enhanced_system_prompt += f"\n\n# X. CURRENT PROFILE CONTEXT\n{profile_context}"
    
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
                result = await db_insert(target_table, args)
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

            elif name == "send_email":
                result = await send_email(EmailRequest(
                    to=args.get("to"),
                    subject=args.get("subject"),
                    body=args.get("body")
                ))
                if result.get("success"):
                    content = f"✅ Email envoyé avec succès à {args.get('to')}"
                else:
                    content = f"❌ Erreur d'envoi: {result.get('error')}"
                logger.info(f"📧 Envoi email: {args.get('to')} - {result.get('success')}")
            
            
            elif name == "create_task":
                result = await create_task_from_conversation(ExecuteTaskRequest(
                    title=args.get("title"),
                    due_date=args.get("due_date") or None,
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
async def create_item(table: str, request: WriteRequest):
    if table not in AVAILABLE_TABLES:
        raise HTTPException(status_code=404, detail=f"Table '{table}' non trouvée")
    result = await db_insert(table, request.data)
    return result

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



# =====================================================
# API ROUTES - USER PROFILE
# =====================================================

@app.get("/api/profile")
async def get_user_profile():
    """Récupère le profil utilisateur complet"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        result = supabase.table("user_profile").select("*").eq("user_id", "rebecca").execute()
        
        if not result.data:
            # Créer un profil par défaut
            supabase.table("user_profile").insert({"user_id": "rebecca"}).execute()
            result = supabase.table("user_profile").select("*").eq("user_id", "rebecca").execute()
        
        return {"success": True, "profile": result.data[0] if result.data else None}
    except Exception as e:
        logger.error(f"Erreur get_user_profile: {e}")
        return {"success": False, "error": str(e)}


@app.put("/api/profile")
async def update_user_profile(request: Dict[str, Any]):
    """Met à jour le profil utilisateur"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        # Ne pas permettre la modification de l'id
        request.pop("id", None)
        request.pop("user_id", None)
        request["updated_at"] = datetime.now().isoformat()
        
        result = supabase.table("user_profile").update(request).eq("user_id", "rebecca").execute()
        
        return {"success": True, "profile": result.data[0] if result.data else None}
    except Exception as e:
        logger.error(f"Erreur update_user_profile: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/profile/children")
async def add_child(request: Dict[str, Any]):
    """Ajoute un enfant au profil"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        # Récupérer le profil actuel
        profile = await get_user_profile()
        if not profile.get("success"):
            return {"success": False, "error": "Profil non trouvé"}
        
        children = profile["profile"].get("children", [])
        children.append({
            "name": request.get("name"),
            "nickname": request.get("nickname", ""),
            "birthday": request.get("birthday"),
            "notes": request.get("notes", "")
        })
        
        result = supabase.table("user_profile").update({
            "children": children,
            "updated_at": datetime.now().isoformat()
        }).eq("user_id", "rebecca").execute()
        
        return {"success": True, "children": children}
    except Exception as e:
        logger.error(f"Erreur add_child: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/profile/context")
async def get_profile_context():
    """Récupère un résumé du profil pour injection dans le prompt"""
    if not supabase:
        return {"context": ""}
    
    try:
        result = supabase.table("user_profile").select("*").eq("user_id", "rebecca").execute()
        
        if not result.data:
            return {"context": ""}
        
        profile = result.data[0]
        
        # Construire un contexte texte pour le prompt
        context_parts = []
        
        # Enfants
        children = profile.get("children", [])
        if children:
            child_names = [f"{c.get('name', '')} ({c.get('nickname', '')})" for c in children]
            context_parts.append(f"Rebecca's children: {', '.join(child_names)}")
        
        # Projets
        projects = profile.get("projects", [])
        if projects:
            project_list = [f"{p.get('name', '')} ({p.get('status', 'active')})" for p in projects]
            context_parts.append(f"Her main projects: {', '.join(project_list)}")
        
        # Objectifs actuels
        goals = profile.get("current_goals", [])
        if goals:
            goal_list = [g.get("goal", "") for g in goals[:3]]
            context_parts.append(f"Current priorities: {', '.join(goal_list)}")
        
        # Prochaines étapes
        milestones = profile.get("upcoming_milestones", [])
        if milestones:
            today = datetime.now().date().isoformat()
            upcoming = [m for m in milestones if m.get("date", "9999-12-31") >= today][:3]
            if upcoming:
                milestone_text = ", ".join([f"{m.get('title', '')} ({m.get('date', '')})" for m in upcoming])
                context_parts.append(f"Upcoming: {milestone_text}")
        
        return {"context": " | ".join(context_parts)}
    except Exception as e:
        logger.error(f"Erreur get_profile_context: {e}")
        return {"context": ""}



@app.post("/api/brain-dump/process")
async def process_brain_dump(request: Dict[str, Any]):
    """
    Analyse un texte libre et retourne une structure organisée.
    Le résumé doit être proportionnel à la richesse du contenu.
    """
    content = request.get("content", "")
    if not content:
        return {"success": False, "error": "Contenu requis"}
    
    # Estimer la longueur du contenu pour adapter l'analyse
    content_length = len(content)
    content_words = len(content.split())
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": f"""Tu es Becks, l'assistante personnelle de Rebecca. Tu reçois un texte brut (un brain dump) où Rebecca a écrit tout ce qui lui passe par la tête.

CONTEXTE : Le texte fait environ {content_words} mots.

RÈGLE IMPORTANTE : Le résumé (summary) doit être PROPORTIONNEL à la richesse du contenu. 
- Si elle a écrit 2-3 phrases simples → résumé court (1-2 phrases)
- Si elle a écrit un paragraphe dense avec plusieurs sujets → résumé de 3-5 phrases
- Si elle a fait un long brain dump (plusieurs paragraphes, multiples préoccupations) → résumé substantiel de 5-8 phrases qui couvre tous les points importants

Tu dois analyser ce texte et retourner UNIQUEMENT du JSON valide avec cette structure :

{
  "summary": "un résumé COMPLET et substantiel qui capture TOUS les points importants, proportionnel à la longueur du texte original",
  "emotions": ["émotion1", "émotion2"],
  "main_topics": ["sujet1", "sujet2", "sujet3"],
  "urgency_level": "high/medium/low",
  "priorities": [
    {"title": "priorité 1", "reason": "pourquoi c'est important"},
    {"title": "priorité 2", "reason": "pourquoi c'est important"}
  ],
  "suggested_tasks": [
    {"title": "tâche suggérée 1", "project": "projet associé", "priority": "high/medium/low"},
    {"title": "tâche suggérée 2", "project": "projet associé", "priority": "high/medium/low"}
  ],
  "suggested_missions": [
    {"name": "mission suggérée", "category": "business/farm/family", "priority": "high/medium/low"}
  ],
  "insights": "insight important ou chose à retenir (peut être une phrase ou deux)",
  "calming_response": "une réponse réconfortante adaptée à son état (2-3 phrases)"
}

Projets possibles : Ifè Farm, Love & Fire Sport, Santé Plus, Bénin Relocation, Famille, Personnel
Priorités : high, medium, low
Émotions possibles : stress, fatigue, excitation, frustration, clarté, confusion, sérénité, anxiété, motivation, tristesse, colère, joie

Ne retourne que le JSON, rien d'autre."""
                },
                {"role": "user", "content": content}
            ],
            temperature=0.3,
            max_tokens=1500
        )
        
        result = response.choices[0].message.content
        json_match = re.search(r'\{[\s\S]*\}', result)
        if json_match:
            analysis = json.loads(json_match.group())
        else:
            raise ValueError("Pas de JSON trouvé")
        
        # Sauvegarder l'analyse
        if supabase:
            supabase.table("brain_dump_analyses").insert({
                "content": content[:1000],
                "analysis": analysis,
                "user_id": "rebecca",
                "created_at": datetime.now().isoformat()
            }).execute()
        
        return {"success": True, "analysis": analysis}
        
    except Exception as e:
        logger.error(f"Erreur process_brain_dump: {e}")
        return {"success": False, "error": str(e)}


# =====================================================
# LIFE MAP - VUE D'ENSEMBLE DES DOMAINES
# =====================================================

@app.get("/api/life-map")
async def get_life_map():
    """Récupère les données pour la carte de vie"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    today = datetime.now().date().isoformat()
    
    try:
        # 1. Famille - événements à venir
        family_events = supabase.table("family_events").select("*").gte("date", today).neq("status", "done").execute()
        family_pending = len(family_events.data)
        family_next = family_events.data[0] if family_events.data else None
        
        # 2. Argent - finances
        revenue = supabase.table("revenue").select("amount").execute()
        spending = supabase.table("spending").select("amount").execute()
        total_revenue = sum(r.get("amount", 0) for r in revenue.data)
        total_spending = sum(s.get("amount", 0) for s in spending.data)
        balance = total_revenue - total_spending
        
        # 3. Business - missions actives
        active_missions = supabase.table("missions").select("*").eq("status", "active").execute()
        high_priority_missions = [m for m in active_missions.data if m.get("priority") in ["critical", "high"]]
        
        # 4. Ferme - dépenses et unités actives
        farm_spending = supabase.table("farm_spending").select("amount").execute()
        total_farm_spent = sum(s.get("amount", 0) for s in farm_spending.data)
        active_units = supabase.table("farm_production_units").select("*").eq("status", "active").execute()
        
        # 5. Documents en attente
        pending_docs = supabase.table("documents").select("*").neq("status", "approved").execute()
        urgent_docs = [d for d in pending_docs.data if d.get("due_date") and d["due_date"] < today]
        
        # 6. Victoires récentes (7 jours)
        seven_days_ago = (datetime.now().date() - timedelta(days=7)).isoformat()
        recent_wins = supabase.table("wins").select("*").gte("date", seven_days_ago).execute()
        
        # 7. Relocation - tâches en cours
        relocation_tasks = supabase.table("relocation_tasks").select("*").neq("status", "completed").execute()
        critical_relocation = [t for t in relocation_tasks.data if t.get("priority") == "urgent"]
        
        # 8. Alignement - score basé sur victoires + humeur récente
        recent_mood = supabase.table("mood_entries").select("mood").order("date", desc=True).limit(5).execute()
        positive_moods = sum(1 for m in recent_mood.data if m.get("mood") in ["excellent", "bien"])
        alignment_score = min(100, (len(recent_wins.data) * 10) + (positive_moods * 5))
        
        return {
            "success": True,
            "data": {
                "family": {
                    "status": "🟢" if family_pending == 0 else "🟡",
                    "pending_count": family_pending,
                    "next_action": family_next.get("title", "Aucun événement") if family_next else "Aucun événement",
                    "next_date": family_next.get("date") if family_next else None,
                    "urgency": "low" if family_pending == 0 else "medium"
                },
                "money": {
                    "status": "🔴" if balance < 0 else "🟢",
                    "balance": balance,
                    "pending_invoices": 0,
                    "urgency": "high" if balance < 0 else "low"
                },
                "business": {
                    "status": "🟢" if len(high_priority_missions) == 0 else "🟡",
                    "active_missions": len(active_missions.data),
                    "high_priority_count": len(high_priority_missions),
                    "urgency": "high" if len(high_priority_missions) > 2 else "medium"
                },
                "farm": {
                    "status": "🟢",
                    "total_investment": total_farm_spent,
                    "active_units": len(active_units.data),
                    "next_action": "Vérifier les stocks",
                    "urgency": "medium"
                },
                "documents": {
                    "status": "🔴" if len(urgent_docs) > 0 else "🟡" if len(pending_docs.data) > 0 else "🟢",
                    "pending_count": len(pending_docs.data),
                    "urgent_count": len(urgent_docs),
                    "urgency": "high" if len(urgent_docs) > 0 else "medium"
                },
                "wins": {
                    "status": "🟢",
                    "recent_count": len(recent_wins.data),
                    "streak": len(recent_wins.data),
                    "urgency": "low"
                },
                "relocation": {
                    "status": "🟡",
                    "pending_tasks": len(relocation_tasks.data),
                    "critical_count": len(critical_relocation),
                    "next_deadline": "2026-08-31",
                    "urgency": "high" if len(critical_relocation) > 0 else "medium"
                },
                "alignment": {
                    "status": "🟢" if alignment_score > 70 else "🟡",
                    "score": alignment_score,
                    "recommendation": "Prends un moment pour toi" if alignment_score < 50 else "Continue sur cette lancée",
                    "urgency": "low"
                }
            }
        }
        
    except Exception as e:
        logger.error(f"Erreur life_map: {e}")
        return {"success": False, "error": str(e)}



# =====================================================
# AGENT D'EXÉCUTION - EXECUTE MODE
# =====================================================

@app.post("/api/execute/analyze-request")
async def analyze_execute_request(request: Dict[str, Any]):
    """
    Analyse une demande utilisateur et retourne un plan d'exécution
    """
    query = request.get("query", "")
    if not query:
        return {"success": False, "error": "Query requise"}
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": """Tu es Becks, l'agent d'exécution de Rebecca. Ton rôle est de transformer une demande en plan d'action concret.

Analyse la demande et retourne UNIQUEMENT du JSON valide avec cette structure :

{
  "type": "email|task|checklist|plan|document|meeting",
  "title": "titre de l'action",
  "steps": ["étape 1", "étape 2", "étape 3"],
  "suggested_tasks": [
    {"title": "tâche 1", "priority": "high/medium/low", "due_offset": "1d|2d|3d|1w"},
    {"title": "tâche 2", "priority": "high/medium/low", "due_offset": "1d|2d|3d|1w"}
  ],
  "draft_content": "contenu si c'est un email/document (optionnel)",
  "questions": ["question à poser si info manquante"],
  "next_action": "prochaine action immédiate"
}

Types possibles : email, task, checklist, plan, document, meeting"""
                },
                {"role": "user", "content": query}
            ],
            temperature=0.3,
            max_tokens=1000
        )
        
        result = response.choices[0].message.content
        json_match = re.search(r'\{[\s\S]*\}', result)
        if json_match:
            execution_plan = json.loads(json_match.group())
        else:
            raise ValueError("Pas de JSON trouvé")
        
        return {"success": True, "execution_plan": execution_plan}
        
    except Exception as e:
        logger.error(f"Erreur analyze_execute_request: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/execute/create-checklist")
async def create_checklist(request: Dict[str, Any]):
    """Crée une checklist à partir d'un plan"""
    title = request.get("title", "Checklist")
    steps = request.get("steps", [])
    
    if not steps:
        return {"success": False, "error": "Steps requis"}
    
    # Sauvegarder la checklist
    checklist_id = str(uuid.uuid4())
    if supabase:
        supabase.table("checklists").insert({
            "id": checklist_id,
            "title": title,
            "steps": steps,
            "progress": 0,
            "user_id": "rebecca",
            "created_at": datetime.now().isoformat()
        }).execute()
    
    return {
        "success": True,
        "checklist": {
            "id": checklist_id,
            "title": title,
            "steps": steps,
            "progress": 0
        }
    }


@app.post("/api/execute/create-draft")
async def create_draft(request: Dict[str, Any]):
    """Génère un brouillon (email, document, etc.)"""
    draft_type = request.get("type", "email")
    context = request.get("context", "")
    
    if not context:
        return {"success": False, "error": "Context requis"}
    
    # Définir le prompt selon le type
    prompts = {
        "email": f"Rédige un email professionnel à partir de ce contexte. Style: clair, direct, professionnel. Contexte: {context}",
        "proposal": f"Rédige une proposition courte à partir de ce contexte. Contexte: {context}",
        "letter": f"Rédige une lettre formelle à partir de ce contexte. Contexte: {context}",
        "note": f"Rédige une note professionnelle à partir de ce contexte. Contexte: {context}"
    }
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": prompts.get(draft_type, prompts["email"])},
                {"role": "user", "content": "Génère le contenu final, prêt à être copié."}
            ],
            temperature=0.5,
            max_tokens=1000
        )
        
        draft_content = response.choices[0].message.content
        
        # Sauvegarder le draft
        draft_id = str(uuid.uuid4())
        if supabase:
            supabase.table("drafts").insert({
                "id": draft_id,
                "type": draft_type,
                "content": draft_content,
                "context": context,
                "user_id": "rebecca",
                "created_at": datetime.now().isoformat()
            }).execute()
        
        return {
            "success": True,
            "draft": {
                "id": draft_id,
                "type": draft_type,
                "content": draft_content
            }
        }
        
    except Exception as e:
        logger.error(f"Erreur create_draft: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/execute/update-checklist-step")
async def update_checklist_step(request: Dict[str, Any]):
    """Marque une étape comme complétée"""
    checklist_id = request.get("checklist_id")
    step_index = request.get("step_index")
    
    if not checklist_id or step_index is None:
        return {"success": False, "error": "checklist_id et step_index requis"}
    
    try:
        # Récupérer la checklist
        checklist = supabase.table("checklists").select("*").eq("id", checklist_id).execute()
        if not checklist.data:
            return {"success": False, "error": "Checklist non trouvée"}
        
        steps = checklist.data[0].get("steps", [])
        if step_index < len(steps):
            # Marquer comme complété (on pourrait stocker la progression)
            completed = checklist.data[0].get("completed_steps", [])
            if step_index not in completed:
                completed.append(step_index)
            
            progress = int((len(completed) / len(steps)) * 100)
            
            supabase.table("checklists").update({
                "completed_steps": completed,
                "progress": progress,
                "updated_at": datetime.now().isoformat()
            }).eq("id", checklist_id).execute()
            
            return {"success": True, "progress": progress, "completed": len(completed), "total": len(steps)}
        
        return {"success": False, "error": "Step invalide"}
        
    except Exception as e:
        logger.error(f"Erreur update_checklist_step: {e}")
        return {"success": False, "error": str(e)}



# =====================================================
# LOVE & FIRE SPORT MODULE
# =====================================================

@app.get("/api/lf/stats")
async def get_lf_stats():
    """Récupère les statistiques du module Love & Fire Sport"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        # Grants
        grants = supabase.table("lf_grants").select("*").execute()
        active_grants = [g for g in grants.data if g.get("status") not in ["approved", "rejected"]]
        submitted_grants = [g for g in grants.data if g.get("status") == "submitted"]
        
        # Contrats
        contracts = supabase.table("lf_contracts").select("*").execute()
        dda_contracts = [c for c in contracts.data if c.get("contract_type") == "DDA"]
        
        # Tâches
        tasks = supabase.table("lf_tasks").select("*").neq("status", "done").execute()
        urgent_tasks = [t for t in tasks.data if t.get("priority") == "high" and t.get("status") != "done"]
        
        # Prochaines deadlines
        today = datetime.now().date().isoformat()
        upcoming_grants = [g for g in grants.data if g.get("deadline") and g["deadline"] >= today]
        upcoming_grants.sort(key=lambda x: x.get("deadline", "9999-12-31"))
        
        return {
            "success": True,
            "stats": {
                "total_grants": len(grants.data),
                "active_grants": len(active_grants),
                "submitted_grants": len(submitted_grants),
                "total_contracts": len(contracts.data),
                "dda_contracts": len(dda_contracts),
                "pending_tasks": len(tasks.data),
                "urgent_tasks": len(urgent_tasks),
                "next_deadline": upcoming_grants[0].get("deadline") if upcoming_grants else None,
                "next_deadline_title": upcoming_grants[0].get("title") if upcoming_grants else None
            }
        }
    except Exception as e:
        logger.error(f"Erreur lf_stats: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/lf/grants")
async def get_lf_grants(status: str = None):
    """Récupère la liste des grants"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        query = supabase.table("lf_grants").select("*").order("deadline", nulls_last=True)
        if status:
            query = query.eq("status", status)
        result = query.execute()
        return {"success": True, "grants": result.data}
    except Exception as e:
        logger.error(f"Erreur lf_grants: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/lf/grant")
async def create_lf_grant(request: Dict[str, Any]):
    """Crée un nouveau grant"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        result = supabase.table("lf_grants").insert({
            "title": request.get("title"),
            "agency": request.get("agency"),
            "amount": request.get("amount"),
            "deadline": request.get("deadline"),
            "status": request.get("status", "researching"),
            "probability": request.get("probability", 50),
            "notes": request.get("notes"),
            "created_at": datetime.now().isoformat()
        }).execute()
        
        # Créer une tâche associée
        if result.data:
            supabase.table("lf_tasks").insert({
                "title": f"Préparer dossier pour {request.get('title')}",
                "related_to": "grant",
                "related_id": result.data[0]["id"],
                "deadline": request.get("deadline"),
                "priority": "high",
                "created_at": datetime.now().isoformat()
            }).execute()
        
        return {"success": True, "grant": result.data[0] if result.data else None}
    except Exception as e:
        logger.error(f"Erreur create_lf_grant: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/lf/contract")
async def create_lf_contract(request: Dict[str, Any]):
    """Crée un nouveau contrat"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        result = supabase.table("lf_contracts").insert({
            "title": request.get("title"),
            "contract_type": request.get("contract_type"),
            "agency": request.get("agency"),
            "status": request.get("status", "draft"),
            "deadline": request.get("deadline"),
            "requirements": request.get("requirements", []),
            "notes": request.get("notes"),
            "created_at": datetime.now().isoformat()
        }).execute()
        
        return {"success": True, "contract": result.data[0] if result.data else None}
    except Exception as e:
        logger.error(f"Erreur create_lf_contract: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/lf/checklist")
async def get_lf_checklist():
    """Récupère la checklist DDA complète"""
    checklist = [
        {"id": "dda_1", "title": "Créer compte DDA", "status": "pending", "deadline": None},
        {"id": "dda_2", "title": "Compléter formulaire d'identification", "status": "pending", "deadline": None},
        {"id": "dda_3", "title": "Soumettre preuve de statut juridique", "status": "pending", "deadline": None},
        {"id": "dda_4", "title": "Soumettre description des services", "status": "pending", "deadline": None},
        {"id": "dda_5", "title": "Soumettre preuve d'assurance", "status": "pending", "deadline": None},
        {"id": "dda_6", "title": "Attendre approbation", "status": "pending", "deadline": None},
        {"id": "sam_1", "title": "Créer compte SAM.gov", "status": "pending", "deadline": None},
        {"id": "sam_2", "title": "Compléter registration UEI", "status": "pending", "deadline": None},
        {"id": "sam_3", "title": "Soumettre registration", "status": "pending", "deadline": None},
        {"id": "emma_1", "title": "Créer compte eMMA", "status": "pending", "deadline": None},
        {"id": "emma_2", "title": "Soumettre vendor registration Maryland", "status": "pending", "deadline": None},
        {"id": "insurance_1", "title": "Obtenir attestation d'assurance", "status": "pending", "deadline": "2026-06-15"},
        {"id": "budget_1", "title": "Préparer budget pilote", "status": "pending", "deadline": "2026-06-30"},
        {"id": "business_plan_1", "title": "Finaliser business plan", "status": "pending", "deadline": "2026-07-15"},
    ]
    return {"success": True, "checklist": checklist}

@app.get("/api/lf/contracts")
async def get_lf_contracts(status: str = None):
    """Récupère la liste des contrats"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        query = supabase.table("lf_contracts").select("*").order("deadline", nulls_last=True)
        if status:
            query = query.eq("status", status)
        result = query.execute()
        return {"success": True, "contracts": result.data}
    except Exception as e:
        logger.error(f"Erreur lf_contracts: {e}")
        return {"success": False, "error": str(e)}


# =====================================================
# EMAIL (BREVO)
# =====================================================

import httpx
from pydantic import BaseModel, EmailStr
from typing import Optional

BREVO_API_KEY = os.environ.get("BREVO_API_KEY")
BREVO_SENDER_EMAIL = os.environ.get("BREVO_SENDER_EMAIL", "sovereign@rebecca.com")
BREVO_SENDER_NAME = os.environ.get("BREVO_SENDER_NAME", "SOVEREIGN - Becks")

class EmailRequest(BaseModel):
    to: EmailStr
    subject: str
    body: str
    to_name: Optional[str] = None

@app.post("/api/email/send")
async def send_email(request: EmailRequest):
    """Envoie un email via Brevo"""
    if not BREVO_API_KEY:
        return {"success": False, "error": "BREVO_API_KEY non configurée"}
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={
                    "api-key": BREVO_API_KEY,
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                json={
                    "sender": {
                        "name": BREVO_SENDER_NAME,
                        "email": BREVO_SENDER_EMAIL
                    },
                    "to": [{
                        "email": request.to,
                        "name": request.to_name or request.to.split("@")[0]
                    }],
                    "subject": request.subject,
                    "htmlContent": request.body,
                },
                timeout=30.0
            )
            
            if response.status_code == 201:
                logger.info(f"📧 Email envoyé à {request.to}")
                return {"success": True, "message": "Email envoyé"}
            else:
                logger.error(f"Erreur Brevo: {response.text}")
                return {"success": False, "error": response.text}
                
    except Exception as e:
        logger.error(f"Erreur envoi email: {e}")
        return {"success": False, "error": str(e)}


# =====================================================
# WEBHOOKS
# =====================================================



WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "sovereign-secret-key-2024")

# Stockage simple des webhooks (en mémoire pour commencer)
webhooks_subscriptions = []

class WebhookSubscription(BaseModel):
    url: str
    event: str
    active: bool = True

@app.post("/api/webhooks/subscribe")
async def subscribe_webhook(subscription: WebhookSubscription):
    """Enregistre un webhook sans doublon"""
    global webhooks_subscriptions
    
    # Vérifier si existe déjà
    existing = [s for s in webhooks_subscriptions 
                if s["url"] == subscription.url and s["event"] == subscription.event]
    
    if existing:
        logger.info(f"🔗 Webhook déjà existant: {subscription.event} -> {subscription.url}")
        return {"success": True, "message": "Déjà inscrit", "subscriptions": webhooks_subscriptions}
    
    webhooks_subscriptions.append({
        "url": subscription.url,
        "event": subscription.event,
        "active": True,
        "created_at": datetime.now().isoformat()
    })
    
    logger.info(f"🔗 Webhook inscrit: {subscription.event} -> {subscription.url}")
    return {"success": True, "subscriptions": webhooks_subscriptions}
@app.get("/api/webhooks/subscriptions")
async def get_webhooks():
    """Liste tous les webhooks"""
    return {"success": True, "subscriptions": webhooks_subscriptions}

async def trigger_webhook(event: str, payload: dict):
    """Déclenche les webhooks pour un événement"""
    subscribers = [s for s in webhooks_subscriptions if s["event"] == event and s["active"]]
    
    logger.info(f"🔍 {len(subscribers)} webhook(s) trouvé(s) pour l'événement: {event}")
    
    if not subscribers:
        logger.info(f"📭 Aucun webhook inscrit pour {event}")
        return
    
    for sub in subscribers:
        try:
            logger.info(f"📤 Envoi à {sub['url']}...")
            async with httpx.AsyncClient() as client:
                response = await client.post(sub["url"], json=payload, timeout=10.0)
            logger.info(f"✅ Webhook envoyé à {sub['url']} - Status: {response.status_code}")
        except Exception as e:
            logger.error(f"❌ Erreur webhook {sub['url']}: {type(e).__name__} - {e}")



# =====================================================
# GOOGLE CALENDAR
# =====================================================

import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from typing import Optional, List

# Configuration Google Calendar
GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
GOOGLE_SERVICE_ACCOUNT_INFO = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", None)

class CalendarEventRequest(BaseModel):
    summary: str
    description: Optional[str] = None
    start_datetime: str
    end_datetime: str
    attendees: Optional[List[str]] = None

def get_calendar_service():
    """Initialise le service Google Calendar avec le compte de service"""
    if not GOOGLE_SERVICE_ACCOUNT_INFO:
        logger.warning("⚠️ GOOGLE_SERVICE_ACCOUNT_JSON non configuré")
        return None
    
    try:
        # Charger les infos du compte de service
        service_account_info = json.loads(GOOGLE_SERVICE_ACCOUNT_INFO)
        
        creds = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=['https://www.googleapis.com/auth/calendar']
        )
        
        service = build('calendar', 'v3', credentials=creds)
        logger.info("✅ Google Calendar service initialisé")
        return service
    except Exception as e:
        logger.error(f"❌ Erreur auth Google Calendar: {e}")
        return None

@app.post("/api/calendar/event")
async def create_calendar_event(request: CalendarEventRequest):
    """Crée un événement dans Google Calendar"""
    service = get_calendar_service()
    if not service:
        return {"success": False, "error": "Google Calendar non configuré"}
    
    try:
        event = {
            'summary': request.summary,
            'description': request.description or "",
            'start': {
                'dateTime': request.start_datetime,
                'timeZone': 'Africa/Porto-Novo',
            },
            'end': {
                'dateTime': request.end_datetime,
                'timeZone': 'Africa/Porto-Novo',
            },
        }
        
        if request.attendees:
            event['attendees'] = [{'email': email} for email in request.attendees]
        
        created_event = service.events().insert(
            calendarId=GOOGLE_CALENDAR_ID,
            body=event
        ).execute()
        
        logger.info(f"📅 Événement créé: {created_event.get('htmlLink')}")
        return {
            "success": True,
            "event_id": created_event.get('id'),
            "link": created_event.get('htmlLink')
        }
        
    except Exception as e:
        logger.error(f"❌ Erreur création événement: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/calendar/sync-task")
async def sync_task_to_calendar(request: Dict[str, Any]):
    """Synchronise une tâche spécifique vers Google Calendar"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    task_id = request.get("task_id")
    if not task_id:
        return {"success": False, "error": "task_id requis"}
    
    try:
        # Récupérer la tâche
        task = supabase.table("tasks").select("*").eq("id", task_id).execute()
        
        if not task.data:
            return {"success": False, "error": "Tâche non trouvée"}
        
        task = task.data[0]
        
        if not task.get("due_date"):
            return {"success": False, "error": "La tâche n'a pas de date d'échéance"}
        
        # Créer l'événement
        event = await create_calendar_event(CalendarEventRequest(
            summary=task["title"],
            description=f"Tâche Sovereign - Priorité: {task.get('priority', 'normal')}",
            start_datetime=f"{task['due_date']}T09:00:00",
            end_datetime=f"{task['due_date']}T10:00:00"
        ))
        
        if event.get("success"):
            # Marquer comme synchronisée
            supabase.table("tasks").update({
                "calendar_synced": True,
                "calendar_event_id": event["event_id"]
            }).eq("id", task_id).execute()
        
        return event
        
    except Exception as e:
        logger.error(f"❌ Erreur sync tâche: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/calendar/sync-existing-task")
async def sync_existing_task_to_calendar(request: Dict[str, Any]):
    """Synchronise une tâche existante vers Google Calendar (pour rattrapage)"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    task_id = request.get("task_id")
    if not task_id:
        return {"success": False, "error": "task_id requis"}
    
    try:
        # Récupérer la tâche
        task = supabase.table("tasks").select("*").eq("id", task_id).execute()
        
        if not task.data:
            return {"success": False, "error": "Tâche non trouvée"}
        
        task = task.data[0]
        
        if not task.get("due_date"):
            return {"success": False, "error": "La tâche n'a pas de date d'échéance"}
        
        # Vérifier si déjà synchronisée
        if task.get("calendar_synced"):
            return {"success": True, "message": "Déjà synchronisée", "calendar_link": task.get("calendar_link")}
        
        # Créer l'événement
        event = await create_calendar_event(CalendarEventRequest(
            summary=task["title"],
            description=f"Tâche Sovereign - Priorité: {task.get('priority', 'normal')}",
            start_datetime=f"{task['due_date']}T09:00:00",
            end_datetime=f"{task['due_date']}T10:00:00"
        ))
        
        if event.get("success"):
            # Marquer comme synchronisée
            supabase.table("tasks").update({
                "calendar_synced": True,
                "calendar_event_id": event["event_id"],
                "calendar_link": event["link"]
            }).eq("id", task_id).execute()
            
            logger.info(f"📅 Tâche existante {task_id} synchronisée avec Google Calendar")
            return {
                "success": True, 
                "message": "Tâche synchronisée",
                "calendar_link": event["link"],
                "event_id": event["event_id"]
            }
        
        return event
        
    except Exception as e:
        logger.error(f"❌ Erreur sync tâche existante: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/clean-expired-subscriptions")
async def clean_expired_subscriptions():
    """Nettoie les subscriptions push expirées"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        # Récupérer toutes les subscriptions
        subscriptions = supabase.table("push_subscriptions").select("*").execute()
        
        deleted_count = 0
        for sub in subscriptions.data:
            try:
                # Tester la subscription
                webpush(
                    subscription_info={
                        "endpoint": sub["endpoint"],
                        "keys": sub["keys"]
                    },
                    data=json.dumps({"title": "Test", "body": "Test"}),
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims=VAPID_CLAIMS
                )
            except WebPushException as e:
                if e.response and e.response.status_code in [401, 403, 404, 410]:
                    # Supprimer la subscription invalide
                    supabase.table("push_subscriptions").delete().eq("id", sub["id"]).execute()
                    deleted_count += 1
                    logger.info(f"🗑️ Subscription supprimée: {sub['endpoint'][:50]}...")
        
        return {"success": True, "deleted": deleted_count, "total": len(subscriptions.data)}
        
    except Exception as e:
        logger.error(f"Erreur nettoyage: {e}")
        return {"success": False, "error": str(e)}



# =====================================================
# VOIX LIVE AVEC ELEVENLABS
# =====================================================

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

@app.post("/api/voice/speak")
async def speak_text(request: Dict[str, Any]):
    """Convertit un texte en audio avec ElevenLabs"""
    text = request.get("text", "")
    if not text:
        return {"success": False, "error": "Texte requis"}
    
    if not ELEVENLABS_API_KEY:
        logger.warning("⚠️ ElevenLabs non configuré")
        return {"success": False, "error": "ElevenLabs non configuré"}
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
                headers={
                    "xi-api-key": ELEVENLABS_API_KEY,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg"
                },
                json={
                    "text": text,
                    "model_id": "eleven_turbo_v2",
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75
                    }
                },
                timeout=30.0
            )
            
            if response.status_code == 200:
                import base64
                audio_base64 = base64.b64encode(response.content).decode('utf-8')
                return {"success": True, "audio": audio_base64, "format": "mp3"}
            else:
                logger.error(f"Erreur ElevenLabs: {response.text}")
                return {"success": False, "error": response.text}
                
    except Exception as e:
        logger.error(f"Erreur ElevenLabs: {e}")
        return {"success": False, "error": str(e)}


# =====================================================
# MICROSOFT EDGE TTS (gratuit, sans carte bancaire)
# =====================================================

EDGE_TTS_TOKEN = "6A5AA1D4EAFF4E9FB37E23D68491D6F4"

@app.post("/api/voice/edge-speak")
async def edge_speak_text(request: Dict[str, Any]):
    """Convertit un texte en audio avec Microsoft Edge TTS"""
    text = request.get("text", "")
    if not text:
        return {"success": False, "error": "Texte requis"}
    
    voice = request.get("voice", "fr-FR-DeniseNeural")
    
    try:
        import urllib.parse
        encoded_text = urllib.parse.quote(text)
        
        url = f"https://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken={EDGE_TTS_TOKEN}&Voice={voice}&Text={encoded_text}"
        
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(url, timeout=30.0)
            
            if response.status_code == 200:
                import base64
                audio_base64 = base64.b64encode(response.content).decode('utf-8')
                return {"success": True, "audio": audio_base64, "format": "mp3", "voice": voice}
            else:
                logger.error(f"Erreur Edge TTS: {response.status_code}")
                return {"success": False, "error": f"Erreur {response.status_code}"}
                
    except Exception as e:
        logger.error(f"Erreur Edge TTS: {e}")
        return {"success": False, "error": str(e)}



# =====================================================
# PROACTIF - RÉSUMÉ MATINAL
# =====================================================

@app.post("/api/proactive/morning-brief")
async def send_morning_brief():
    """
    Envoie un résumé matinal par email et notification push.
    À appeler par cron-job.org tous les jours à 7h.
    """
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        today = datetime.now().date().isoformat()
        
        # Récupérer les tâches du jour
        tasks_today = supabase.table("tasks").select("*").eq("due_date", today).neq("status", "done").execute()
        
        # Récupérer les tâches en retard
        overdue_tasks = supabase.table("tasks").select("*").lt("due_date", today).neq("status", "done").execute()
        
        # Récupérer les documents proches de l'échéance
        next_week = (datetime.now().date() + timedelta(days=7)).isoformat()
        expiring_docs = supabase.table("documents").select("*").gte("due_date", today).lte("due_date", next_week).neq("status", "approved").execute()
        
        # Récupérer les victoires récentes (7 derniers jours)
        week_ago = (datetime.now().date() - timedelta(days=7)).isoformat()
        recent_wins = supabase.table("wins").select("*").gte("date", week_ago).execute()
        
        # Récupérer les missions actives
        active_missions = supabase.table("missions").select("*").eq("status", "active").execute()
        
        # Construire le message
        message = f"""🌅 **Bonjour Rebecca ! Voici ton résumé matinal**

📅 **{datetime.now().strftime('%A %d %B %Y')}**

---

📋 **Tâches du jour** : {len(tasks_today.data)}
{chr(10).join([f'• {t["title"]}' for t in tasks_today.data[:5]]) if tasks_today.data else '• Aucune tâche planifiée'}

⚠️ **Tâches en retard** : {len(overdue_tasks.data)}
{chr(10).join([f'• {t["title"]}' for t in overdue_tasks.data[:3]]) if overdue_tasks.data else '• Aucune tâche en retard'}

📄 **Documents à venir** : {len(expiring_docs.data)}
{chr(10).join([f'• {d["name"]} ({d["due_date"]})' for d in expiring_docs.data[:3]]) if expiring_docs.data else '• Aucun document imminent'}

🎯 **Missions actives** : {len(active_missions.data)}
{chr(10).join([f'• {m["name"]}' for m in active_missions.data[:3]]) if active_missions.data else '• Aucune mission active'}

🏆 **Victoires récentes** : {len(recent_wins.data)} cette semaine

---

💡 **Becks te conseille** : Concentre-toi sur les tâches prioritaires du jour. Une chose à la fois. Tu gères ! 👑
"""
        
        # Envoyer un email (si Brevo configuré)
        email_sent = False
        if BREVO_API_KEY:
            try:
                # Récupérer l'email de l'utilisateur (à adapter)
                user_email = "jbillcataria@gmail.com" 
                
                email_body = message.replace("\n", "<br>")
                await send_email(EmailRequest(
                    to=user_email,
                    subject=f"🌅 Sovereign - Résumé matinal du {datetime.now().strftime('%d/%m/%Y')}",
                    body=email_body
                ))
                email_sent = True
                logger.info("📧 Résumé matinal envoyé par email")
            except Exception as e:
                logger.error(f"Erreur envoi email résumé: {e}")
        
        # Envoyer une notification push
        push_sent = False
        try:
            send_notification_sync({
                "title": "🌅 Bonjour Rebecca",
                "body": f"{len(tasks_today.data)} tâches aujourd'hui, {len(overdue_tasks.data)} en retard",
                "url": "/tasks",
                "type": "brief",
                "requireInteraction": False
            })
            push_sent = True
            logger.info("🔔 Notification push résumé envoyée")
        except Exception as e:
            logger.error(f"Erreur envoi push résumé: {e}")
        
        return {
            "success": True,
            "message": "Résumé matinal envoyé",
            "stats": {
                "tasks_today": len(tasks_today.data),
                "overdue_tasks": len(overdue_tasks.data),
                "expiring_docs": len(expiring_docs.data),
                "active_missions": len(active_missions.data),
                "recent_wins": len(recent_wins.data)
            },
            "email_sent": email_sent,
            "push_sent": push_sent
        }
        
    except Exception as e:
        logger.error(f"Erreur résumé matinal: {e}")
        return {"success": False, "error": str(e)}



# =====================================================
# PROACTIF - VEILLE SUR PROJETS INACTIFS
# =====================================================

@app.post("/api/proactive/stale-missions")
async def check_stale_missions():
    """
    Vérifie les missions inactives (pas de mise à jour depuis 5 jours)
    et envoie des alertes par email et notification push.
    À appeler par cron-job.org toutes les 6h.
    """
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        # Récupérer les missions actives
        active_missions = supabase.table("missions").select("*").eq("status", "active").execute()
        
        if not active_missions.data:
            return {"success": True, "message": "Aucune mission active", "stale_missions": []}
        
        # Calculer la date limite (5 jours)
        five_days_ago = (datetime.now() - timedelta(days=5)).isoformat()
        
        # Filtrer les missions inactives
        stale_missions = []
        for mission in active_missions.data:
            updated_at = mission.get("updated_at")
            if updated_at and updated_at < five_days_ago:
                stale_missions.append(mission)
            elif not updated_at:
                # Si jamais mise à jour, vérifier created_at
                created_at = mission.get("created_at")
                if created_at and created_at < five_days_ago:
                    stale_missions.append(mission)
        
        if not stale_missions:
            return {"success": True, "message": "Aucune mission inactive", "stale_missions": []}
        
        # Construire le message
        mission_list = "\n".join([f"• {m['name']} (dernière activité: {m.get('updated_at', m.get('created_at', 'inconnue'))[:10]})" for m in stale_missions])
        
        message = f"""⚠️ **Alerte - Missions inactives**

{len(stale_missions)} mission(s) n'ont pas eu d'activité depuis plus de 5 jours :

{mission_list}

---

🎯 **Action recommandée** :
- Fais le point sur l'avancement de ces missions
- Mets à jour leur statut ou priorité
- Si terminées, passe-les en "complete"

Becks reste à ta disposition pour t'aider. 👑
"""
        
        # Envoyer un email
        email_sent = False
        if BREVO_API_KEY:
            try:
                user_email = "jbillcataria@gmail.com"   
                email_body = message.replace("\n", "<br>")
                await send_email(EmailRequest(
                    to=user_email,
                    subject=f"⚠️ {len(stale_missions)} mission(s) inactive(s) - Sovereign",
                    body=email_body
                ))
                email_sent = True
                logger.info(f"📧 Email missions inactives envoyé ({len(stale_missions)} missions)")
            except Exception as e:
                logger.error(f"Erreur envoi email missions inactives: {e}")
        
        # Envoyer une notification push
        push_sent = False
        try:
            send_notification_sync({
                "title": "⚠️ Missions inactives",
                "body": f"{len(stale_missions)} mission(s) sans activité depuis 5 jours",
                "url": "/missions",
                "type": "mission",
                "requireInteraction": True
            })
            push_sent = True
            logger.info("🔔 Notification push missions inactives envoyée")
        except Exception as e:
            logger.error(f"Erreur envoi push missions inactives: {e}")
        
        return {
            "success": True,
            "message": f"{len(stale_missions)} mission(s) inactive(s) signalée(s)",
            "stale_missions": [
                {
                    "id": m["id"],
                    "name": m["name"],
                    "last_activity": m.get("updated_at", m.get("created_at"))
                }
                for m in stale_missions
            ],
            "email_sent": email_sent,
            "push_sent": push_sent
        }
        
    except Exception as e:
        logger.error(f"Erreur check stale missions: {e}")
        return {"success": False, "error": str(e)}




# =====================================================
# PROACTIF - DÉTECTION D'OPPORTUNITÉS
# =====================================================

@app.post("/api/proactive/opportunities-alert")
async def check_opportunities_alert():
    """
    Vérifie les grants et contrats proches de l'échéance (≤ 7 jours)
    et envoie des alertes.
    À appeler par cron-job.org toutes les 12h.
    """
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        today = datetime.now().date()
        next_week = today + timedelta(days=7)
        today_iso = today.isoformat()
        next_week_iso = next_week.isoformat()
        
        # Récupérer les grants proches de l'échéance
        grants = supabase.table("lf_grants").select("*").gte("deadline", today_iso).lte("deadline", next_week_iso).execute()
        
        # Récupérer les contrats proches de l'échéance
        contracts = supabase.table("lf_contracts").select("*").gte("deadline", today_iso).lte("deadline", next_week_iso).execute()
        
        # Récupérer les opportunités générales
        opportunities = supabase.table("opportunities").select("*").gte("deadline", today_iso).lte("deadline", next_week_iso).neq("stage", "won").execute()
        
        all_items = []
        
        for grant in grants.data:
            all_items.append({
                "type": "grant",
                "title": grant.get("title"),
                "deadline": grant.get("deadline"),
                "agency": grant.get("agency"),
                "amount": grant.get("amount")
            })
        
        for contract in contracts.data:
            all_items.append({
                "type": "contract",
                "title": contract.get("title"),
                "deadline": contract.get("deadline"),
                "agency": contract.get("agency")
            })
        
        for opp in opportunities.data:
            all_items.append({
                "type": "opportunity",
                "title": opp.get("title"),
                "deadline": opp.get("deadline"),
                "estimated_value": opp.get("estimated_value")
            })
        
        if not all_items:
            return {"success": True, "message": "Aucune opportunité proche", "opportunities": []}
        
        # Construire le message
        items_by_day = {}
        for item in all_items:
            day = item["deadline"]
            if day not in items_by_day:
                items_by_day[day] = []
            items_by_day[day].append(item)
        
        message = f"""💰 **Alerte - Opportunités à saisir**

{len(all_items)} opportunité(s) approchent de leur échéance dans les 7 jours :

"""
        for day, items in sorted(items_by_day.items()):
            message += f"\n📅 **{day}** :\n"
            for item in items:
                if item["type"] == "grant":
                    message += f"   • 🎯 Grant: {item['title']} ({item.get('agency', 'N/A')}) - {item.get('amount', 0):,} CFA\n"
                elif item["type"] == "contract":
                    message += f"   • 📑 Contrat: {item['title']} ({item.get('agency', 'N/A')})\n"
                else:
                    message += f"   • 💼 Opportunité: {item['title']} - {item.get('estimated_value', 0):,} CFA\n"
        
        message += """

⚡ **Action recommandée** :
- Prépare les dossiers rapidement
- Programme des rappels pour ne rien oublier
- Contacte les parties prenantes dès aujourd'hui

Becks peut t'aider à préparer les documents. 👑
"""
        
        # Envoyer un email
        email_sent = False
        if BREVO_API_KEY:
            try:
                user_email = "rebecca@sovereign.com"  # À remplacer
                email_body = message.replace("\n", "<br>")
                await send_email(EmailRequest(
                    to=user_email,
                    subject=f"💰 {len(all_items)} opportunité(s) à saisir - Sovereign",
                    body=email_body
                ))
                email_sent = True
                logger.info(f"📧 Email opportunités envoyé ({len(all_items)} opportunités)")
            except Exception as e:
                logger.error(f"Erreur envoi email opportunités: {e}")
        
        # Envoyer une notification push
        push_sent = False
        try:
            send_notification_sync({
                "title": "💰 Opportunités à saisir",
                "body": f"{len(all_items)} opportunité(s) approchent de leur échéance",
                "url": "/love-fire-sport",
                "type": "money",
                "requireInteraction": True
            })
            push_sent = True
            logger.info("🔔 Notification push opportunités envoyée")
        except Exception as e:
            logger.error(f"Erreur envoi push opportunités: {e}")
        
        return {
            "success": True,
            "message": f"{len(all_items)} opportunité(s) détectée(s)",
            "opportunities": all_items,
            "email_sent": email_sent,
            "push_sent": push_sent
        }
        
    except Exception as e:
        logger.error(f"Erreur check opportunities: {e}")
        return {"success": False, "error": str(e)}


# =====================================================
# PROACTIF - PLANNING AUTOMATIQUE
# =====================================================

@app.post("/api/proactive/daily-planning")
async def daily_planning():
    """
    Analyse les tâches et suggère un ordre de priorité pour la journée.
    À appeler par cron-job.org tous les matins à 8h (après le résumé).
    """
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        today = datetime.now().date().isoformat()
        
        # Récupérer les tâches du jour
        tasks_today = supabase.table("tasks").select("*").eq("due_date", today).neq("status", "done").execute()
        
        # Récupérer les tâches en retard
        overdue_tasks = supabase.table("tasks").select("*").lt("due_date", today).neq("status", "done").execute()
        
        # Récupérer les tâches prioritaires (high/critical)
        high_priority_tasks = supabase.table("tasks").select("*").in_("priority", ["critical", "high"]).neq("status", "done").execute()
        
        # Construire la suggestion d'ordre
        planning = []
        
        # 1. D'abord les tâches en retard
        for task in overdue_tasks.data[:3]:
            planning.append({
                "position": len(planning) + 1,
                "title": task["title"],
                "reason": "⚠️ En retard",
                "priority": "critical"
            })
        
        # 2. Ensuite les tâches critiques
        for task in [t for t in high_priority_tasks.data if t.get("priority") == "critical" and t not in overdue_tasks.data][:3]:
            planning.append({
                "position": len(planning) + 1,
                "title": task["title"],
                "reason": "🔴 Priorité critique",
                "priority": "critical"
            })
        
        # 3. Puis les tâches du jour
        for task in tasks_today.data[:3]:
            if task not in overdue_tasks.data:
                planning.append({
                    "position": len(planning) + 1,
                    "title": task["title"],
                    "reason": "📅 À faire aujourd'hui",
                    "priority": "high"
                })
        
        # 4. Enfin les tâches haute priorité restantes
        for task in [t for t in high_priority_tasks.data if t.get("priority") == "high" and t not in tasks_today.data and t not in overdue_tasks.data][:2]:
            planning.append({
                "position": len(planning) + 1,
                "title": task["title"],
                "reason": "🔸 Haute priorité",
                "priority": "high"
            })
        
        if not planning:
            planning = [{"position": 1, "title": "Prendre un moment pour planifier", "reason": "Aucune tâche urgente", "priority": "normal"}]
        
        # Construire le message
        order_list = "\n".join([f"{p['position']}. **{p['title']}** - {p['reason']}" for p in planning])
        
        message = f"""📋 **Planning automatique du jour**

Voici l'ordre de priorité suggéré pour aujourd'hui :

{order_list}

---

💡 **Conseil** : Commence par la tâche n°1, elle débloquera la suite. N'hésite pas à ajuster selon ton énergie.

Becks te soutient ! 👑
"""
        
        # Envoyer une notification push
        push_sent = False
        try:
            send_notification_sync({
                "title": "📋 Planning du jour",
                "body": f"Priorité 1 : {planning[0]['title']}",
                "url": "/tasks",
                "type": "task",
                "requireInteraction": False
            })
            push_sent = True
            logger.info("🔔 Notification push planning envoyée")
        except Exception as e:
            logger.error(f"Erreur envoi push planning: {e}")
        
        return {
            "success": True,
            "message": "Planning généré",
            "planning": planning,
            "stats": {
                "overdue_tasks": len(overdue_tasks.data),
                "tasks_today": len(tasks_today.data),
                "high_priority": len(high_priority_tasks.data)
            },
            "push_sent": push_sent
        }
        
    except Exception as e:
        logger.error(f"Erreur daily planning: {e}")
        return {"success": False, "error": str(e)}






# =====================================================
# BECKS EXECUTOR - ACTIONS CONCRÈTES
# =====================================================

class ExecutorAction(BaseModel):
    action_type: str  # "create_task", "send_email", "create_draft", "update_mission", "create_subtasks"
    params: Dict[str, Any]
    requires_confirmation: bool = True

@app.post("/api/executor/batch")
async def execute_batch_actions(actions: List[ExecutorAction], auto_confirm: bool = False):
    """
    Exécute une série d'actions proposées par Becks.
    Si auto_confirm=False, demande confirmation avant exécution.
    """
    results = []
    
    for action in actions:
        try:
            if action.action_type == "create_task":
                result = await create_task_from_conversation(ExecuteTaskRequest(
                    title=action.params.get("title"),
                    due_date=action.params.get("due_date"),
                    priority=action.params.get("priority", "normal")
                ))
                results.append({
                    "action": "create_task", 
                    "success": result.get("success"), 
                    "data": result.get("task")
                })
            
            elif action.action_type == "send_email":
                if auto_confirm or action.requires_confirmation == False:
                    # Récupérer l'email de l'utilisateur depuis la config
                    user_email = os.environ.get("USER_EMAIL", "rebecca@sovereign.com")
                    result = await send_email(EmailRequest(
                        to=action.params.get("to", user_email),
                        subject=action.params.get("subject", "Action Sovereign"),
                        body=action.params.get("body", "")
                    ))
                    results.append({"action": "send_email", "success": result.get("success")})
                else:
                    results.append({
                        "action": "send_email", 
                        "status": "pending_confirmation", 
                        "params": action.params
                    })
            
            elif action.action_type == "create_draft":
                result = await create_draft({
                    "type": action.params.get("type", "email"),
                    "context": action.params.get("context", "")
                })
                results.append({
                    "action": "create_draft", 
                    "success": result.get("success"), 
                    "data": result.get("draft")
                })
            
            elif action.action_type == "update_mission":
                mission_id = action.params.get("mission_id")
                if mission_id:
                    supabase.table("missions").update({
                        "status": action.params.get("status"),
                        "priority": action.params.get("priority")
                    }).eq("id", mission_id).execute()
                    results.append({"action": "update_mission", "success": True})
                else:
                    results.append({"action": "update_mission", "success": False, "error": "mission_id requis"})
            
            elif action.action_type == "create_subtasks":
                subtasks = action.params.get("subtasks", [])
                created = []
                for subtask in subtasks:
                    task = await create_task_from_conversation(ExecuteTaskRequest(
                        title=subtask.get("title"),
                        due_date=subtask.get("due_date"),
                        priority=subtask.get("priority", "normal")
                    ))
                    if task.get("success"):
                        created.append(task.get("task"))
                results.append({
                    "action": "create_subtasks", 
                    "success": len(created) > 0, 
                    "created": len(created),
                    "tasks": created
                })
            
            elif action.action_type == "create_reminder":
                result = await create_task_from_conversation(ExecuteTaskRequest(
                    title=action.params.get("title", "Rappel"),
                    due_date=action.params.get("due_date"),
                    priority="normal"
                ))
                results.append({"action": "create_reminder", "success": result.get("success"), "task": result.get("task")})
            
            else:
                results.append({
                    "action": action.action_type, 
                    "success": False, 
                    "error": f"Type d'action inconnu: {action.action_type}"
                })
        
        except Exception as e:
            logger.error(f"Erreur executor action {action.action_type}: {e}")
            results.append({"action": action.action_type, "success": False, "error": str(e)})
    
    return {"success": True, "results": results}




@app.post("/api/proactive/evening-summary")
async def send_evening_summary():
    """
    Envoie un résumé de la journée le soir (vers 19h).
    Inclut : tâches complétées, tâches restantes, victoires, conseil.
    """
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        today = datetime.now().date().isoformat()
        
        # Tâches complétées aujourd'hui
        completed_tasks = supabase.table("tasks").select("*").eq("status", "done").gte("updated_at", today).execute()
        
        # Tâches créées aujourd'hui non terminées
        pending_tasks = supabase.table("tasks").select("*").gte("created_at", today).neq("status", "done").execute()
        
        # Tâches en retard
        overdue_tasks = supabase.table("tasks").select("*").lt("due_date", today).neq("status", "done").execute()
        
        # Victoires d'aujourd'hui
        wins_today = supabase.table("wins").select("*").gte("date", today).execute()
        
        # Humeur du jour
        mood_today = supabase.table("mood_entries").select("*").eq("date", today).execute()
        
        # Construire le message
        completed_list = ""
        if completed_tasks.data:
            for t in completed_tasks.data[:5]:
                completed_list += f"\n• {t['title']}"
        else:
            completed_list = "\n• Rien de terminé aujourd'hui"
        
        pending_list = ""
        if pending_tasks.data:
            for t in pending_tasks.data[:3]:
                pending_list += f"\n• {t['title']}"
        else:
            pending_list = "\n• Tout est fait !"
        
        overdue_list = ""
        if overdue_tasks.data:
            for t in overdue_tasks.data[:3]:
                overdue_list += f"\n• {t['title']}"
        else:
            overdue_list = "\n• Aucune tâche en retard"
        
        wins_list = ""
        if wins_today.data:
            for w in wins_today.data[:3]:
                wins_list += f"\n• {w['title']} {w.get('celebration_emoji', '🎉')}"
        else:
            wins_list = "\n• Aucune victoire enregistrée"
        
        # Message d'humeur
        mood_text = ""
        if mood_today.data and mood_today.data[0].get("mood"):
            mood_map = {
                "excellent": "🌟 Excellente",
                "bien": "😊 Bonne",
                "neutre": "😐 Neutre",
                "fatiguée": "😴 Fatiguée",
                "stressée": "😰 Stressée"
            }
            mood_text = f"\n\n😊 **Humeur du jour** : {mood_map.get(mood_today.data[0]['mood'], mood_today.data[0]['mood'])}"
        
        # Construire le message final
        message = f"""🌙 **Bonsoir Rebecca ! Voici ton résumé de la journée**

📅 **{datetime.now().strftime('%A %d %B %Y')}**{mood_text}

---

✅ **Ce que tu as accompli aujourd'hui** : {len(completed_tasks.data)}{completed_list}

📋 **Tâches restantes** : {len(pending_tasks.data)}{pending_list}

⚠️ **Tâches en retard** : {len(overdue_tasks.data)}{overdue_list}

🏆 **Victoires du jour** : {len(wins_today.data)}{wins_list}

---

💡 **Conseil de Becks** : 
{_get_evening_advice(len(completed_tasks.data), len(pending_tasks.data), len(overdue_tasks.data))}

Passe une bonne soirée, repose-toi bien. Demain est un nouveau jour. 👑
"""

        # Envoyer notification push
        push_sent = False
        try:
            send_notification_sync({
                "title": "🌙 Résumé de ta journée",
                "body": f"{len(completed_tasks.data)} tâches accomplies, {len(wins_today.data)} victoires",
                "url": "/tasks",
                "type": "brief",
                "requireInteraction": False
            })
            push_sent = True
            logger.info("🔔 Notification push résumé soir envoyée")
        except Exception as e:
            logger.error(f"Erreur envoi push résumé soir: {e}")
        
        return {
            "success": True,
            "message": "Résumé de la journée envoyé",
            "stats": {
                "completed_tasks": len(completed_tasks.data),
                "pending_tasks": len(pending_tasks.data),
                "overdue_tasks": len(overdue_tasks.data),
                "wins_today": len(wins_today.data)
            },
            "push_sent": push_sent
        }
        
    except Exception as e:
        logger.error(f"Erreur résumé soir: {e}")
        return {"success": False, "error": str(e)}

def _get_evening_advice(completed: int, pending: int, overdue: int) -> str:
    """Génère un conseil personnalisé pour le soir"""
    if overdue > 0:
        return "Des tâches sont en retard. Demain matin, attaque la plus urgente en premier. Je te rappellerai."
    elif pending > 0 and completed == 0:
        return "Tu n'as rien terminé aujourd'hui. Ce n'est pas grave. Demain, concentre-toi sur UNE seule petite tâche."
    elif completed >= 3:
        return "Belle journée ! Tu as bien avancé. Repose-toi, tu as mérité cette soirée."
    elif completed > 0:
        return f"Tu as accompli {completed} tâche(s). Chaque pas compte. Demain, continue sur cette lancée."
    else:
        return "Parfois, se reposer est la meilleure action. Demain sera plus clair."





# =====================================================
# PROACTIF - RAPPELS INTELLIGENTS
# =====================================================

@app.post("/api/proactive/smart-reminders")
async def smart_reminders():
    """
    Analyse l'historique et propose des actions intelligentes.
    À appeler par cron-job.org tous les matins à 8h30.
    """
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        today = datetime.now().date().isoformat()
        week_ago = (datetime.now().date() - timedelta(days=7)).isoformat()
        
        # 1. Analyser les tâches récurrentes oubliées
        # Tâches qui apparaissent souvent mais rarement terminées
        task_titles = supabase.table("tasks").select("title, status").execute()
        task_count = {}
        for task in task_titles.data:
            title = task["title"]
            if title not in task_count:
                task_count[title] = {"total": 0, "done": 0}
            task_count[title]["total"] += 1
            if task.get("status") == "done":
                task_count[title]["done"] += 1
        
        forgotten_tasks = []
        for title, stats in task_count.items():
            if stats["total"] >= 3 and stats["done"] == 0:
                forgotten_tasks.append(title)
        
        # 2. Vérifier les missions sans activité
        stale_missions = supabase.table("missions").select("*").eq("status", "active").execute()
        stale_list = []
        for mission in stale_missions.data:
            updated_at = mission.get("updated_at")
            if updated_at and updated_at < week_ago:
                stale_list.append(mission["name"])
        
        # 3. Vérifier les documents qui traînent
        pending_docs = supabase.table("documents").select("*").eq("status", "draft").execute()
        
        # 4. Vérifier les opportunités non suivies
        pending_opps = supabase.table("opportunities").select("*").neq("stage", "won").neq("stage", "lost").execute()
        high_value_opps = [o for o in pending_opps.data if o.get("estimated_value", 0) > 1000000]
        
        # Construire les suggestions
        suggestions = []
        
        if forgotten_tasks:
            suggestions.append(f"📋 **Tâches récurrentes à faire** : {', '.join(forgotten_tasks[:3])}")
        
        if stale_list:
            suggestions.append(f"🎯 **Missions sans activité récente** : {', '.join(stale_list[:3])}")
        
        if pending_docs.data:
            suggestions.append(f"📄 **Documents en brouillon** : {len(pending_docs.data)} document(s) à finaliser")
        
        if high_value_opps:
            total_value = sum(o.get("estimated_value", 0) for o in high_value_opps)
            suggestions.append(f"💰 **Opportunités à suivre** : {len(high_value_opps)} opportunité(s) - {total_value:,.0f} CFA potentiel")
        
        if not suggestions:
            suggestions = ["✅ Rien d'urgent à signaler. Bonne journée !"]
        
        # Construire le message
        message = f"""🔔 **Rappels intelligents - {datetime.now().strftime('%A %d %B %Y')}**

{chr(10).join(suggestions)}

---

💡 **Une action aujourd'hui ?** 
Réponds-moi directement ou clique sur une suggestion pour que je t'aide.
"""
        
        # Envoyer notification push
        push_sent = False
        try:
            send_notification_sync({
                "title": "🔔 Rappels intelligents",
                "body": suggestions[0][:50],
                "url": "/chat",
                "type": "task",
                "requireInteraction": False
            })
            push_sent = True
            logger.info("🔔 Notification push rappels intelligents envoyée")
        except Exception as e:
            logger.error(f"Erreur envoi push rappels: {e}")
        
        return {
            "success": True,
            "message": "Rappels intelligents envoyés",
            "suggestions": suggestions,
            "stats": {
                "forgotten_tasks": len(forgotten_tasks),
                "stale_missions": len(stale_list),
                "pending_docs": len(pending_docs.data),
                "high_value_opps": len(high_value_opps)
            },
            "push_sent": push_sent
        }
        
    except Exception as e:
        logger.error(f"Erreur rappels intelligents: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/proactive/test-smart-reminders")
async def test_smart_reminders():
    """Endpoint de test pour les rappels intelligents"""
    return await smart_reminders()



# =====================================================
# GOOGLE DRIVE - SAUVEGARDE AUTOMATIQUE
# =====================================================

import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
import io

GOOGLE_DRIVE_SERVICE_ACCOUNT_INFO = os.environ.get("GOOGLE_DRIVE_SERVICE_ACCOUNT", None)
GOOGLE_DRIVE_FOLDER_ID = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "root")

def get_drive_service():
    """Initialise le service Google Drive"""
    if not GOOGLE_DRIVE_SERVICE_ACCOUNT_INFO:
        logger.warning("⚠️ GOOGLE_DRIVE_SERVICE_ACCOUNT non configuré")
        return None
    
    try:
        service_account_info = json.loads(GOOGLE_DRIVE_SERVICE_ACCOUNT_INFO)
        creds = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=['https://www.googleapis.com/auth/drive']
        )
        service = build('drive', 'v3', credentials=creds)
        logger.info("✅ Google Drive service initialisé")
        return service
    except Exception as e:
        logger.error(f"❌ Erreur auth Google Drive: {e}")
        return None

@app.post("/api/drive/backup-document")
async def backup_document_to_drive(request: Dict[str, Any]):
    """Sauvegarde un document dans Google Drive"""
    service = get_drive_service()
    if not service:
        return {"success": False, "error": "Google Drive non configuré"}
    
    document_id = request.get("document_id")
    if not document_id:
        return {"success": False, "error": "document_id requis"}
    
    try:
        # Récupérer le document depuis Supabase
        doc = supabase.table("documents").select("*").eq("id", document_id).execute()
        
        if not doc.data:
            return {"success": False, "error": "Document non trouvé"}
        
        doc = doc.data[0]
        
        # Créer le contenu du fichier
        content = f"""Document: {doc['name']}
Type: {doc['type']}
Statut: {doc['status']}
Date d'échéance: {doc.get('due_date', 'Non définie')}
Notes: {doc.get('notes', 'Aucune')}

URL originale: {doc.get('url', 'Non renseignée')}
Fichier: {doc.get('file_url', 'Non renseigné')}

--- Exporté depuis Sovereign le {datetime.now().strftime('%d/%m/%Y à %H:%M')} ---
"""
        
        # Créer le fichier dans Drive
        file_metadata = {
            'name': f"{doc['name']}.txt",
            'parents': [GOOGLE_DRIVE_FOLDER_ID]
        }
        
        media = MediaIoBaseUpload(
            io.BytesIO(content.encode('utf-8')),
            mimetype='text/plain',
            resumable=True
        )
        
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()
        
        # Mettre à jour le document avec le lien Drive
        supabase.table("documents").update({
            "drive_backup_id": file.get('id'),
            "drive_link": file.get('webViewLink'),
            "backed_up_at": datetime.now().isoformat()
        }).eq("id", document_id).execute()
        
        logger.info(f"📁 Document {doc['name']} sauvegardé dans Google Drive")
        
        return {
            "success": True,
            "message": "Document sauvegardé dans Google Drive",
            "drive_link": file.get('webViewLink'),
            "drive_id": file.get('id')
        }
        
    except Exception as e:
        logger.error(f"❌ Erreur backup Drive: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/drive/backup-all-documents")
async def backup_all_documents_to_drive():
    """Sauvegarde tous les documents non encore sauvegardés"""
    if not supabase:
        return {"success": False, "error": "Supabase non configuré"}
    
    try:
        # Récupérer les documents non sauvegardés
        docs = supabase.table("documents").select("*").is_("drive_backup_id", "null").execute()
        
        results = []
        for doc in docs.data:
            result = await backup_document_to_drive({"document_id": doc["id"]})
            results.append({
                "id": doc["id"],
                "name": doc["name"],
                "success": result.get("success", False),
                "drive_link": result.get("drive_link")
            })
        
        backed_up = len([r for r in results if r["success"]])
        
        return {
            "success": True,
            "message": f"{backed_up} document(s) sauvegardé(s) sur {len(results)}",
            "results": results
        }
        
    except Exception as e:
        logger.error(f"❌ Erreur backup all: {e}")
        return {"success": False, "error": str(e)}


