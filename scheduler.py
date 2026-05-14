import requests
import time
import os
from datetime import datetime

BACKEND_URL = os.environ.get("BACKEND_URL", "https://sovereign-bridge.onrender.com")

# Suivi des envois pour éviter les doublons dans la même session
morning_sent_today = False
last_reminder_date = None

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

def run_hourly_checks():
    """Exécutions horaires (au lieu de toutes les 5 minutes)"""
    current_minute = datetime.now().minute
    
    # Exécuter uniquement à la minute 0 de chaque heure
    if current_minute == 0:
        send_morning_notification()
        run_all_reminders()

if __name__ == "__main__":
    print(f"🚀 Scheduler Sovereign démarré - {datetime.now()}")
    print(f"📡 Backend: {BACKEND_URL}")
    print(f"⏰ Vérification toutes les minutes (exécution à la minute 0 de chaque heure)")
    
    last_minute = -1
    
    while True:
        current_minute = datetime.now().minute
        
        # Exécuter une fois par minute (pour être réactif) mais les fonctions internes gèrent les doublons
        if current_minute != last_minute:
            run_hourly_checks()
            last_minute = current_minute
        
        time.sleep(60)  # Vérifier toutes les minutes
