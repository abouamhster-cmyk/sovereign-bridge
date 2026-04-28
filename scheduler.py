# scheduler.py - Version complète
import requests
import time
import os
from datetime import datetime

BACKEND_URL = os.environ.get("BACKEND_URL", "https://sovereign-bridge.onrender.com")

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
                    print(f"[{datetime.now()}] 📨 {name}: {count} notification(s) envoyée(s)")
        except Exception as e:
            print(f"[{datetime.now()}] ❌ Erreur {name}: {e}")
    
    # Brief matinal uniquement le matin
    if 7 <= datetime.now().hour <= 9:
        try:
            response = requests.post(f"{BACKEND_URL}/api/morning-brief-reminder", timeout=30)
            if response.status_code == 200:
                print(f"[{datetime.now()}] 🌅 Brief matinal envoyé")
        except Exception as e:
            print(f"[{datetime.now()}] ❌ Erreur brief: {e}")

if __name__ == "__main__":
    print(f"🚀 Scheduler Sovereign démarré - {datetime.now()}")
    print(f"📡 Backend: {BACKEND_URL}")
    
    while True:
        run_all_reminders()
        time.sleep(300)  # Toutes les 5 minutes
