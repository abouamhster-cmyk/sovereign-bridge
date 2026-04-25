import requests
import time
import os
from datetime import datetime

BACKEND_URL = "https://sovereign-bridge.onrender.com"

def check_and_send_reminders():
    """Vérifie les tâches et envoie les rappels"""
    try:
        response = requests.get(f"{BACKEND_URL}/api/check-reminders", timeout=30)
        if response.status_code == 200:
            data = response.json()
            if data.get("count", 0) > 0:
                print(f"[{datetime.now()}] 📨 {data['count']} rappels envoyés")
        else:
            print(f"[{datetime.now()}] ❌ Erreur: {response.status_code}")
    except Exception as e:
        print(f"[{datetime.now()}] ❌ Exception: {e}")

if __name__ == "__main__":
    print(f"🚀 Scheduler démarré - {datetime.now()}")
    
    while True:
        check_and_send_reminders()
        time.sleep(300)  # Toutes les 5 minutes
