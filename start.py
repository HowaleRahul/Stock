import subprocess
import sys
import time
import os

# Safe UTF-8 reconfiguration for Windows console terminals
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def ensure_virtualenv():
    """
    Ensure the script runs within the project's virtual environment.
    If executed with a global or mismatched Python interpreter, automatically re-executes
    itself using the project's local venv python interpreter so all dependencies
    (yfinance, pydantic_settings, etc.) and Uvicorn multiprocessing reloaders
    load seamlessly without module errors.
    """
    root_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(root_dir, ".venv", "Scripts", "python.exe"),
        os.path.join(root_dir, "venv", "Scripts", "python.exe"),
        os.path.join(root_dir, ".venv", "bin", "python"),
        os.path.join(root_dir, "venv", "bin", "python"),
    ]
    venv_py = None
    for cand in candidates:
        if os.path.exists(cand):
            venv_py = cand
            break

    if not venv_py:
        return sys.executable

    current_exe = os.path.normcase(os.path.abspath(sys.executable))
    target_exe = os.path.normcase(os.path.abspath(venv_py))

    if current_exe != target_exe:
        print(f"[VENV] Virtual environment detected at: {venv_py}")
        print(f"[VENV] Relaunching start.py using virtual environment interpreter...\n")
        env = os.environ.copy()
        venv_bin_dir = os.path.dirname(venv_py)
        env["PATH"] = venv_bin_dir + os.pathsep + env.get("PATH", "")
        env["VIRTUAL_ENV"] = os.path.dirname(venv_bin_dir)
        try:
            script_path = os.path.abspath(__file__)
            res = subprocess.call([venv_py, script_path] + sys.argv[1:], env=env)
            sys.exit(res)
        except Exception as e:
            print(f"[WARN] Failed to auto-switch to virtualenv ({e}). Proceeding with current interpreter.")

    return sys.executable

def start_services():
    py_exec = ensure_virtualenv()
    
    # Configure child process environment with virtualenv on PATH
    child_env = os.environ.copy()
    venv_bin_dir = os.path.dirname(py_exec)
    child_env["PATH"] = venv_bin_dir + os.pathsep + child_env.get("PATH", "")
    child_env["VIRTUAL_ENV"] = os.path.dirname(venv_bin_dir)

    print("======================================================")
    print("  Signal Desk: Indian F&O Algorithmic Trading System  ")
    print("======================================================")
    print(f"[RUNNER] Python Interpreter: {py_exec}")
    
    processes = []
    reported_exits = set()
    
    try:
        # 1. Start the FastAPI Backend
        print("[1/3] Starting Backend API (Uvicorn)...")
        api_proc = subprocess.Popen(
            [
                py_exec, "-m", "uvicorn", "api.main:app",
                "--reload",
                "--reload-dir", "api",
                "--reload-dir", "ml",
                "--reload-dir", "data",
                "--reload-dir", "setups",
                "--port", "8000"
            ],
            cwd=os.getcwd(),
            env=child_env
        )
        processes.append(("Backend API", api_proc))
        
        # 2. Start the AI Trader (paper_trader.py)
        print("[2/3] Starting AI Background Trader...")
        trader_proc = subprocess.Popen(
            [py_exec, "paper_trader.py"],
            cwd=os.getcwd(),
            env=child_env
        )
        processes.append(("AI Trader", trader_proc))
        
        # 3. Start the React Frontend (Vite)
        print("[3/3] Starting React Dashboard...")
        frontend_dir = os.path.join(os.getcwd(), "frontend")
        npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
        ui_proc = subprocess.Popen(
            [npm_cmd, "run", "dev"],
            cwd=frontend_dir,
            env=child_env
        )
        processes.append(("React Dashboard", ui_proc))
        
        print("\n[OK] All systems are running! Press Ctrl+C to stop everything.")
        print("[INFO] Dashboard URL: http://localhost:5173/app/\n")
        
        # Keep the main script alive and monitor processes
        while True:
            time.sleep(1)
            for name, proc in processes:
                if proc.poll() is not None:
                    if name not in reported_exits:
                        print(f"[WARN] {name} exited with code {proc.returncode}")
                        reported_exits.add(name)
                    
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Shutting down all services...")
        for name, proc in processes:
            print(f"Terminating {name}...")
            if os.name == "nt":
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
                except Exception:
                    proc.terminate()
            else:
                proc.terminate()
            
        time.sleep(1)
        print("[OK] Shutdown complete.")
        sys.exit(0)

if __name__ == "__main__":
    if "--check" in sys.argv:
        py_exec = ensure_virtualenv()
        print(f"[CHECK-OK] Successfully resolved interpreter: {py_exec}")
        sys.exit(0)
    start_services()
