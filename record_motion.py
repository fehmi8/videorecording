import cv2
import time
import os
import threading
import shutil
from datetime import datetime
from flask import Flask, render_template_string
from flask_httpauth import HTTPBasicAuth
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- CONFIGURATION ---
PASSWORD = os.getenv("CAMERA_PASSWORD", "default_fallback_change_me")
WEBSITE_PORT = 5000
DEVICE_INDEX = 0
MIN_DURATION = 1.0
MOTION_THRESHOLD = 5000
IDLE_TIMEOUT = 2.0

# --- GLOBAL STATE ---
state = {
    "is_recording": False,
    "current_filename": "None",
    "total_recordings": 0,
    "last_motion": "Never",
    "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
}
lock = threading.Lock()
last_frame = None

app = Flask(__name__)
auth = HTTPBasicAuth()

@auth.verify_password
def verify_password(username, password):
    return password == PASSWORD

def gen_frames():
    global last_frame
    while True:
        with lock:
            if last_frame is None:
                continue
            ret, buffer = cv2.imencode('.jpg', last_frame)
            frame_bytes = buffer.tobytes()
        
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        time.sleep(0.1)  # Limit stream to ~10 FPS to save bandwidth

@app.route('/video_feed')
@auth.login_required
def video_feed():
    return app.response_class(gen_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
@auth.login_required
def index():
    # Get disk space info
    total, used, free = shutil.disk_usage("/")
    free_gb = free // (2**30)
    
    html = """
    <html>
    <head>
        <title>Jetson Camera Monitor</title>
        <style>
            body { font-family: sans-serif; background: #121212; color: #e0e0e0; text-align: center; padding: 20px; }
            .container { display: flex; flex-wrap: wrap; justify-content: center; gap: 20px; }
            .card { background: #1e1e1e; border-radius: 10px; padding: 20px; min-width: 300px; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }
            .video-card { background: #000; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 8px rgba(0,0,0,0.5); border: 2px solid #333; }
            .status { font-size: 1.5em; color: #ff5252; margin-bottom: 15px; }
            .status.active { color: #4caf50; }
            .info { margin: 8px 0; font-size: 1.1em; text-align: left; }
            .highlight { color: #bb86fc; font-weight: bold; }
            img { max-width: 100%; height: auto; display: block; }
        </style>
    </head>
    <body>
        <h1>Jetson Nano Cam Live</h1>
        <div class="container">
            <div class="video-card">
                <img src="/video_feed" width="640">
            </div>
            <div class="card">
                <div class="status {{ 'active' if state.is_recording else '' }}">
                    {{ '● RECORDING' if state.is_recording else '○ MONITORING' }}
                </div>
                <div class="info">Current File: <span class="highlight">{{ state.current_filename }}</span></div>
                <div class="info">Last Motion: <span class="highlight">{{ state.last_motion }}</span></div>
                <div class="info">Total Clips: <span class="highlight">{{ state.total_recordings }}</span></div>
                <hr style="border: 0; border-top: 1px solid #333;">
                <div class="info">Free Disk Space: <span class="highlight">{{ free_gb }} GB</span></div>
                <div class="info">System Started: {{ state.start_time }}</div>
            </div>
        </div>
        <p style="color: #666; font-size: 0.8em; margin-top: 20px;">Stream and stats update in real-time</p>
    </body>
    </html>
    """
    return render_template_string(html, state=state, free_gb=free_gb)

def run_camera():
    global state, last_frame
    cap = cv2.VideoCapture(DEVICE_INDEX, cv2.CAP_V4L2)
    if not cap.isOpened():
        print("Error: Could not open camera")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    ret, frame = cap.read()
    if not ret:
        cap.release()
        return

    height, width, _ = frame.shape
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    fourcc = cv2.VideoWriter_fourcc(*'avc1')
    
    avg_frame = None
    out = None
    recording_start_time = 0
    last_motion_time = 0
    current_filename = ""

    print("Motion detection engine started...")

    while True:
        ret, frame = cap.read()
        if not ret: break

        # Update the global frame for the web stream
        with lock:
            last_frame = frame.copy()

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if avg_frame is None:
            avg_frame = gray.copy().astype("float")
            continue

        cv2.accumulateWeighted(gray, avg_frame, 0.5)
        frame_delta = cv2.absdiff(gray, cv2.convertScaleAbs(avg_frame))
        thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)
        
        has_motion = cv2.countNonZero(thresh) > MOTION_THRESHOLD
        current_time = time.time()

        if has_motion:
            last_motion_time = current_time
            state["last_motion"] = datetime.now().strftime("%H:%M:%S")
            if not state["is_recording"]:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                current_filename = f"motion_{timestamp}.mp4"
                out = cv2.VideoWriter(current_filename, fourcc, fps, (width, height))
                
                state["is_recording"] = True
                state["current_filename"] = current_filename
                recording_start_time = current_time
                print(f"Motion! Saving to {current_filename}")

        if state["is_recording"]:
            out.write(frame)
            if (current_time - last_motion_time) > IDLE_TIMEOUT:
                out.release()
                state["is_recording"] = False
                duration = current_time - recording_start_time
                
                if duration < MIN_DURATION:
                    if os.path.exists(current_filename):
                        os.remove(current_filename)
                    state["current_filename"] = "None (Deleted: <1s)"
                else:
                    state["total_recordings"] += 1
                    state["current_filename"] = "None (Idle)"
                    print(f"Saved {current_filename}")

    cap.release()

# --- START CAMERA THREAD AUTOMATICALLY ---
# We start this globally so it runs whether we use 'python3' or 'gunicorn'
cam_thread = threading.Thread(target=run_camera, daemon=True)
cam_thread.start()

if __name__ == "__main__":
    # Start Web Server (Development mode)
    print(f"Web server starting on port {WEBSITE_PORT}...")
    print(f"Login: any username | Password: {PASSWORD}")
    app.run(host='0.0.0.0', port=WEBSITE_PORT, debug=False, use_reloader=False)
