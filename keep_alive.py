# keep_alive.py
import requests
import time
import os
import sys
from datetime import datetime

# Configuration
BACKEND_URL = os.environ.get("BACKEND_URL", "https://sovereign-bridge.onrender.com")
PING_INTERVAL = 300  # 5 minutes (Render free tier timeout is 15 minutes)

# Headers pour ressembler à un vrai navigateur
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (Safari/537.36)",
    "Accept": "application/json",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Cache-Control": "no-cache"
}

def log_message(message: str, status: str = "INFO"):
    """Affiche un message avec timestamp et couleur dans les logs"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if status == "ERROR":
        print(f"[{timestamp}] ❌ {message}")
    elif status == "SUCCESS":
        print(f"[{timestamp}] ✅ {message}")
    elif status == "WARNING":
        print(f"[{timestamp}] ⚠️ {message}")
    else:
        print(f"[{timestamp}] 🔄 {message}")
    sys.stdout.flush()  # Force l'écriture immédiate dans les logs

def ping_backend() -> bool:
    """Envoie un ping au backend pour le maintenir actif"""
    endpoints = [
        "/ping",      # Endpoint rapide (prioritaire)
        "/health",    # Fallback
        "/"           # Fallback final
    ]
    
    for endpoint in endpoints:
        try:
            url = f"{BACKEND_URL}{endpoint}"
            log_message(f"Ping vers {endpoint}...", "INFO")
            
            response = requests.get(
                url, 
                timeout=10, 
                headers=HEADERS
            )
            
            if response.status_code in [200, 204]:
                log_message(f"Ping réussi sur {endpoint} (status: {response.status_code})", "SUCCESS")
                return True
            else:
                log_message(f"Ping retourne {response.status_code} sur {endpoint}", "WARNING")
                
        except requests.exceptions.Timeout:
            log_message(f"Timeout sur {endpoint}", "WARNING")
        except requests.exceptions.ConnectionError:
            log_message(f"Erreur connexion sur {endpoint}", "WARNING")
        except Exception as e:
            log_message(f"Erreur sur {endpoint}: {e}", "WARNING")
    
    return False

def run_keep_alive():
    """Boucle principale de keep-alive"""
    log_message(f"🚀 Keep-alive démarré", "INFO")
    log_message(f"📡 Backend cible: {BACKEND_URL}", "INFO")
    log_message(f"⏱️  Intervalle: {PING_INTERVAL} secondes ({PING_INTERVAL//60} minutes)", "INFO")
    log_message(f"📅 Démarrage: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "INFO")
    print("-" * 60)
    
    # Compteur pour les stats
    success_count = 0
    fail_count = 0
    total_pings = 0
    
    while True:
        try:
            total_pings += 1
            success = ping_backend()
            
            if success:
                success_count += 1
            else:
                fail_count += 1
            
            # Afficher les stats toutes les 10 pings (~50 minutes)
            if total_pings % 10 == 0:
                success_rate = (success_count / total_pings) * 100
                log_message(f"📊 STATS - {total_pings} pings, {success_count} succès ({success_rate:.1f}%), {fail_count} échecs", "INFO")
            
            time.sleep(PING_INTERVAL)
            
        except KeyboardInterrupt:
            log_message("Arrêt demandé par l'utilisateur", "WARNING")
            break
        except Exception as e:
            log_message(f"Erreur dans la boucle principale: {e}", "ERROR")
            time.sleep(60)  # Attendre 1 minute avant de réessayer

def run_once():
    """Exécute un seul ping (pour les cron jobs)"""
    log_message("🏓 Exécution unique...", "INFO")
    success = ping_backend()
    if success:
        log_message("✅ Ping unique réussi", "SUCCESS")
    else:
        log_message("❌ Ping unique échoué", "ERROR")
    return success

if __name__ == "__main__":
    # Si l'argument "once" est passé, exécuter un seul ping
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        success = run_once()
        sys.exit(0 if success else 1)
    else:
        run_keep_alive()
