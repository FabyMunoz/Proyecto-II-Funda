import queue
import random
import socket
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

HOST = "0.0.0.0"
PORT = 8001

MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".",
    "F": "..-.", "G": "--.", "H": "....", "I": "..", "J": ".---",
    "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---",
    "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-",
    "U": "..-", "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--",
    "Z": "--..", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
    "0": "-----", "+": ".-.-.", "-": "-....-"
}
MORSE_TO_CHAR = {v: k for k, v in MORSE.items()}
ALLOWED_CHARS = set(MORSE.keys()) | {" "}
DEFAULT_PHRASES = ["SOS", "SI", "NO", "HOLA", "VIDA", "ROJO", "CHAO", "A+B", "SOL", "LUNA"]

def normalize_text(text):
    return "".join(ch for ch in text.upper().strip() if ch in ALLOWED_CHARS)

def text_to_morse(text):
    words = []
    for word in normalize_text(text).split(" "):
        words.append(" ".join(MORSE[ch] for ch in word if ch in MORSE))
    return " / ".join(words)

def expected_units_for_text(text):
    text = normalize_text(text)
    total = 0
    for wi, word in enumerate(text.split(" ")):
        for li, ch in enumerate(word):
            code = MORSE.get(ch, "")
            for si, sym in enumerate(code):
                total += 1 if sym == "." else 3
                if si < len(code) - 1: total += 1
            if li < len(word) - 1: total += 3
        if wi < len(text.split(" ")) - 1: total += 7
    return total

def evaluate_response(expected_text, received_text, received_morse="", elapsed_ms=None, unit_s=0.2, include_speed=False):
    expected_text = normalize_text(expected_text)
    received_text = normalize_text(received_text)
    max_chars = max(len(expected_text), 1)
    correct_chars = sum(1 for a, b in zip(expected_text, received_text) if a == b)
    char_ratio = correct_chars / max_chars
    expected_morse = text_to_morse(expected_text).replace(" / ", " ")
    if received_morse:
        exp = expected_morse.split()
        rec = received_morse.replace("/", " ").split()
        max_tokens = max(len(exp), 1)
        correct_morse = sum(1 for a, b in zip(exp, rec) if a == b)
        morse_ratio = correct_morse / max_tokens
    else:
        morse_ratio = char_ratio
    speed_level = "No aplica"
    speed_points = 0
    if include_speed:
        expected_ms = max(expected_units_for_text(expected_text) * unit_s * 1000, 1)
        elapsed_ms = elapsed_ms or expected_ms * 3
        if elapsed_ms <= expected_ms * 1.5:
            speed_level, speed_points = "Rápido", 20
        elif elapsed_ms <= expected_ms * 2.5:
            speed_level, speed_points = "Normal", 12
        else:
            speed_level, speed_points = "Lento", 6
        score = round(char_ratio * 70 + morse_ratio * 10 + speed_points)
    else:
        score = round(char_ratio * 70 + morse_ratio * 30)
    return {"score": max(0, min(100, score)), "correct_chars": correct_chars, "max_chars": max_chars,
            "expected_morse": text_to_morse(expected_text), "received_text": received_text,
            "received_morse": received_morse, "speed_level": speed_level, "speed_points": speed_points}

def increment5_info(ch):
    ch = normalize_text(ch[:1])
    if not ch:
        return None
    ascii_value = ord(ch)
    low_bits = ascii_value & 0x0F
    result = (low_bits + 5) & 0x0F
    return {
        "char": ch,
        "ascii": ascii_value,
        "input_bits": format(low_bits, "04b"),
        "result_bits": format(result, "04b"),
        "result_value": result,
    }

def invert_bits(bits):
    return "".join("1" if bit == "0" else "0" for bit in bits)

