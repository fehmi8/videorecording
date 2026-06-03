import cv2
import time
import os
import threading
import shutil
from datetime import datetime
from flask import Flask, render_template_string, jsonify
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
    "is_monitoring": False,
    "manual_override": False, # True if user clicked START, False if user clicked STOP
    "current_filename": "None",
    "total_recordings": 0,
    "last_motion": "Never",
    "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
}
lock = threading.Lock()
state_lock = threading.Lock()
last_frame = None
camera_started = False

app = Flask(__name__)
auth = HTTPBasicAuth()

@auth.verify_password
def verify_password(username, password):
    return password == PASSWORD

def update_state(key, value):
    with state_lock:
        state[key] = value

def is_within_schedule():
    """Checks if current time is weekday 12:00-14:00."""
    now = datetime.now()
    # Weekday: 0=Monday, 6=Sunday
    if now.weekday() < 5: 
        if 12 <= now.hour < 14:
            return True
    return False

def get_current_status():
    with state_lock:
        if state["is_recording"]:
            return "RECORDING"
        if state["is_monitoring"]:
            return "MONITORING"
        return "DISABLED"

def gen_frames():
    global last_frame
    while True:
        with lock:
            if last_frame is None:
                time.sleep(0.1)
                continue
            ret, buffer = cv2.imencode('.jpg', last_frame)
            if not ret:
                continue
            frame_bytes = buffer.tobytes()
        
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        time.sleep(0.05)

@app.route('/video_feed')
@auth.login_required
def video_feed():
    return app.response_class(gen_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/stats')
@auth.login_required
def stats():
    total, used, free = shutil.disk_usage("/")
    with state_lock:
        return jsonify({
            "status": get_current_status(),
            "current_filename": state["current_filename"],
            "last_motion": state["last_motion"],
            "total_recordings": state["total_recordings"],
            "free_gb": free // (2**30)
        })

@app.route('/start')
@auth.login_required
def start_manual():
    update_state("manual_override", True)
    return jsonify({"success": True})

@app.route('/stop')
@auth.login_required
def stop_manual():
    update_state("manual_override", False)
    return jsonify({"success": True})

@app.route('/')
@auth.login_required
def index():
    html = """
    <html>
    <head>
        <title>Jetson Camera Monitor</title>
        <style>
            body { font-family: sans-serif; background: #121212; color: #e0e0e0; text-align: center; padding: 20px; }
            .container { display: flex; flex-wrap: wrap; justify-content: center; gap: 20px; }
            .card { background: #1e1e1e; border-radius: 10px; padding: 20px; min-width: 300px; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }
            .video-card { background: #000; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 8px rgba(0,0,0,0.5); border: 2px solid #333; }
            .status { font-size: 1.5em; color: #757575; margin-bottom: 15px; }
            .status.RECORDING { color: #ff5252; }
            .status.MONITORING { color: #4caf50; }
            .status.DISABLED { color: #757575; }
            .info { margin: 8px 0; font-size: 1.1em; text-align: left; }
            .highlight { color: #bb86fc; font-weight: bold; }
            .btn-container { margin-top: 20px; display: flex; gap: 10px; justify-content: center; }
            button { padding: 10px 20px; border-radius: 5px; border: none; cursor: pointer; font-weight: bold; font-size: 1em; }
            .btn-start { background: #4caf50; color: white; }
            .btn-stop { background: #f44336; color: white; }
            img { max-width: 100%; height: auto; display: block; }
        </style>
        <script>
            function updateStats() {
                fetch('/stats')
                    .then(response => response.json())
                    .then(data => {
                        const statusEl = document.getElementById('status');
                        statusEl.innerText = '● ' + data.status;
                        statusEl.className = 'status ' + data.status;
                        document.getElementById('filename').innerText = data.current_filename;
                        document.getElementById('last_motion').innerText = data.last_motion;
                        document.getElementById('total_clips').innerText = data.total_recordings;
                        document.getElementById('free_space').innerText = data.free_gb + ' GB';
                    })
                    .catch(err => console.error("Stats update failed", err));
            }
            function control(action) {
                fetch('/' + action).then(() => updateStats());
            }
            setInterval(updateStats, 2000);
        </script>
    </head>
    <body>
        <h1>Jetson Nano Cam Live</h1>
        <div class="container">
            <div class="video-card">
                <img src="/video_feed" width="640">
            </div>
            <div class="card">
                <div id="status" class="status">● DISABLED</div>
                <div class="info">Current File: <span id="filename" class="highlight">-</span></div>
                <div class="info">Last Motion: <span id="last_motion" class="highlight">-</span></div>
                <div class="info">Total Clips: <span id="total_clips" class="highlight">0</span></div>
                <hr style="border: 0; border-top: 1px solid #333;">
                <div class="info">Free Disk Space: <span id="free_space" class="highlight">-</span></div>
                <div class="info">System Started: {{ state.start_time }}</div>
                
                <div class="btn-container">
                    <button class="btn-start" onclick="control('start')">START MANUAL</button>
                    <button class="btn-stop" onclick="control('stop')">STOP MANUAL</button>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(html, state=state)

def run_camera():
    global state, last_frame
    print("Initializing camera...")
    cap = cv2.VideoCapture(DEVICE_INDEX, cv2.CAP_V4L2)
    if not cap.isOpened():
        print("Error: Could not open camera.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    ret, frame = cap.read()
    if not ret:
        cap.release()
        return

    height, width, _ = frame.shape
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    
    avg_frame = None
    out = None
    recording_start_time = 0
    last_motion_time = 0
    current_filename = ""

    print("Motion detection engine active.")

    while True:
        ret, frame = cap.read()
        if not ret: break

        with lock:
            last_frame = frame.copy()

        # Check if we should be monitoring (Schedule OR Manual Override)
        should_monitor = is_within_schedule() or state["manual_override"]
        update_state("is_monitoring", should_monitor)

        if not should_monitor:
            if state["is_recording"]:
                # Force stop recording if system is disabled
                out.release()
                update_state("is_recording", False)
                print("Recording stopped (System disabled).")
            avg_frame = None # Reset background for when it restarts
            continue

        # --- MOTION DETECTION ---
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
            update_state("last_motion", datetime.now().strftime("%H:%M:%S"))
            if not state["is_recording"]:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                current_filename = f"motion_{timestamp}.mp4"
                out = cv2.VideoWriter(current_filename, fourcc, fps, (width, height))
                update_state("is_recording", True)
                update_state("current_filename", current_filename)
                recording_start_time = current_time
                print(f"Motion! Saving to {current_filename}")

        if state["is_recording"]:
            out.write(frame)
            if (current_time - last_motion_time) > IDLE_TIMEOUT:
                out.release()
                update_state("is_recording", False)
                duration = current_time - recording_start_time
                if duration < MIN_DURATION:
                    if os.path.exists(current_filename): os.remove(current_filename)
                    update_state("current_filename", "None (Deleted: <1s)")
                else:
                    update_state("total_recordings", state["total_recordings"] + 1)
                    update_state("current_filename", "None (Idle)")
                    print(f"Saved {current_filename}")

    cap.release()

@app.before_request
def start_camera_thread():
    global camera_started
    if not camera_started:
        threading.Thread(target=run_camera, daemon=True).start()
        camera_started = True

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=WEBSITE_PORT, debug=False, use_reloader=False)
