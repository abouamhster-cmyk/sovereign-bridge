import requests
import time
import os
from datetime import datetime

BACKEND_URL = os.environ.get("BACKEND_URL", "https://sovereign-bridge.onrender.com")

# Suivi des envois pour éviter les doublons dans la même session
morning_sent_today = False
last_reminder_date = None
last_evening_comms_date = None

def send_morning_notification():
    """Envoie la notification matinale UNE SEULE FOIS par jour"""
    global morning_sent_today
    current_hour = datetime.now().hour
    
    # Entre 7h et 9h, mais pas déjà envoyé aujourd'hui
    if 7 <= current_hour <= 9 and not morning_sent_today:
        try:
            response = requests.post(f"{BACKEND_URL}/api/morning-notification", timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    morning_sent_today = True
                    print(f"[{datetime.now()}] 🌅 Notification matinale envoyée: {data.get('message')}")
                else:
                    print(f"[{datetime.now()}] ⚠️ Notification matinale non envoyée (déjà faite?)")
        except Exception as e:
            print(f"[{datetime.now()}] ❌ Erreur notification matinale: {e}")
    
    # Réinitialiser le flag après 9h
    if current_hour > 9:
        morning_sent_today = False

def send_morning_brief():
    """Envoie le brief matinal complet (avec tâches et communications)"""
    current_hour = datetime.now().hour
    
    # Entre 7h et 9h
    if 7 <= current_hour <= 9:
        try:
            response = requests.post(f"{BACKEND_URL}/api/proactive/morning-brief", timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    stats = data.get("stats", {})
                    print(f"[{datetime.now()}] 📋 Brief matinal envoyé: {stats.get('tasks_today', 0)} tâches, {stats.get('pending_comms', 0)} messages en attente")
                else:
                    print(f"[{datetime.now()}] ⚠️ Brief matinal non envoyé")
        except Exception as e:
            print(f"[{datetime.now()}] ❌ Erreur brief matinal: {e}")

def send_evening_comms_reminder():
    """Envoie le rappel des communications non traitées le soir (19h-21h)"""
    global last_evening_comms_date
    current_hour = datetime.now().hour
    today = datetime.now().date()
    
    # Ne pas exécuter plus d'une fois par jour
    if last_evening_comms_date == today:
        return
    
    # Entre 19h et 21h
    if 19 <= current_hour <= 21:
        try:
            response = requests.post(f"{BACKEND_URL}/api/proactive/evening-comms-reminder", timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("sent"):
                    last_evening_comms_date = today
                    stats = data.get("stats", {})
                    print(f"[{datetime.now()}] 🌙 Rappel communications soir envoyé: {stats.get('total_pending', 0)} messages, {stats.get('urgent_count', 0)} urgents")
                else:
                    print(f"[{datetime.now()}] 🌙 Rappel communications déjà envoyé aujourd'hui")
        except Exception as e:
            print(f"[{datetime.now()}] ❌ Erreur rappel communications soir: {e}")

def run_all_reminders():
    """Exécute tous les rappels UNE SEULE FOIS par jour"""
    global last_reminder_date
    today = datetime.now().date()
    
    # Ne pas exécuter plus d'une fois par jour
    if last_reminder_date == today:
        return
    
    endpoints = [
        ("/api/check-task-reminders", "Tâches"),
        ("/api/mission-reminders", "Missions"),
        ("/api/document-reminders", "Documents"),
        ("/api/celebration-reminder", "Victoires"),
    ]
    
    any_sent = False
    for endpoint, name in endpoints:
        try:
            response = requests.post(f"{BACKEND_URL}{endpoint}", timeout=30)
            if response.status_code == 200:
                data = response.json()
                count = data.get("count", data.get("sent", 0))
                if count > 0:
                    print(f"[{datetime.now()}] 📨 {name}: {count} notification(s) envoyée(s)")
                    any_sent = True
                else:
                    print(f"[{datetime.now()}] 📨 {name}: aucune notification (déjà envoyée)")
        except Exception as e:
            print(f"[{datetime.now()}] ❌ Erreur {name}: {e}")
    
    if any_sent:
        last_reminder_date = today
        print(f"[{datetime.now()}] ✅ Rappels du {today} terminés")

def send_morning_checkin():
    """Envoie le check-in matinal proactif (une fois par jour entre 7h et 9h)"""
    current_hour = datetime.now().hour
    
    # Entre 7h et 9h seulement
    if 7 <= current_hour <= 9:
        try:
            response = requests.post(f"{BACKEND_URL}/api/morning-checkin", timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("sent"):
                    print(f"[{datetime.now()}] 🌅 Check-in matinal envoyé: {data.get('stats', {})}")
                else:
                    print(f"[{datetime.now()}] 🌅 Check-in matinal déjà envoyé aujourd'hui")
        except Exception as e:
            print(f"[{datetime.now()}] ❌ Erreur check-in matinal: {e}")

def send_intelligent_notifications():
    """Envoie des notifications contextuelles intelligentes"""
    try:
        response = requests.post(f"{BACKEND_URL}/api/notifications/intelligent-check", timeout=30)
        if response.status_code == 200:
            data = response.json()
            if data.get("notifications_sent", 0) > 0:
                print(f"[{datetime.now()}] 🤖 {data['notifications_sent']} notification(s) intelligente(s) envoyée(s)")
            else:
                print(f"[{datetime.now()}] 🤖 Aucune notification intelligente nécessaire")
    except Exception as e:
        print(f"[{datetime.now()}] ❌ Erreur notifications intelligentes: {e}")

def run_hourly_checks():
    """Exécutions horaires (à la minute 0 de chaque heure)"""
    current_minute = datetime.now().minute
    current_hour = datetime.now().hour
    
    # Exécuter à la minute 0 de chaque heure
    if current_minute == 0:
        # ========== MATIN (7h-9h) ==========
        send_morning_checkin()
        send_morning_brief()      # ← Brief matinal complet avec communications
        send_morning_notification()
        
        # ========== RAPPELS QUOTIDIENS (une fois par jour) ==========
        run_all_reminders()
        
        # ========== SOIR (19h-21h) ==========
        send_evening_comms_reminder()  # ← Rappel communications du soir
        
        # ========== NOTIFICATIONS INTELLIGENTES (toutes les 2 heures) ==========
        if current_hour % 2 == 0:
            send_intelligent_notifications()

def run_continuous():
    """Boucle continue avec vérification toutes les minutes"""
    print(f"🚀 Scheduler Sovereign démarré - {datetime.now()}")
    print(f"📡 Backend: {BACKEND_URL}")
    print(f"⏰ Vérification toutes les minutes (exécution à la minute 0 de chaque heure)")
    print(f"📋 Notifications programmées :")
    print(f"   • 7h-9h : Brief matinal + Check-in + Notifications")
    print(f"   • 19h-21h : Rappel communications du soir")
    print(f"   • Heures paires : Notifications intelligentes")
    print(f"   • Une fois par jour : Rappels tâches, missions, documents, victoires")
    
    last_minute = -1
    
    while True:
        current_minute = datetime.now().minute
        
        # Exécuter une fois par minute
        if current_minute != last_minute:
            run_hourly_checks()
            last_minute = current_minute
        
        time.sleep(60)  # Vérifier toutes les minutes

if __name__ == "__main__":
    run_continuous()