class PicoServer:
    def __init__(self, host, port, inbox_queue, log_callback):
        self.host = host
        self.port = port
        self.inbox_queue = inbox_queue
        self.log = log_callback
        self.server_socket = None
        self.client_socket = None
        self.running = False
        self.rx_buffer = b""

    def start(self):
        if self.running: return
        self.running = True
        threading.Thread(target=self._server_loop, daemon=True).start()

    def _server_loop(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(1)
            self.log(f"Servidor escuchando en {self.host}:{self.port}")
            while self.running:
                client, addr = self.server_socket.accept()
                self.client_socket = client
                self.client_socket.settimeout(0.1)
                self.rx_buffer = b""
                self.log(f"Pico conectada desde {addr[0]}:{addr[1]}")
                self._client_loop()
        except Exception as exc:
            self.log(f"Error del servidor: {exc}")
        finally:
            self.stop()

    def _client_loop(self):
        while self.running and self.client_socket:
            try:
                data = self.client_socket.recv(512)
                if not data:
                    self.log("La Pico cerró la conexión.")
                    self.client_socket.close()
                    self.client_socket = None
                    return
                self.rx_buffer += data
                while b"\n" in self.rx_buffer:
                    line, self.rx_buffer = self.rx_buffer.split(b"\n", 1)
                    if line:
                        self.inbox_queue.put(self.parse_line(line.decode().strip()))
            except socket.timeout:
                continue
            except Exception as exc:
                self.log(f"Error leyendo Pico: {exc}")
                self.client_socket = None
                return

    def parse_line(self, line):
        p = line.split("|")
        if p[0] == "HELLO":
            return {"type": "HELLO", "ip": p[1] if len(p) > 1 else ""}
        if p[0] == "INPUT_UPDATE":
            return {"type": "INPUT_UPDATE", "text": p[1] if len(p) > 1 else "", "morse": p[2] if len(p) > 2 else "", "current": p[3] if len(p) > 3 else ""}
        if p[0] == "INPUT_DONE":
            try: elapsed = int(p[3]) if len(p) > 3 else 0
            except Exception: elapsed = 0
            return {"type": "INPUT_DONE", "text": p[1] if len(p) > 1 else "", "morse": p[2] if len(p) > 2 else "", "elapsed_ms": elapsed}
        if p[0] == "INC_UPDATE":
            return {
                "type": "INC_UPDATE",
                "enabled": p[1] if len(p) > 1 else "0",
                "char": p[2] if len(p) > 2 else "",
                "ascii": p[3] if len(p) > 3 else "",
                "input_bits": p[4] if len(p) > 4 else "",
                "result_bits": p[5] if len(p) > 5 else "",
                "result_value": p[6] if len(p) > 6 else "",
            }
        if p[0] == "SWITCH":
            return {"type": "SWITCH", "state": p[1] if len(p) > 1 else "off"}
        return {"type": p[0], "raw": line}

    def send_line(self, line):
        if not self.client_socket:
            self.log("No hay Pico conectada.")
            return False
        try:
            self.client_socket.sendall((line + "\n").encode())
            return True
        except Exception as exc:
            self.log(f"Error enviando a Pico: {exc}")
            return False

    def is_connected(self):
        return self.client_socket is not None

    def stop(self):
        self.running = False
        for s in [self.client_socket, self.server_socket]:
            try:
                if s: s.close()
            except Exception: pass
        self.client_socket = None
        self.server_socket = None

class StrangerTecApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("StrangerTEC Morse Translator")
        self.geometry("1050x650")
        self.minsize(920, 560)
        self.configure(bg="#0f172a")
        self.inbox = queue.Queue()
        self.server = PicoServer(HOST, PORT, self.inbox, self.log)
        self.current_phrase = ""
        self.current_phase = 0
        self.mode_running = False
        self.waiting_pc = False
        self.waiting_hw = False
        self.scores = {"A": 0, "B": 0}
        self.hw_latest_text = ""
        self.hw_latest_morse = ""
        self.hw_latest_elapsed_ms = 0
        self.incrementer_enabled = False
        self.incrementer_test_var = tk.StringVar(value="0")
        self.incrementer_var = tk.StringVar(value="Incrementador +5: esperando datos de la Pico.")
        self.pc_morse_enabled = False
        self.pc_space_pressed = False
        self.pc_press_start = None
        self.pc_current_symbol = ""
        self.pc_decoded_text = ""
        self.pc_morse_letters = []
        self.pc_letter_after_id = None
        self.pc_word_after_id = None
        self.pc_capture_start = None
        self.mode_var = tk.StringVar(value="listen")
        self.output_var = tk.StringVar(value="led")
        self.unit_var = tk.StringVar(value="0.2")
        self.pc_entry_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Servidor no iniciado.")
        self.turn_var = tk.StringVar(value="Sin partida.")
        self.score_var = tk.StringVar(value="Jugador A: 0 | Jugador B: 0")
        self.hw_text_var = tk.StringVar(value="Entrada maqueta: ---")
        self.morse_preview_var = tk.StringVar(value="Morse: ---")
        self.pc_morse_status_var = tk.StringVar(value="Morse PC: desactivado")
        self.phrase_vars = [tk.StringVar(value=DEFAULT_PHRASES[i]) for i in range(10)]
        self._build_ui()
        self.bind_all("<KeyPress-space>", self.on_pc_space_press)
        self.bind_all("<KeyRelease-space>", self.on_pc_space_release)
        self.after(100, self.process_inbox)

    def label(self, parent, text, color="#93c5fd", size=13):
        return tk.Label(parent, text=text, bg="#111827", fg=color, font=("Arial", size, "bold"))

    def _build_ui(self):
        tk.Label(self, text="StrangerTEC Morse Translator", bg="#0f172a", fg="#e5e7eb", font=("Arial", 18, "bold")).pack(pady=6)
        container = tk.Frame(self, bg="#0f172a")
        container.pack(fill="both", expand=True, padx=8, pady=4)
        left = tk.Frame(container, bg="#111827", bd=1, relief="solid")
        center_shell = tk.Frame(container, bg="#111827", bd=1, relief="solid")
        right = tk.Frame(container, bg="#111827", bd=1, relief="solid")
        left.pack(side="left", fill="both", expand=False, padx=4)
        center_shell.pack(side="left", fill="both", expand=True, padx=4)
        right.pack(side="left", fill="both", expand=True, padx=4)
        center = self._make_scrollable_panel(center_shell)
        self._build_config_panel(left)
        self._build_game_panel(center)
        self._build_alphabet_panel(right)
        self._build_log_panel()

    def _make_scrollable_panel(self, parent):
        canvas = tk.Canvas(parent, bg="#111827", highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        content = tk.Frame(canvas, bg="#111827")
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def on_content_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_canvas_configure(event):
            canvas.itemconfigure(window_id, width=event.width)

        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        content.bind("<Configure>", on_content_configure)
        canvas.bind("<Configure>", on_canvas_configure)
        canvas.bind_all("<MouseWheel>", on_mousewheel)
        return content

    def _build_config_panel(self, parent):
        self.label(parent, "Configuración").pack(anchor="w", padx=10, pady=(10, 4))
        tk.Button(parent, text="Iniciar servidor PC", command=self.start_server, bg="#2563eb", fg="white").pack(fill="x", padx=10, pady=4)
        tk.Label(parent, textvariable=self.status_var, bg="#111827", fg="#e5e7eb", wraplength=260, justify="left").pack(fill="x", padx=10, pady=4)
        ttk.Separator(parent).pack(fill="x", padx=10, pady=8)
        tk.Label(parent, text="Modo de juego", bg="#111827", fg="white").pack(anchor="w", padx=10)
        tk.Radiobutton(parent, text="Escucha y Transmisión", value="listen", variable=self.mode_var, bg="#111827", fg="white", selectcolor="#1f2937").pack(anchor="w", padx=16)
        tk.Radiobutton(parent, text="Transmisión Simple", value="simple", variable=self.mode_var, bg="#111827", fg="white", selectcolor="#1f2937").pack(anchor="w", padx=16)
        tk.Label(parent, text="Salida en maqueta", bg="#111827", fg="white").pack(anchor="w", padx=10, pady=(8,0))
        tk.Radiobutton(parent, text="Luces / panel", value="led", variable=self.output_var, bg="#111827", fg="white", selectcolor="#1f2937").pack(anchor="w", padx=16)
        tk.Radiobutton(parent, text="Buzzer", value="buzzer", variable=self.output_var, bg="#111827", fg="white", selectcolor="#1f2937").pack(anchor="w", padx=16)
        tk.Label(parent, text="Unidad Morse", bg="#111827", fg="white").pack(anchor="w", padx=10, pady=(8,0))
        tk.Radiobutton(parent, text="Unidad A = 0.2 s", value="0.2", variable=self.unit_var, bg="#111827", fg="white", selectcolor="#1f2937").pack(anchor="w", padx=16)
        tk.Radiobutton(parent, text="Unidad B = 0.3 s", value="0.3", variable=self.unit_var, bg="#111827", fg="white", selectcolor="#1f2937").pack(anchor="w", padx=16)
        ttk.Separator(parent).pack(fill="x", padx=10, pady=8)
        self.label(parent, "Lista de 10 frases").pack(anchor="w", padx=10)
        tk.Label(parent, text="Máximo 16 caracteres. Deben incluir SOS, SI, NO,\nuna con número y una con + o -.", bg="#111827", fg="#cbd5e1", justify="left").pack(anchor="w", padx=10)
        for i, var in enumerate(self.phrase_vars):
            row = tk.Frame(parent, bg="#111827")
            row.pack(fill="x", padx=10, pady=2)
            tk.Label(row, text=f"{i+1}.", bg="#111827", fg="white", width=3).pack(side="left")
            tk.Entry(row, textvariable=var, width=22).pack(side="left", fill="x", expand=True)
        tk.Button(parent, text="Validar frases", command=self.validate_phrases, bg="#22c55e").pack(fill="x", padx=10, pady=8)

    def _build_game_panel(self, parent):
        self.label(parent, "Partida").pack(anchor="w", padx=10, pady=(10,4))
        tk.Label(parent, textvariable=self.turn_var, bg="#111827", fg="#fef3c7", font=("Arial", 13, "bold"), wraplength=420, justify="left").pack(fill="x", padx=10, pady=4)
        tk.Label(parent, textvariable=self.score_var, bg="#111827", fg="#86efac", font=("Arial", 12, "bold")).pack(fill="x", padx=10, pady=4)
        btns = tk.Frame(parent, bg="#111827")
        btns.pack(fill="x", padx=10, pady=8)
        tk.Button(btns, text="Nueva ronda", command=self.start_round, bg="#f59e0b").pack(side="left", expand=True, fill="x", padx=3)
        tk.Button(btns, text="Reproducir frase en maqueta", command=self.play_current_phrase, bg="#38bdf8").pack(side="left", expand=True, fill="x", padx=3)
        ttk.Separator(parent).pack(fill="x", padx=10, pady=8)
        tk.Label(parent, text="Incrementador fisico +5", bg="#111827", fg="#93c5fd", font=("Arial", 11, "bold")).pack(anchor="w", padx=10)
        tk.Label(parent, textvariable=self.incrementer_var, bg="#1f2937", fg="#bfdbfe", font=("Consolas", 10), wraplength=390, justify="left").pack(fill="x", padx=10, pady=4)
        row4 = tk.Frame(parent, bg="#111827")
        row4.pack(fill="x", padx=10, pady=4)
        tk.Spinbox(row4, from_=0, to=15, textvariable=self.incrementer_test_var, width=5, font=("Consolas", 11)).pack(side="left", padx=3)
        tk.Button(row4, text="Probar manual", command=self.test_incrementer_value, bg="#38bdf8").pack(side="left", expand=True, fill="x", padx=3)
        tk.Button(row4, text="Limpiar", command=self.clear_incrementer, bg="#64748b", fg="white").pack(side="left", expand=True, fill="x", padx=3)
        row5 = tk.Frame(parent, bg="#111827")
        row5.pack(fill="x", padx=10, pady=4)
        tk.Button(row5, text="Forzar ON", command=self.force_incrementer_on, bg="#22c55e").pack(side="left", expand=True, fill="x", padx=3)
        tk.Button(row5, text="Auto switch", command=self.force_incrementer_auto, bg="#f59e0b").pack(side="left", expand=True, fill="x", padx=3)
        ttk.Separator(parent).pack(fill="x", padx=10, pady=8)
        tk.Label(parent, text="Entrada del jugador en PC", bg="#111827", fg="white").pack(anchor="w", padx=10)
        entry = tk.Entry(parent, textvariable=self.pc_entry_var, font=("Consolas", 18), justify="center")
        entry.pack(fill="x", padx=10, pady=5)
        entry.bind("<KeyRelease>", lambda e: self.update_morse_preview())
        tk.Label(parent, textvariable=self.morse_preview_var, bg="#1f2937", fg="#22c55e", font=("Consolas", 12), wraplength=430, justify="left").pack(fill="x", padx=10, pady=5)
        row2 = tk.Frame(parent, bg="#111827")
        row2.pack(fill="x", padx=10, pady=5)
        tk.Button(row2, text="Enviar respuesta PC", command=self.submit_pc_answer, bg="#22c55e").pack(side="left", expand=True, fill="x", padx=3)
        tk.Button(row2, text="Limpiar entrada PC", command=self.clear_pc_entry, bg="#64748b", fg="white").pack(side="left", expand=True, fill="x", padx=3)
        ttk.Separator(parent).pack(fill="x", padx=10, pady=8)
        tk.Label(parent, text="Transmisión Morse desde PC usando ESPACIO", bg="#111827", fg="#facc15", font=("Arial", 11, "bold")).pack(anchor="w", padx=10)
        row_morse = tk.Frame(parent, bg="#111827")
        row_morse.pack(fill="x", padx=10, pady=5)
        tk.Button(row_morse, text="Activar Morse PC", command=self.enable_pc_morse_capture, bg="#facc15").pack(side="left", expand=True, fill="x", padx=3)
        tk.Button(row_morse, text="Terminar Morse PC", command=self.disable_pc_morse_capture, bg="#ef4444", fg="white").pack(side="left", expand=True, fill="x", padx=3)
        tk.Button(row_morse, text="Borrar Morse PC", command=self.reset_pc_morse_capture, bg="#64748b", fg="white").pack(side="left", expand=True, fill="x", padx=3)
        tk.Label(parent, textvariable=self.pc_morse_status_var, bg="#1f2937", fg="#e5e7eb", font=("Consolas", 11), wraplength=430, justify="left").pack(fill="x", padx=10, pady=5)
        ttk.Separator(parent).pack(fill="x", padx=10, pady=8)
        tk.Label(parent, text="Entrada desde maqueta", bg="#111827", fg="white").pack(anchor="w", padx=10)
        tk.Label(parent, textvariable=self.hw_text_var, bg="#1f2937", fg="#facc15", font=("Consolas", 14), wraplength=430, justify="left").pack(fill="x", padx=10, pady=5)
        row3 = tk.Frame(parent, bg="#111827")
        row3.pack(fill="x", padx=10, pady=5)
        tk.Button(row3, text="Iniciar captura maqueta", command=self.start_hw_capture, bg="#a78bfa").pack(side="left", expand=True, fill="x", padx=3)
        tk.Button(row3, text="Terminar captura maqueta", command=self.end_hw_capture, bg="#ef4444", fg="white").pack(side="left", expand=True, fill="x", padx=3)
        tk.Button(row3, text="Enviar respuesta maqueta", command=self.submit_hw_answer, bg="#22c55e").pack(side="left", expand=True, fill="x", padx=3)
        self.results_box = tk.Text(parent, height=6, bg="#020617", fg="#e5e7eb", font=("Consolas", 10))
        self.results_box.pack(fill="both", expand=True, padx=10, pady=8)

    def _build_alphabet_panel(self, parent):
        self.label(parent, "Panel del abecedario").pack(anchor="w", padx=10, pady=(10, 4))
        grid = tk.Frame(parent, bg="#111827")
        grid.pack(padx=10, pady=8)

        rows = [
            "ACEGIKMOQSUWY",
            "BDFHJLNPRTVXZ",
            "0123456789-+",
        ]

        for row_idx, row_chars in enumerate(rows):
            for col_idx, ch in enumerate(row_chars):
                tk.Button(
                    grid,
                    text=ch,
                    width=4,
                    command=lambda x=ch: self.append_pc_char(x),
                    bg="#334155",
                    fg="white"
                ).grid(row=row_idx, column=col_idx, padx=2, pady=3)

        ttk.Separator(parent).pack(fill="x", padx=10, pady=8)
        self.label(parent, "Tabla Morse").pack(anchor="w", padx=10)

        table = tk.Text(parent, height=20, bg="#020617", fg="#e5e7eb", font=("Consolas", 10))
        table.pack(fill="both", expand=True, padx=10, pady=8)

        for ch in list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-"):
            table.insert("end", f"{ch}: {MORSE[ch]}\n")

        table.configure(state="disabled")

    def _build_log_panel(self):
        frame = tk.Frame(self, bg="#0f172a")
        frame.pack(fill="x", padx=18, pady=(0,10))
        tk.Label(frame, text="Registro de comunicación", bg="#0f172a", fg="#93c5fd", font=("Arial", 11, "bold")).pack(anchor="w")
        self.log_box = tk.Text(frame, height=5, bg="#020617", fg="#cbd5e1", font=("Consolas", 9))
        self.log_box.pack(fill="x")

    def log(self, text):
        timestamp = time.strftime("%H:%M:%S")
        def write():
            self.log_box.insert("end", f"[{timestamp}] {text}\n")
            self.log_box.see("end")
            self.status_var.set(text)
        try: self.after(0, write)
        except Exception: pass

    def start_server(self): self.server.start()
    def send_to_pico(self, line):
        ok = self.server.send_line(line)
        if ok: self.log(f"PC -> Pico: {line}")
        return ok
    def process_inbox(self):
        while not self.inbox.empty(): self.handle_pico_msg(self.inbox.get())
        self.after(100, self.process_inbox)
    def handle_pico_msg(self, msg):
        mtype = msg.get("type", "")
        self.log(f"Pico -> PC: {mtype}")
        if mtype == "HELLO":
            self.status_var.set(f"Pico conectada. IP: {msg.get('ip')}")
        elif mtype == "INPUT_UPDATE":
            self.hw_latest_text, self.hw_latest_morse = msg.get("text", ""), msg.get("morse", "")
            self.hw_text_var.set(f"Entrada maqueta: {self.hw_latest_text}   Actual: {msg.get('current','')}\nMorse: {self.hw_latest_morse}")
        elif mtype == "INPUT_DONE":
            self.hw_latest_text, self.hw_latest_morse = msg.get("text", ""), msg.get("morse", "")
            elapsed = msg.get("elapsed_ms", 0)
            self.hw_latest_elapsed_ms = elapsed
            self.hw_text_var.set(f"Entrada maqueta final: {self.hw_latest_text}\nMorse: {self.hw_latest_morse}\nTiempo: {elapsed/1000:.2f} s")
            self.submit_hw_answer()
        elif mtype == "INC_UPDATE":
            self.update_incrementer_from_pico(msg)
        elif mtype == "SWITCH":
            self.incrementer_enabled = msg.get("state") == "on"
            state = "ACTIVADO" if self.incrementer_enabled else "DESACTIVADO"
            self.incrementer_var.set(f"Incrementador +5: switch {state}.\nEntradas Pico: A=GP0 B=GP1 C=GP2 D=GP3\nSalidas fisicas: S0=U1 pin2, S1=U4 pin3, S2=U3 pin3, S3=U3 pin8")

    def get_phrases(self): return [normalize_text(v.get()) for v in self.phrase_vars if normalize_text(v.get())]
    def validate_phrases(self):
        phrases = self.get_phrases()
        if len(phrases) != 10: messagebox.showerror("Frases inválidas", "Debe haber exactamente 10 frases no vacías."); return False
        for p in phrases:
            if len(p) > 16: messagebox.showerror("Frases inválidas", f"La frase '{p}' supera 16 caracteres."); return False
        for req in ["SOS", "SI", "NO"]:
            if req not in phrases: messagebox.showerror("Frases mínimas", f"Debe incluir {req}."); return False
        if not any(any(ch.isdigit() for ch in p) for p in phrases): messagebox.showerror("Frases mínimas", "Debe incluir al menos una frase con número."); return False
        if not any(("+" in p or "-" in p) for p in phrases): messagebox.showerror("Frases mínimas", "Debe incluir al menos una frase con + o -."); return False
        messagebox.showinfo("Frases válidas", "La lista de frases cumple las reglas básicas.")
        return True
    def current_unit(self): return float(self.unit_var.get())
    def configure_pico(self): self.send_to_pico(f"CONFIG|{self.mode_var.get()}|{self.output_var.get()}|{self.current_unit()}")
    def test_incrementer_value(self):
        try:
            value = int(self.incrementer_test_var.get()) & 0x0F
        except Exception:
            messagebox.showerror("Valor invalido", "Ingresa un numero entre 0 y 15.")
            return
        self.send_to_pico(f"TEST_INC|{value}")
    def clear_incrementer(self):
        self.send_to_pico("CLEAR_INC")
        self.incrementer_var.set("Incrementador +5: entradas ABCD limpiadas desde la interfaz.")
    def force_incrementer_on(self):
        self.send_to_pico("FORCE_INC|1")
        self.incrementer_var.set("Incrementador +5: FORZADO ON desde software.\nAhora prueba valores manuales 0, 1, 2, 15.")
    def force_incrementer_auto(self):
        self.send_to_pico("FORCE_INC|0")
        self.incrementer_var.set("Incrementador +5: modo automatico por switch fisico.")
    def update_incrementer_from_pico(self, msg):
        enabled = msg.get("enabled") == "1"
        label = "activo" if enabled else "apagado por switch"
        result_bits = msg.get("result_bits") or "----"
        active_low_bits = invert_bits(result_bits) if set(result_bits) <= {"0", "1"} else "----"
        self.incrementer_var.set(
            f"Incrementador +5 ({label})\n"
            f"Letra/valor: {msg.get('char') or 'manual'} | ASCII: {msg.get('ascii')}\n"
            f"Entrada ABCD: {msg.get('input_bits')}\n"
            f"Salida logica esperada S3S2S1S0: {result_bits} ({msg.get('result_value')})\n"
            f"Si tus LEDs van a +5V, encendidos esperados: {active_low_bits}\n"
            f"Orden fisico recomendado: S3 S2 S1 S0."
        )
        self.write_line(f"Incrementador +5: ABCD {msg.get('input_bits')} -> logico {result_bits} | LEDs activos-bajo {active_low_bits}")
    def start_round(self):
        if not self.validate_phrases(): return
        self.current_phrase = random.choice(self.get_phrases())
        self.current_phase = 0; self.mode_running = True; self.waiting_pc = False; self.waiting_hw = False; self.scores = {"A":0,"B":0}
        self.results_box.delete("1.0", "end"); self.update_score_label(); self.configure_pico()
        self.start_listen_phase() if self.mode_var.get() == "listen" else self.start_simple_phase()
    def start_listen_phase(self):
        self.clear_pc_entry(); self.reset_pc_morse_capture(); self.hw_text_var.set("Entrada maqueta: ---")
        if self.current_phase > 1: self.show_final_results(); return
        txt = "Fase 1: Jugador A en PC | Jugador B en maqueta." if self.current_phase == 0 else "Fase 2: Jugador B en PC | Jugador A en maqueta."
        self.turn_var.set(f"Frase seleccionada: {self.current_phrase}\n{txt}")
        self.waiting_pc = True; self.waiting_hw = True; self.play_current_phrase(); self.enable_pc_morse_capture(); self.start_hw_capture()
    def start_simple_phase(self):
        self.clear_pc_entry(); self.reset_pc_morse_capture(); self.hw_text_var.set("Entrada maqueta: ---")
        if self.current_phase > 1: self.show_final_results(); return
        player = "A" if self.current_phase == 0 else "B"
        self.turn_var.set(f"Transmisión Simple | Frase objetivo: {self.current_phrase}\nJugador {player}: transmite desde la maqueta.")
        self.waiting_pc = False; self.waiting_hw = True; self.start_hw_capture()
    def play_current_phrase(self):
        if not self.current_phrase: messagebox.showinfo("Sin frase", "Primero inicia una ronda."); return
        self.configure_pico(); self.send_to_pico(f"PLAY|{self.current_phrase}|{self.output_var.get()}|{self.current_unit()}")
    def start_hw_capture(self):
        if not self.server.is_connected(): messagebox.showwarning("Sin Pico", "Primero conecta la Raspberry Pi Pico W."); return
        self.hw_latest_text = ""; self.hw_latest_morse = ""; self.hw_latest_elapsed_ms = 0; self.hw_text_var.set("Entrada maqueta: capturando..."); self.send_to_pico("START_CAPTURE")
    def end_hw_capture(self): self.send_to_pico("END_CAPTURE")
    def submit_hw_answer(self):
        if not self.mode_running:
            messagebox.showinfo("Sin partida", "Primero inicia una ronda.")
            return
        if not self.waiting_hw:
            messagebox.showinfo("Respuesta ya enviada", "La respuesta de maqueta para esta fase ya fue evaluada.")
            return
        if not self.hw_latest_text and not self.hw_latest_morse:
            messagebox.showinfo("Sin respuesta", "Primero termina la captura de la maqueta.")
            return
        self.process_hw_answer(self.hw_latest_text, self.hw_latest_morse, self.hw_latest_elapsed_ms)
    def submit_pc_answer(self):
        if not self.mode_running or self.mode_var.get() != "listen" or not self.waiting_pc: return
        self.finalize_pc_pending_letter()
        player = "A" if self.current_phase == 0 else "B"
        result = evaluate_response(self.current_phrase, self.pc_entry_var.get(), " ".join(self.pc_morse_letters), unit_s=self.current_unit())
        self.scores[player] += result["score"]; self.waiting_pc = False; self.disable_pc_morse_capture(silent=True)
        self.write_result(f"Jugador {player} en PC", result); self.update_score_label(); self.check_phase_complete()
    def process_hw_answer(self, text, morse, elapsed_ms):
        if not self.mode_running or not self.waiting_hw: return
        include_speed = self.mode_var.get() == "simple"
        player = ("B" if self.current_phase == 0 else "A") if self.mode_var.get() == "listen" else ("A" if self.current_phase == 0 else "B")
        result = evaluate_response(self.current_phrase, text, morse, elapsed_ms, self.current_unit(), include_speed)
        self.scores[player] += result["score"]; self.waiting_hw = False
        self.write_result(f"Jugador {player} en maqueta", result); self.update_score_label(); self.check_phase_complete()
    def check_phase_complete(self):
        if self.mode_var.get() == "listen":
            if not self.waiting_pc and not self.waiting_hw:
                self.current_phase += 1
                self.start_listen_phase() if self.current_phase <= 1 else self.show_final_results()
        else:
            if not self.waiting_hw:
                self.current_phase += 1
                self.start_simple_phase() if self.current_phase <= 1 else self.show_final_results()
    def show_final_results(self):
        self.mode_running = False; self.disable_pc_morse_capture(silent=True)
        a, b = self.scores["A"], self.scores["B"]
        winner = "Ganador: Jugador A" if a > b else "Ganador: Jugador B" if b > a else "Resultado: Empate"
        text = f"FINAL DE RONDA\nFrase: {self.current_phrase}\nJugador A: {a} puntos\nJugador B: {b} puntos\n{winner}\n"
        self.turn_var.set(text); self.write_line("\n" + text); messagebox.showinfo("Resultado final", text)
    def enable_pc_morse_capture(self):
        self.pc_morse_enabled = True; self.pc_space_pressed = False; self.pc_press_start = None; self.pc_capture_start = time.time(); self.pc_morse_status_var.set("Morse PC: ACTIVO. Usa ESPACIO."); self.focus_set()
    def disable_pc_morse_capture(self, silent=False):
        if not silent: self.finalize_pc_pending_letter(); self.pc_morse_status_var.set("Morse PC: desactivado.")
        self.cancel_pc_pause_timers(); self.pc_morse_enabled = False; self.pc_space_pressed = False
    def reset_pc_morse_capture(self):
        self.cancel_pc_pause_timers(); self.pc_morse_enabled = False; self.pc_space_pressed = False; self.pc_press_start = None; self.pc_current_symbol = ""; self.pc_decoded_text = ""; self.pc_morse_letters = []; self.pc_entry_var.set(""); self.update_morse_preview(); self.pc_morse_status_var.set("Morse PC: limpio/desactivado.")
    def cancel_pc_pause_timers(self):
        for attr in ["pc_letter_after_id", "pc_word_after_id"]:
            aid = getattr(self, attr)
            if aid is not None:
                try: self.after_cancel(aid)
                except Exception: pass
                setattr(self, attr, None)
    def on_pc_space_press(self, event):
        if not self.pc_morse_enabled: return None
        if self.pc_space_pressed: return "break"
        self.cancel_pc_pause_timers(); self.pc_space_pressed = True; self.pc_press_start = time.time(); return "break"
    def on_pc_space_release(self, event):
        if not self.pc_morse_enabled: return None
        if not self.pc_space_pressed or self.pc_press_start is None: return "break"
        duration = time.time() - self.pc_press_start; self.pc_space_pressed = False
        symbol = "." if duration < 2 * self.current_unit() else "-"
        self.pc_current_symbol += symbol; self.pc_morse_status_var.set(f"Morse PC: símbolo {symbol} | letra actual [{self.pc_current_symbol}]"); self.schedule_pc_pause_detection(); return "break"
    def schedule_pc_pause_detection(self):
        self.cancel_pc_pause_timers(); self.pc_letter_after_id = self.after(int(3*self.current_unit()*1000), self.finalize_pc_pending_letter); self.pc_word_after_id = self.after(int(7*self.current_unit()*1000), self.add_pc_word_space)
    def finalize_pc_pending_letter(self):
        if not self.pc_current_symbol: return
        letter = MORSE_TO_CHAR.get(self.pc_current_symbol, "?"); self.pc_decoded_text += letter; self.pc_morse_letters.append(self.pc_current_symbol); self.pc_current_symbol = ""
        self.pc_entry_var.set(self.pc_decoded_text); self.update_morse_preview(); self.pc_morse_status_var.set(f"Morse PC: letra '{letter}' agregada | Texto: {self.pc_decoded_text}")
    def add_pc_word_space(self):
        self.finalize_pc_pending_letter()
        if self.pc_decoded_text and not self.pc_decoded_text.endswith(" "):
            self.pc_decoded_text += " "; self.pc_entry_var.set(self.pc_decoded_text); self.update_morse_preview()
    def append_pc_char(self, ch): self.pc_entry_var.set(self.pc_entry_var.get() + ch); self.pc_decoded_text = self.pc_entry_var.get(); self.update_morse_preview()
    def clear_pc_entry(self): self.pc_entry_var.set(""); self.pc_decoded_text = ""; self.pc_current_symbol = ""; self.pc_morse_letters = []; self.update_morse_preview(); self.pc_morse_status_var.set("Morse PC: entrada limpia.")
    def update_morse_preview(self):
        text = normalize_text(self.pc_entry_var.get()); self.pc_entry_var.set(text); self.morse_preview_var.set(f"Morse: {text_to_morse(text) if text else '---'}")
    def update_score_label(self): self.score_var.set(f"Jugador A: {self.scores['A']} | Jugador B: {self.scores['B']}")
    def write_line(self, text): self.results_box.insert("end", text + "\n"); self.results_box.see("end")
    def write_result(self, label, result):
        inc_lines = []
        for ch in result["received_text"]:
            info = increment5_info(ch)
            if info:
                inc_lines.append(f"  {info['char']}: ASCII {info['ascii']} | ABCD {info['input_bits']} | +5 {info['result_bits']} ({info['result_value']}) | LEDs activos-bajo {invert_bits(info['result_bits'])}")
        inc_text = "\n".join(inc_lines) if inc_lines else "  No aplica"
        self.write_line(f"{label}\n  Respuesta: {result['received_text']}\n  Correctos: {result['correct_chars']}/{result['max_chars']}\n  Morse esperado: {result['expected_morse']}\n  Morse recibido: {result['received_morse'] or 'No aplica'}\n  Incrementador software:\n{inc_text}\n  Velocidad: {result['speed_level']} (+{result['speed_points']})\n  Puntaje: {result['score']}\n")

if __name__ == "__main__":
    app = StrangerTecApp()
    app.mainloop()
