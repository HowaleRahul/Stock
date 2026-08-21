import subprocess
import sys
import time
import os

def start_services():
    print("🚀 Starting AI Algorithmic Trading System...")
    
    processes = []
    reported_exits = set()
    
    try:
        # 1. Start the FastAPI Backend
        print("[1/3] Starting Backend API (Uvicorn)...")
        api_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api.main:app", "--reload", "--port", "8000"],
            cwd=os.getcwd()
        )
        processes.append(("Backend API", api_proc))
        
        # 2. Start the AI Trader (paper_trader.py)
        print("[2/3] Starting AI Background Trader...")
        trader_proc = subprocess.Popen(
            [sys.executable, "paper_trader.py"],
            cwd=os.getcwd()
        )
        processes.append(("AI Trader", trader_proc))
        
        # 3. Start the React Frontend (Vite)
        print("[3/3] Starting React Dashboard...")
        # Use shell=True for npm on Windows
        frontend_dir = os.path.join(os.getcwd(), "frontend")
        npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
        ui_proc = subprocess.Popen(
            [npm_cmd, "run", "dev"],
            cwd=frontend_dir
        )
        processes.append(("React Dashboard", ui_proc))
        
        print("\n✅ All systems are running! Press Ctrl+C to stop everything.")
        print("🌐 Dashboard URL: http://localhost:5173\n")
        
        # Keep the main script alive and monitor processes
        while True:
            time.sleep(1)
            for name, proc in processes:
                if proc.poll() is not None:
                    if name not in reported_exits:
                        print(f"⚠️ Warning: {name} exited with code {proc.returncode}")
                        reported_exits.add(name)
                    
    except KeyboardInterrupt:
        print("\n🛑 Shutting down all services...")
        for name, proc in processes:
            print(f"Terminating {name}...")
            proc.terminate()
            
        # Give them a moment to terminate gracefully
        time.sleep(2)
        print("✅ Shutdown complete.")
        sys.exit(0)

if __name__ == "__main__":
    start_services()
