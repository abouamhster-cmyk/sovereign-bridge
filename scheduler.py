import requests
import time
import os
from datetime import datetime

BACKEND_URL = os.environ.get("BACKEND_URL", "https://sovereign-bridge.onrender.com")

def send_morning_notification():
    """Envoie la notification matinale (entre 7h et 9h)"""
    current_hour = datetime.now().hour
    if 7 <= current_hour <= 9:
        try:
            response = requests.post(f"{BACKEND_URL}/api/morning-notification", timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    print(f"[{datetime.now()}] 🌅 Notification matinale: {data.get('message')}")
        except Exception as e:
            print(f"[{datetime.now()}] ❌ Erreur notification matinale: {e}")

def run_all_reminders():
    """Exécute tous les types de rappels"""
    endpoints = [
        ("/api/check-task-reminders", "Tâches"),
        ("/api/mission-reminders", "Missions"),
        ("/api/document-reminders", "Documents"),
        ("/api/celebration-reminder", "Victoires"),
    ]
    
    for endpoint, name in endpoints:
        try:
            response = requests.post(f"{BACKEND_URL}{endpoint}", timeout=30)
            if response.status_code == 200:
                data = response.json()
                count = data.get("count", data.get("sent", 0))
                if count > 0:
                    print(f"[{datetime.now()}] 📨 {name}: {count} notification(s)")
        except Exception as e:
            print(f"[{datetime.now()}] ❌ Erreur {name}: {e}")

if __name__ == "__main__":
    print(f"🚀 Scheduler Sovereign démarré - {datetime.now()}")
    print(f"📡 Backend: {BACKEND_URL}")
    
    last_morning_hour = None
    
    while True:
        current_hour = datetime.now().hour
        
        # Envoyer la notification matinale une fois par heure entre 7h et 9h
        if 7 <= current_hour <= 9 and last_morning_hour != current_hour:
            send_morning_notification()
            last_morning_hour = current_hour
        elif current_hour < 7 or current_hour > 9:
            last_morning_hour = None
        
        run_all_reminders()
        time.sleep(300)  # Toutes les 5 minutes
