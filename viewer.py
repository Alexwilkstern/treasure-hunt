import tkinter as tk
from tkinter import messagebox, scrolledtext
import threading
import requests
import cv2
import numpy as np
from PIL import Image, ImageTk
import io


class ViewerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Camera Viewer")
        self.root.geometry("1060x600")
        self.running = False
        self.base_url = ""
        self.seen_messages = 0
        self.viewer_name = self._ask_name()

        # --- Top bar ---
        top = tk.Frame(root)
        top.pack(fill=tk.X, padx=10, pady=(12, 4))
        tk.Label(top, text="Your Name:", font=("Arial", 11)).pack(side=tk.LEFT, padx=(0, 4))
        self.name_entry = tk.Entry(top, width=14, font=("Arial", 10))
        self.name_entry.insert(0, self.viewer_name)
        self.name_entry.pack(side=tk.LEFT, padx=(0, 12))
        tk.Label(top, text="Stream Link:", font=("Arial", 11)).pack(side=tk.LEFT, padx=(0, 6))
        self.url_entry = tk.Entry(top, width=44, font=("Arial", 10))
        self.url_entry.pack(side=tk.LEFT, padx=(0, 8))
        self.connect_btn = tk.Button(top, text="Connect", font=("Arial", 11), command=self.start_stream)
        self.connect_btn.pack(side=tk.LEFT)
        self.stop_btn = tk.Button(top, text="Disconnect", font=("Arial", 11), command=self.stop_stream, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=(6, 0))

        self.status_var = tk.StringVar(value="Paste the link and press Connect.")
        tk.Label(root, textvariable=self.status_var, fg="gray", font=("Arial", 10)).pack(pady=(0, 4))

        # --- Main area ---
        main = tk.Frame(root)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # Video
        self.canvas = tk.Label(main, bg="black", width=820)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        # Chat panel
        right = tk.Frame(main, bd=1, relief=tk.SUNKEN, width=220)
        right.pack(side=tk.LEFT, fill=tk.BOTH)
        right.pack_propagate(False)

        tk.Label(right, text="Live Chat", font=("Arial", 12, "bold")).pack(pady=(8, 4))

        self.chat_box = scrolledtext.ScrolledText(right, state=tk.DISABLED, wrap=tk.WORD,
                                                   font=("Arial", 10), bg="#f5f5f5")
        self.chat_box.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

        send_frame = tk.Frame(right)
        send_frame.pack(fill=tk.X, padx=6, pady=(0, 8))
        self.msg_entry = tk.Entry(send_frame, font=("Arial", 10))
        self.msg_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.msg_entry.bind("<Return>", self.send_message)
        tk.Button(send_frame, text="Send", font=("Arial", 10), command=self.send_message).pack(side=tk.LEFT)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _ask_name(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Welcome")
        dialog.geometry("300x140")
        dialog.resizable(False, False)
        dialog.grab_set()

        tk.Label(dialog, text="Enter your name to join:", font=("Arial", 12)).pack(pady=(20, 8))
        entry = tk.Entry(dialog, font=("Arial", 12), width=22, justify="center")
        entry.pack()
        entry.focus()

        result = ["Viewer"]

        def confirm(event=None):
            name = entry.get().strip()
            result[0] = name if name else "Viewer"
            dialog.destroy()

        entry.bind("<Return>", confirm)
        tk.Button(dialog, text="Join", font=("Arial", 11), command=confirm).pack(pady=10)
        self.root.wait_window(dialog)
        return result[0]

    def _base_url_from_link(self, url):
        # Strip /video suffix to get base URL for chat endpoints
        url = url.rstrip("/")
        if url.endswith("/video"):
            url = url[:-6]
        return url

    def start_stream(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter the stream link.")
            return
        self.base_url = self._base_url_from_link(url)
        self.seen_messages = 0
        self.running = True
        self.connect_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("Connecting...")
        threading.Thread(target=self.read_stream, args=(url,), daemon=True).start()
        self.poll_chat()

    def read_stream(self, url):
        try:
            response = None
            for attempt in range(1, 6):
                try:
                    self.status_var.set(f"Connecting... (attempt {attempt}/5)")
                    response = requests.get(url, stream=True, timeout=10,
                                            headers={"ngrok-skip-browser-warning": "1"})
                    break
                except Exception:
                    if attempt < 5:
                        time.sleep(2)
                    else:
                        raise
            if response is None or response.status_code != 200:
                self.status_var.set(f"Failed to connect (HTTP {response.status_code if response else '?'}).")
                self.reset_buttons()
                return

            self.status_var.set("Connected — watching live.")
            buffer = b""
            for chunk in response.iter_content(chunk_size=4096):
                if not self.running:
                    break
                buffer += chunk
                start = buffer.find(b'\xff\xd8')
                end = buffer.find(b'\xff\xd9')
                if start != -1 and end != -1 and end > start:
                    jpg = buffer[start:end + 2]
                    buffer = buffer[end + 2:]
                    try:
                        img_array = np.frombuffer(jpg, dtype=np.uint8)
                        frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        img = Image.fromarray(frame)
                        img.thumbnail((820, 480))
                        photo = ImageTk.PhotoImage(img)
                        self.canvas.config(image=photo)
                        self.canvas.image = photo
                    except Exception:
                        continue
        except requests.exceptions.ConnectionError:
            self.status_var.set("Connection lost or refused.")
        except requests.exceptions.Timeout:
            self.status_var.set("Connection timed out.")
        except Exception as e:
            self.status_var.set(f"Error: {e}")
        finally:
            self.reset_buttons()

    def poll_chat(self):
        if not self.running:
            return
        try:
            resp = requests.get(f"{self.base_url}/messages", timeout=3,
                                headers={"ngrok-skip-browser-warning": "1"})
            if resp.status_code == 200:
                messages = resp.json()
                for msg in messages[self.seen_messages:]:
                    self._append_chat(msg["sender"], msg["text"])
                self.seen_messages = len(messages)
        except Exception:
            pass
        self.root.after(1000, self.poll_chat)

    def _append_chat(self, sender, text):
        self.chat_box.config(state=tk.NORMAL)
        self.chat_box.insert(tk.END, f"{sender}: {text}\n")
        self.chat_box.see(tk.END)
        self.chat_box.config(state=tk.DISABLED)

    def send_message(self, event=None):
        text = self.msg_entry.get().strip()
        if not text or not self.base_url:
            return
        self.msg_entry.delete(0, tk.END)
        try:
            name = self.name_entry.get().strip() or "Viewer"
            requests.post(f"{self.base_url}/send",
                          json={"sender": name, "text": text},
                          timeout=3,
                          headers={"ngrok-skip-browser-warning": "1"})
        except Exception:
            pass

    def stop_stream(self):
        self.running = False
        self.status_var.set("Disconnected.")
        self.canvas.config(image="")

    def reset_buttons(self):
        self.running = False
        self.connect_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)

    def on_close(self):
        self.running = False
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = ViewerApp(root)
    root.mainloop()
