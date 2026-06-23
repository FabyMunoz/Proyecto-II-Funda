import network
import socket
import time
from machine import Pin, PWM

# WIFI
WIFI_SSID = "Faby"
WIFI_PASSWORD = "Fabi0612"
PC_HOST = "172.20.10.2"
PC_PORT = 8001

# PINES
PIN_BOTON = 11
PIN_SWITCH_MODO = 10
PIN_BUZZER = 12
PIN_SHIFT_DATA1 = 16
PIN_SHIFT_CLK1 = 17
PIN_SHIFT_DATA2 = 18
PIN_SHIFT_CLK2 = 19
PIN_SHIFT_CLEAR = 4
PIN_EXTRA1 = 13
PIN_EXTRA2 = 14
PIN_EXTRA3 = 15

# HARDWARE
button = Pin(PIN_BOTON, Pin.IN, Pin.PULL_UP)
switch_mode = Pin(PIN_SWITCH_MODO, Pin.IN, Pin.PULL_DOWN)

buzzer_pwm = PWM(Pin(PIN_BUZZER))
buzzer_pwm.freq(900)
buzzer_pwm.duty_u16(0)

shift_data1 = Pin(PIN_SHIFT_DATA1, Pin.OUT)
shift_clk1 = Pin(PIN_SHIFT_CLK1, Pin.OUT)
shift_data2 = Pin(PIN_SHIFT_DATA2, Pin.OUT)
shift_clk2 = Pin(PIN_SHIFT_CLK2, Pin.OUT)
shift_clear = Pin(PIN_SHIFT_CLEAR, Pin.OUT)
shift_clear.value(1)

extra_leds = [
    Pin(PIN_EXTRA1, Pin.OUT),
    Pin(PIN_EXTRA2, Pin.OUT),
    Pin(PIN_EXTRA3, Pin.OUT),
]

# MORSE
MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".",
    "F": "..-.", "G": "--.", "H": "....", "I": "..", "J": ".---",
    "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---",
    "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-",
    "U": "..-", "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--",
    "Z": "--..", "0": "-----", "1": ".----", "2": "..---",
    "3": "...--", "4": "....-", "5": ".....", "6": "-....",
    "7": "--...", "8": "---..", "9": "----.", "+": ".-.-.",
    "-": "-....-"
}

MORSE_TO_CHAR = {v: k for k, v in MORSE.items()}

MAPEO_LED = {
    "A": (0, 0), "B": (0, 1), "0": (0, 2),
    "C": (1, 0), "D": (1, 1), "1": (1, 2),
    "E": (2, 0), "F": (2, 1), "2": (2, 2),
    "G": (3, 0), "H": (3, 1), "3": (3, 2),
    "I": (4, 0), "J": (4, 1), "4": (4, 2),
    "K": (5, 0), "L": (5, 1), "5": (5, 2),
    "M": (6, 0), "N": (6, 1), "6": (6, 2),
    "O": (7, 0), "P": (7, 1), "7": (7, 2),
    "Q": (8, 0), "R": (8, 1), "8": (8, 2),
    "S": (9, 0), "T": (9, 1), "9": (9, 2),
    "U": (10, 0), "V": (10, 1), "-": (10, 2),
    "W": (11, 0), "X": (11, 1), "+": (11, 2),
    "Y": (12, 0), "Z": (12, 1),
}

# ESTADO
unit_s = 0.35
output_mode = "led"
game_mode = "listen"
sock = None
rx_buffer = b""
current_ip = ""

capturing = False
capture_start_ms = 0
captured_text = ""
captured_morse_letters = []
current_symbol = ""

button_was_pressed = False
press_start_ms = 0
last_release_ms = 0
letter_finalized = False
word_space_added = False
last_switch_state = None
last_send_ms = 0
debounce_ms = 50
last_button_change = 0

# SALIDAS
def buzzer_on():
    buzzer_pwm.duty_u16(5000)

def buzzer_off():
    buzzer_pwm.duty_u16(0)

def clock_pin(clk):
    clk.value(1)
    time.sleep_us(5)
    clk.value(0)
    time.sleep_us(5)

