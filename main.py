import subprocess
import sys
import time
import os

def main():
    print("Starting Skill-Gap Builder Services...\n")
    
    # Start Flask Backend
    print("[+] Starting Flask Backend (Port 5000)...")
    flask_process = subprocess.Popen(
        [sys.executable, "backend.py"],
        stdout=sys.stdout,
        stderr=sys.stderr
    )

    # Wait a couple seconds to ensure backend is up
    time.sleep(2)
    
    # Start Streamlit Frontend
    print("[+] Starting Streamlit Frontend (Port 8501)...")
    streamlit_process = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py"],
        stdout=sys.stdout,
        stderr=sys.stderr
    )

    print("\n[OK] Both services are running! Press Ctrl+C to shut down both.")

    try:
        # Wait for both processes to finish
        flask_process.wait()
        streamlit_process.wait()
    except KeyboardInterrupt:
        print("\n\n[STOP] Shutting down services...")
        flask_process.terminate()
        streamlit_process.terminate()
        flask_process.wait()
        streamlit_process.wait()
        print("Done.")

if __name__ == "__main__":
    main()
