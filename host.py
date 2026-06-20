# -*- coding: utf-8 -*-
# PC camera client — connects to the cloud server and streams webcam
import cv2
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext
from PIL import Image, ImageTk
import urllib.request
import urllib.error
import time
import json

server_url = ""
room_id = ""
camera = None
is_running = False
preview_canvas = None
chat_box = None
overlay_text = ""


# ── Camera + frame push ───────────────────────────────────────────────────────
def frame_push_loop():
    global camera, is_running
    while is_running:
        if camera and camera.isOpened():
            ret, frame = camera.read()
            if ret and frame is not None:
                if overlay_text:
                    import cv2 as _cv2
                    _cv2.putText(frame, overlay_text, (20, frame.shape[0] - 20),
                                 _cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 3, _cv2.LINE_AA)
                    _cv2.putText(frame, overlay_text, (20, frame.shape[0] - 20),
                                 _cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 1, _cv2.LINE_AA)
                # Update preview canvas
                if preview_canvas:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    img = Image.fromarray(rgb).resize((480, 270))
                    photo = ImageTk.PhotoImage(img)
                    preview_canvas.image = photo
                    preview_canvas.after(0, lambda p=photo: (
                        preview_canvas.delete("all"),
                        preview_canvas.create_image(0, 0, anchor=tk.NW, image=p)
                    ))
                # Push frame to cloud server
                _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 40])
                try:
                    req = urllib.request.Request(
                        f'{server_url}/upload_frame/{room_id}',
                        data=buf.tobytes(),
                        headers={'Content-Type': 'image/jpeg'})
                    urllib.request.urlopen(req, timeout=2)
                except Exception:
                    pass
        time.sleep(0.1)


def chat_poll_loop():
    seen = 0
    while is_running:
        try:
            with urllib.request.urlopen(f'{server_url}/messages/{room_id}', timeout=3) as r:
                msgs = json.loads(r.read())
            for msg in msgs[seen:]:
                if chat_box:
                    m = msg
                    chat_box.after(0, lambda m=m: append_chat(m['sender'], m['text']))
            seen = len(msgs)
        except Exception:
            pass
        time.sleep(1)


# ── Helpers ───────────────────────────────────────────────────────────────────
def append_chat(sender, text):
    if chat_box is None:
        return
    chat_box.config(state=tk.NORMAL)
    chat_box.insert(tk.END, f'{sender}: {text}\n')
    chat_box.see(tk.END)
    chat_box.config(state=tk.DISABLED)

def copy_link(var, root):
    root.clipboard_clear()
    root.clipboard_append(var.get())
    root.update()


# ── Start streaming ───────────────────────────────────────────────────────────
def start_hosting(server_entry, room_name_entry, viewer_link_var, host_link_var,
                  overlay_entry, status_var, start_btn, root):
    global server_url, room_id, camera, is_running, overlay_text

    raw = server_entry.get().strip().rstrip('/')
    if not raw:
        messagebox.showerror("Error", "Please enter the Railway server URL.")
        return
    server_url = raw
    room_name = room_name_entry.get().strip() or 'My Room'
    overlay_text = overlay_entry.get().strip()

    status_var.set("Opening camera...")
    # Open webcam
    camera = None
    for index in range(5):
        cap = cv2.VideoCapture(index)
        if cap.isOpened():
            ret, test = cap.read()
            if ret and test is not None:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
                camera = cap
                break
            cap.release()
    if camera is None:
        status_var.set("No camera found.")
        messagebox.showerror("Error", "No webcam found.")
        return

    status_var.set("Creating room on server...")
    try:
        body = json.dumps({'name': room_name}).encode()
        req = urllib.request.Request(
            f'{server_url}/api/create_room',
            data=body,
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read())
        room_id = result['room_id']
    except Exception as e:
        status_var.set(f"Failed to reach server: {e}")
        messagebox.showerror("Error", f"Could not connect to server:\n{e}")
        return

    is_running = True
    threading.Thread(target=frame_push_loop, daemon=True).start()
    threading.Thread(target=chat_poll_loop, daemon=True).start()

    viewer_link_var.set(f'{server_url}/room/{room_id}')
    host_link_var.set(f'{server_url}/host-web/{room_id}')
    status_var.set(f'Live! Streaming to {server_url}')
    start_btn.config(state=tk.DISABLED)
    server_entry.config(state=tk.DISABLED)
    room_name_entry.config(state=tk.DISABLED)


