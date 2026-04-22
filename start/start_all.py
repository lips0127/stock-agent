#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import time
import signal
import threading

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
processes = []

def log(msg):
    print(f"[System] {msg}")

def run_process(name, cmd, cwd=None):
    log(f"Starting {name}...")
    try:
        if cwd:
            proc = subprocess.Popen(cmd, shell=True, cwd=cwd)
        else:
            proc = subprocess.Popen(cmd, shell=True)
        processes.append((name, proc))
        log(f"{name} started (PID: {proc.pid})")
        return True
    except Exception as e:
        log(f"ERROR starting {name}: {e}")
        return False

def check_java():
    try:
        result = subprocess.run("java -version", shell=True, capture_output=True, text=True)
        return result.returncode == 0
    except:
        return False

def check_python():
    try:
        result = subprocess.run("python --version", shell=True, capture_output=True, text=True)
        return result.returncode == 0
    except:
        return False

def check_java_jar():
    jar_path = os.path.join(PROJECT_ROOT, "stock-backend", "target", "stock-backend-0.0.1-SNAPSHOT.jar")
    return os.path.exists(jar_path)

def build_java():
    log("Building Java backend...")
    build_script = os.path.join(PROJECT_ROOT, "build", "build_java.bat")
    result = subprocess.run(build_script, shell=True, cwd=PROJECT_ROOT)
    return result.returncode == 0

def get_python_cmd():
    venv_paths = ["venv_new", "venv"]
    for venv in venv_paths:
        activate_path = os.path.join(PROJECT_ROOT, venv, "Scripts", "activate.bat")
        python_path = os.path.join(PROJECT_ROOT, venv, "Scripts", "python.exe")
        if os.path.exists(python_path):
            return f'cd /d "{PROJECT_ROOT}" && call "{venv}\\Scripts\\activate.bat" && python -m backend.api.app'
    return f'cd /d "{PROJECT_ROOT}" && python -m backend.api.app'

def start_java():
    jar_path = os.path.join(PROJECT_ROOT, "stock-backend", "target", "stock-backend-0.0.1-SNAPSHOT.jar")
    cmd = f'cd /d "{PROJECT_ROOT}\\stock-backend" && java -jar "{jar_path}" --spring.profiles.active=dev'
    return run_process("Java Backend", cmd)

def start_python():
    cmd = get_python_cmd()
    return run_process("Python Backend", cmd, cwd=PROJECT_ROOT)

def start_frontend():
    cmd = f'cd /d "{PROJECT_ROOT}\\frontend" && pnpm dev:h5'
    return run_process("Frontend", cmd)

def cleanup(signum, frame):
    log("\nStopping all processes...")
    for name, proc in processes:
        try:
            log(f"Stopping {name} (PID: {proc.pid})...")
            proc.terminate()
            proc.wait(timeout=3)
        except:
            try:
                proc.kill()
            except:
                pass
    log("All processes stopped.")
    sys.exit(0)

def print_info():
    print("\n" + "="*60)
    print("  Stock Agent System - Running")
    print("="*60)
    print("\nService Ports:")
    print("  - Java Backend:    http://localhost:8080")
    print("  - Python Backend:  http://localhost:5000")
    print("  - Frontend H5:     http://localhost:10086")
    print("\nSwagger UI:")
    print("  - http://localhost:8080/swagger-ui.html")
    print("\nPress Ctrl+C to stop all services\n")

def main():
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    print("="*60)
    print("  Stock Agent System - Startup")
    print("="*60)
    print()

    # Check prerequisites
    log("Checking prerequisites...")

    if not check_java():
        log("ERROR: Java not found!")
        return 1

    if not check_python():
        log("ERROR: Python not found!")
        return 1

    # Check Java JAR
    if not check_java_jar():
        log("Java JAR not found, building...")
        if not build_java():
            log("ERROR: Failed to build Java backend!")
            return 1

    # Start services
    print()

    success = True
    success &= start_java()
    time.sleep(2)  # Give Java a head start
    success &= start_python()
    time.sleep(1)
    success &= start_frontend()

    if success:
        print_info()

        # Monitor processes
        try:
            while True:
                time.sleep(1)
                # Check if any process died
                for name, proc in processes:
                    if proc.poll() is not None:
                        log(f"WARNING: {name} has stopped (exit code: {proc.returncode})")
        except KeyboardInterrupt:
            cleanup(None, None)
    else:
        log("ERROR: Some services failed to start!")
        cleanup(None, None)
        return 1

if __name__ == "__main__":
    main()
