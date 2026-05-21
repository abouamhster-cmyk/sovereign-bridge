# keep_alive.py
import requests
import time
import os
from datetime import datetime

BACKEND_URL = os.environ.get("BACKEND_URL", "https://sovereign-bridge.onrender.com")
PING_INTERVAL = 300  # 5 minutes (Render free tier timeout is 15 minutes)

def ping_backend():
    """Envoie un ping au backend pour le maintenir actif"""
    try:
        # Ping sur l'endpoint health (le plus léger)
        response = requests.get(f"{BACKEND_URL}/health", timeout=10)
        if response.status_code == 200:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Ping réussi")
            return True
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Ping retourne {response.status_code}")
            return False
    except requests.exceptions.Timeout:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Timeout")
        return False
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Erreur: {e}")
        return False

def keep_alive():
    """Boucle de keep-alive"""
    print(f"🔄 Keep-alive démarré - {BACKEND_URL}")
    print(f"⏱️ Ping toutes les {PING_INTERVAL} secondes")
    
    while True:
        ping_backend()
        time.sleep(PING_INTERVAL)

if __name__ == "__main__":
    keep_alive()