def send_chat_msg(msg_entry, name_entry):
    text = msg_entry.get().strip()
    if not text or not server_url or not room_id:
        return
    msg_entry.delete(0, tk.END)
    sender = name_entry.get().strip() or 'Host'
    try:
        body = json.dumps({'sender': sender, 'text': text}).encode()
        req = urllib.request.Request(
            f'{server_url}/send/{room_id}',
            data=body,
            headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass


# ── Tkinter UI ────────────────────────────────────────────────────────────────
def main():
    global preview_canvas, chat_box

    root = tk.Tk()
    root.title("Camera Host")
    root.geometry("1000x720")
    root.resizable(False, False)

    left = tk.Frame(root)
    left.pack(side=tk.LEFT, fill=tk.BOTH, padx=10, pady=10)

    tk.Label(left, text="Camera Host", font=("Arial", 14, "bold")).pack(pady=(6, 2))
    tk.Label(left, text="Streams to your Railway cloud server", fg="gray", font=("Arial", 9)).pack()

    tk.Label(left, text="Server URL:", font=("Arial", 11)).pack(pady=(12, 2))
    server_entry = tk.Entry(left, width=44, font=("Arial", 10))
    server_entry.insert(0, "https://your-app.up.railway.app")
    server_entry.pack()

    tk.Label(left, text="Room Name:", font=("Arial", 11)).pack(pady=(10, 2))
    room_name_entry = tk.Entry(left, width=40, font=("Arial", 11))
    room_name_entry.insert(0, "My Room")
    room_name_entry.pack()

    tk.Label(left, text="Overlay Text (optional):", font=("Arial", 10)).pack(pady=(8, 2))
    overlay_entry = tk.Entry(left, width=40, font=("Arial", 10))
    overlay_entry.pack()

    viewer_link_var = tk.StringVar(value="")
    host_link_var = tk.StringVar(value="")
    status_var = tk.StringVar(value="Enter your Railway URL and press Start.")

    start_btn = tk.Button(
        left, text="Start Streaming", font=("Arial", 11), bg="#4a90e2", fg="white",
        command=lambda: threading.Thread(
            target=start_hosting,
            args=(server_entry, room_name_entry, viewer_link_var, host_link_var,
                  overlay_entry, status_var, start_btn, root),
            daemon=True).start())
    start_btn.pack(pady=(14, 6))

    tk.Label(left, textvariable=status_var, fg="gray", font=("Arial", 10), wraplength=380).pack()

    # Links
    for label, var in [("Viewer Link:", viewer_link_var), ("Host Link:", host_link_var)]:
        tk.Label(left, text=label, font=("Arial", 10)).pack(pady=(10, 0))
        row = tk.Frame(left)
        row.pack(fill=tk.X)
        e = tk.Entry(row, textvariable=var, font=("Arial", 9), state="readonly", width=38)
        e.pack(side=tk.LEFT)
        tk.Button(row, text="Copy", font=("Arial", 9),
                  command=lambda v=var: copy_link(v, root)).pack(side=tk.LEFT, padx=4)

    # Preview
    preview_canvas = tk.Canvas(left, width=480, height=270, bg="black")
    preview_canvas.pack(pady=(14, 0))

    # Chat panel
    right = tk.Frame(root, bd=1, relief=tk.SUNKEN, width=240)
    right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10), pady=10)
    right.pack_propagate(False)

    tk.Label(right, text="Live Chat", font=("Arial", 12, "bold")).pack(pady=(8, 4))

    tk.Label(right, text="Your name:", font=("Arial", 10)).pack()
    name_entry = tk.Entry(right, font=("Arial", 10), width=20, justify="center")
    name_entry.insert(0, "Host")
    name_entry.pack(pady=(0, 6))

    chat_box = scrolledtext.ScrolledText(right, state=tk.DISABLED, wrap=tk.WORD,
                                          font=("Arial", 10), bg="#f5f5f5")
    chat_box.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

    send_frame = tk.Frame(right)
    send_frame.pack(fill=tk.X, padx=6, pady=(0, 8))
    msg_entry = tk.Entry(send_frame, font=("Arial", 10))
    msg_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
    msg_entry.bind("<Return>", lambda e: send_chat_msg(msg_entry, name_entry))
    tk.Button(send_frame, text="Send", font=("Arial", 10),
              command=lambda: send_chat_msg(msg_entry, name_entry)).pack(side=tk.LEFT)

    def on_close():
        global is_running
        is_running = False
        if camera:
            camera.release()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