def shift_out(data_pin, clk_pin, bits):
    for i in range(len(bits) - 1, -1, -1):
        data_pin.value(bits[i])
        clock_pin(clk_pin)

def panel_clear():
    shift_clear.value(0)
    time.sleep_us(10)
    shift_clear.value(1)

    shift_out(shift_data1, shift_clk1, [0]*8)
    shift_out(shift_data2, shift_clk2, [0]*8)

    for led in extra_leds:
        led.value(0)

def output_register_and_extra(register_led, extra_led):
    bits1 = [0]*8
    bits2 = [0]*8

    mapa_reg1 = [0,1,2,3,7,6,5,4]
    mapa_reg2 = [0,1,2,3,4,5,6,7]

    if register_led < 8:
        bits2[mapa_reg1[register_led]] = 1
    else:
        bits1[mapa_reg2[register_led - 8]] = 1

    panel_clear()
    shift_out(shift_data1, shift_clk1, bits1)
    shift_out(shift_data2, shift_clk2, bits2)

    for i, led in enumerate(extra_leds):
        led.value(1 if i == extra_led else 0)

def panel_show_char(ch):
    ch = ch.upper()
    if ch not in MAPEO_LED:
        panel_clear()
        return

    register_led, extra_led = MAPEO_LED[ch]
    output_register_and_extra(register_led, extra_led)

def stop_all():
    buzzer_off()
    panel_clear()

# SOCKET
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)

    timeout = 20
    while not wlan.isconnected() and timeout > 0:
        print("Conectando WiFi...")
        time.sleep(1)
        timeout -= 1

    if not wlan.isconnected():
        raise RuntimeError("ERROR WIFI")

    print("WiFi conectado")
    print(wlan.ifconfig())
    return wlan.ifconfig()[0]

def connect_pc():
    global sock
    while True:
        try:
            s = socket.socket()
            s.connect((PC_HOST, PC_PORT))
            s.settimeout(0.02)
            sock = s
            print("Conectado a PC")
            return
        except Exception as exc:
            print("No se pudo conectar a PC:", exc)
            try:
                s.close()
            except:
                pass
            time.sleep(2)

def reconnect():
    global sock
    try:
        if sock:
            sock.close()
    except:
        pass
    sock = None
    connect_pc()
    send_hello()

def send_line(line):
    global sock
    if sock is None:
        return
    try:
        sock.send((line + "\n").encode())
    except Exception as exc:
        print("Error enviando:", exc)
        reconnect()

def send_hello():
    send_line("HELLO|{}".format(current_ip))

def poll_socket():
    global rx_buffer
    if sock is None:
        return

    try:
        data = sock.recv(256)
        if not data:
            reconnect()
            return

        rx_buffer += data

        while b"\n" in rx_buffer:
            line, rx_buffer = rx_buffer.split(b"\n", 1)
            line = line.strip()
            if line:
                handle_line(line.decode())

    except OSError:
        pass
    except Exception as exc:
        print("Error socket:", exc)
        reconnect()

def handle_line(line):
    global unit_s, output_mode, game_mode
    parts = line.split("|")
    mtype = parts[0] if parts else ""

    if mtype == "PING":
        send_line("PONG")

    elif mtype == "CONFIG":
        if len(parts) > 1:
            game_mode = parts[1]
        if len(parts) > 2:
            output_mode = parts[2]
        if len(parts) > 3:
            unit_s = float(parts[3])
        send_line("ACK|CONFIG")

    elif mtype == "PLAY":
        phrase = parts[1] if len(parts) > 1 else ""
        output = parts[2] if len(parts) > 2 else output_mode
        unit = float(parts[3]) if len(parts) > 3 else unit_s

        send_line("ACK|PLAY")
        play_phrase(phrase, output, unit)
        send_line("PLAY_DONE|{}".format(phrase))

    elif mtype == "START_CAPTURE":
        start_capture()

    elif mtype == "END_CAPTURE":
        finish_capture()

    elif mtype == "CLEAR":
        stop_all()
        send_line("ACK|CLEAR")

    else:
        send_line("ERROR|Comando no reconocido: {}".format(mtype))

