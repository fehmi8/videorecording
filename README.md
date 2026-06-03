# Jetson Nano Motion-Activated Camera

A robust, motion-activated recording system for the Jetson Nano using USB cameras. Features a remote web dashboard with live streaming, disk space monitoring, and password protection.

## Features
- **Motion Detection:** Intelligent weighted-average background subtraction.
- **Live Stream:** Remote MJPEG video feed via Flask.
- **Production Ready:** Designed to run with Gunicorn for stability.
- **Disk Management:** Real-time disk space monitoring on the dashboard.
- **Secure:** Basic Auth protection for remote access.

## Setup Instructions

### 1. Create a Virtual Environment
It is recommended to use a virtual environment to manage dependencies:
```bash
python3 -m venv .venv
```

### 2. Activate the Environment
```bash
source .venv/bin/activate
```

### 3. Install Requirements
```bash
pip install -r requirements.txt
```
*Note: Ensure OpenCV is installed on your Jetson. If the pip version fails, you may need to use the system-provided OpenCV.*

## Launching the System

### Production Mode (Recommended)
To launch with the Gunicorn production server:
```bash
gunicorn --bind 0.0.0.0:5000 record_motion:app
```
Access the dashboard at: `http://<jetson-ip>:5000`
- **Username:** (Any)
- **Password:** `jetson_secret`

### Development/Test Mode
To run the script directly:
```bash
python3 record_motion.py
```

## Project Structure
- `record_motion.py`: Main application (Camera engine + Web server).
- `record_3s.py`: Simple utility for timed recordings.
- `requirements.txt`: Python dependencies.
- `.gitignore`: Files excluded from version control (videos, venv, etc).

## License
MIT
