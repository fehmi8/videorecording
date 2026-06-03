import cv2
import time

def record_video(duration=3, filename='recording_3s.mp4', device_index=0):
    # Initialize the USB camera using the native V4L2 backend to avoid GStreamer warnings
    cap = cv2.VideoCapture(device_index, cv2.CAP_V4L2)

    if not cap.isOpened():
        print(f"Error: Could not open camera at index {device_index}.")
        return

    # Attempt to set resolution (common for USB webcams)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    # DYNAMIC RESOLUTION DETECTION: Read one frame to get actual dimensions
    # This prevents file corruption caused by size mismatches.
    ret, frame = cap.read()
    if not ret:
        print("Error: Could not read the first frame. Camera might be busy.")
        cap.release()
        return

    height, width, channels = frame.shape
    
    # Get FPS from camera, fallback to 30 if invalid
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0 or fps > 60:
        fps = 30.0

    # Use H.264 codec for MP4 - highly compatible and efficient
    # 'avc1' is the FourCC for H.264
    fourcc = cv2.VideoWriter_fourcc(*'avc1')
    out = cv2.VideoWriter(filename, fourcc, fps, (width, height))

    if not out.isOpened():
        # Fallback to 'mp4v' if 'avc1' fails on this specific OS build
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(filename, fourcc, fps, (width, height))

    if not out.isOpened():
        print("Error: Could not open VideoWriter. Check codec and file permissions.")
        cap.release()
        return

    print(f"Recording {duration} seconds to {filename}...")
    print(f"Actual Resolution: {width}x{height} @ {fps} FPS")

    # Write the first frame we already read
    out.write(frame)
    frames_recorded = 1
    
    start_time = time.time()
    try:
        while (time.time() - start_time) < duration:
            ret, frame = cap.read()
            if not ret:
                break
            out.write(frame)
            frames_recorded += 1
            
    except Exception as e:
        print(f"Error during recording: {e}")
    finally:
        cap.release()
        out.release()
        end_time = time.time()
        print(f"Done. Recorded {frames_recorded} frames in {end_time - start_time:.2f}s.")
        print(f"Effective FPS: {frames_recorded / (end_time - start_time):.2f}")

if __name__ == "__main__":
    record_video(duration=3, filename='recording_3s.mp4', device_index=0)