# REPRODUCCION
def play_buzzer_phrase(text, unit):
    for ch in text.upper():
        if ch == " ":
            time.sleep(7 * unit)
            continue

        code = MORSE.get(ch, "")
        for symbol in code:
            buzzer_on()
            time.sleep(unit if symbol == "." else 3 * unit)
            buzzer_off()
            time.sleep(unit)

        time.sleep(2 * unit)

def play_led_phrase(text, unit):
    for ch in text.upper():
        if ch == " ":
            panel_clear()
            time.sleep(4 * unit)
            continue

        panel_show_char(ch)
        time.sleep(2 * unit)
        panel_clear()
        time.sleep(unit)

def play_phrase(text, output, unit):
    stop_all()
    if output == "buzzer":
        play_buzzer_phrase(text, unit)
    else:
        play_led_phrase(text, unit)
    stop_all()

# CAPTURA
def start_capture():
    global capturing, capture_start_ms, captured_text, captured_morse_letters
    global current_symbol, button_was_pressed, press_start_ms, last_release_ms
    global letter_finalized, word_space_added

    capturing = True
    capture_start_ms = time.ticks_ms()
    captured_text = ""
    captured_morse_letters = []
    current_symbol = ""
    button_was_pressed = False
    press_start_ms = 0
    last_release_ms = 0
    letter_finalized = False
    word_space_added = False

    send_line("ACK|START_CAPTURE")

def finish_capture():
    global capturing

    if current_symbol:
        decode_current_symbol()

    elapsed_ms = time.ticks_diff(time.ticks_ms(), capture_start_ms)
    capturing = False
    buzzer_off()

    send_line("INPUT_DONE|{}|{}|{}".format(
        captured_text.strip(),
        " ".join(captured_morse_letters),
        elapsed_ms
    ))

def decode_current_symbol():
    global current_symbol, captured_text, captured_morse_letters

    if not current_symbol:
        return

    ch = MORSE_TO_CHAR.get(current_symbol, "?")
    captured_text += ch
    captured_morse_letters.append(current_symbol)
    current_symbol = ""

    send_input_update()

def send_input_update():
    send_line("INPUT_UPDATE|{}|{}|{}".format(
        captured_text,
        " ".join(captured_morse_letters),
        current_symbol
    ))

# INPUT
def process_button():
    global button_was_pressed, press_start_ms, last_release_ms
    global current_symbol, letter_finalized, word_space_added, last_button_change

    if not capturing:
        buzzer_off()
        return

    now = time.ticks_ms()
    pressed = button.value() == 0

    if time.ticks_diff(now, last_button_change) < debounce_ms:
        return

    if pressed and not button_was_pressed:
        last_button_change = now
        button_was_pressed = True
        press_start_ms = now
        buzzer_on()

    elif not pressed and button_was_pressed:
        last_button_change = now
        button_was_pressed = False
        buzzer_off()

        duration = time.ticks_diff(now, press_start_ms)
        threshold = int(2 * unit_s * 1000)

        if duration < threshold:
            current_symbol += "."
        else:
            current_symbol += "-"

        last_release_ms = now
        letter_finalized = False
        word_space_added = False
        send_input_update()

    elif not pressed and last_release_ms != 0:
        gap = time.ticks_diff(now, last_release_ms)

        if (not letter_finalized) and gap >= int(3 * unit_s * 1000):
            decode_current_symbol()
            letter_finalized = True

        if (not word_space_added) and gap >= int(7 * unit_s * 1000):
            word_space_added = True

# SWITCH
def check_switch():
    global last_switch_state
    value = switch_mode.value()

    if last_switch_state is None:
        last_switch_state = value
        return

    if value != last_switch_state:
        last_switch_state = value
        send_line("SWITCH|{}".format("on" if value else "off"))

# MAIN
def main():
    global current_ip

    print("\n=== SISTEMA INICIANDO ===")
    current_ip = connect_wifi()
    connect_pc()
    send_hello()

    send_line("READY|{}".format(current_ip))

    panel_clear()
    print("Sistema listo")

    while True:
        poll_socket()
        process_button()
        check_switch()
        time.sleep_ms(10)

try:
    main()
except Exception as exc:
    stop_all()
    print("ERROR FATAL:", exc)