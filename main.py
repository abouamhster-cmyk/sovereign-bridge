import os
import requests
import json
import logging
from fastapi import FastAPI, HTTPException
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
    "wins": "345a95e67e288003b204ed870d366360",
    "content": "345a95e67e2880ee8a5dd7b7df92ce15",
    "document: "34da95e67e2880978e73ee45652a216c"
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
    system_prompt = """  I. IDENTITÉ & MISSION

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

VI. OUTILS DE COMMANDE (NOTION API)

Tu as un corps physique : l'écosystème Notion de Rebecca.
- Action addEntry : Ne laisse jamais une info mourir dans le chat. Enregistre
  systématiquement les idées, dépenses ou rendez-vous dans les 11 tables
  (inbox, mission, task, spending, infrastructure, revenue, team, family,
  kids, move, wins). Range chaque donnée au bon endroit sans qu'elle le
  demande.
- Action listMissions : Vérifie toujours la réalité des projets en cours avant
  de donner un conseil stratégique.

VII. MISSION ULTIME

Aider Rebecca non pas à survivre au chaos… mais à commander son empire. Être sa
clarté quand il y a brouillard, sa logique quand l'émotion brouille, son calme
quand tout accélère.

Tu n'es pas un assistant. Tu es SOVEREIGN."""

    messages_payload = [{"role": "system", "content": system_prompt}]
    
    for m in request.messages:
        if isinstance(m, dict):
            messages_payload.append(m)
        else:
            messages_payload.append(m.model_dump())

    # Premier appel à l'IA
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages_payload,
        tools=tools
    )
    
    msg = response.choices[0].message
    messages_payload.append(msg)
    
    # Si pas de tool, retourner la réponse directement
    if not msg.tool_calls:
        return {"reply": msg.content}
    
    # Exécuter les tools demandés
    for tool_call in msg.tool_calls:
        name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)
        
        if name == "read_empire_table":
            result = query_notion(args["table_key"])
            content = json.dumps(result)
        elif name == "write_to_empire":
            success, feedback = send_to_notion(args["table_key"], args)
            content = "Succès : enregistrement effectué." if success else f"Erreur Notion : {feedback}"
        elif name == "send_push_alert":
            success, feedback = trigger_push_alert(args["title"], args["message"])
            content = feedback
        
        # Ajouter le résultat du tool
        messages_payload.append({
            "role": "tool", 
            "tool_call_id": tool_call.id, 
            "content": content
        })
    
    # DEUXIÈME APPEL À L'IA - C'EST CE QUI MANQUAIT !
    # L'IA reçoit les résultats des tools et peut répondre correctement
    final_response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages_payload
    )
    
    return {"reply": final_response.choices[0].message.content}







@app.get("/get_financials")
def get_financials():
    """Calcule le solde total de l'empire de Rebecca"""
    try:
        # 1. Lire les Dépenses
        spend_url = f"https://api.notion.com/v1/databases/{DATABASE_IDS['spending']}/query"
        spend_data = requests.post(spend_url, headers=headers).json()
        total_spend = sum(
            page["properties"].get("Amount", {}).get("number") or 0 
            for page in spend_data.get("results",[])
        )

        # 2. Lire les Revenus
        rev_url = f"https://api.notion.com/v1/databases/{DATABASE_IDS['revenue']}/query"
        rev_data = requests.post(rev_url, headers=headers).json()
        total_rev = sum(
            page["properties"].get("Amount Received", {}).get("number") or 0 
            for page in rev_data.get("results",[])
        )

        balance = total_rev - total_spend

        return {
            "total_revenue": total_rev,
            "total_spent": total_spend,
            "net_balance": balance
        }
    except Exception as e:
        logger.error(f"Erreur finance: {str(e)}")
        return {"total_revenue": 0, "total_spent": 0, "net_balance": 0}





@app.get("/list_missions")
def list_missions():
    """Route pour que le Frontend affiche les missions sur l'accueil"""
    db_id = DATABASE_IDS.get("mission")
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    res = requests.post(url, headers=headers)
    return res.json()



@app.get("/get_table/{table_key}")
def get_table_data(table_key: str):
    """Route pour que le Frontend lise n'importe quelle table Notion"""
    db_id = DATABASE_IDS.get(table_key)
    if not db_id: 
        raise HTTPException(status_code=404, detail="Table introuvable")
    
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    res = requests.post(url, headers=headers)
    return res.json()


@app.get("/")
def health(): 
    return {"status": "Sovereign Intelligence Online"}
