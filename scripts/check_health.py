#!/usr/bin/env python3
"""
Cognitia Infrastructure Health Check
Runs on the GPU server to verify all components are active and responding.
"""

import sys
import socket
import requests
import time

def check_port(host, port, name):
    try:
        with socket.create_connection((host, port), timeout=2):
            print(f"✅ {name} (TCP {port}): OPEN")
            return True
    except (socket.timeout, ConnectionRefusedError):
        print(f"❌ {name} (TCP {port}): CLOSED/UNREACHABLE")
        return False
    except Exception as e:
        print(f"❌ {name} (TCP {port}): ERROR - {e}")
        return False

def check_http(url, name):
    try:
        response = requests.get(url, timeout=2)
        if response.status_code == 200:
            print(f"✅ {name} (HTTP): OK ({response.status_code})")
            return True
        else:
            print(f"⚠️ {name} (HTTP): WARNING (Status {response.status_code})")
            return True
    except Exception as e:
        print(f"❌ {name} (HTTP): FAILED - {e}")
        return False

def main():
    print("=== Cognitia Infrastructure Health Check ===\n")
    
    all_good = True
    
    # 1. Check Ollama
    if not check_port("localhost", 11434, "Ollama Port"): all_good = False
    if not check_http("http://localhost:11434/api/tags", "Ollama API"): all_good = False
    
    # 2. Check RVC
    if not check_port("localhost", 5050, "RVC Port"): all_good = False
    if not check_http("http://localhost:5050/models", "RVC API"): all_good = False
    
    # 3. Check Cognitia Main Server
    if not check_port("127.0.0.1", 5555, "Cognitia Server"): all_good = False
    
    print("\n" + "="*40)
    if all_good:
        print("🚀 SYSTEM STATUS: OPERATIONAL")
        print("You can now connect clients to port 5555.")
    else:
        print("⚠️ SYSTEM STATUS: DEGRADED")
        print("Check the logs in /tmp/cognitia_logs/")
    print("="*40)

if __name__ == "__main__":
    main()
