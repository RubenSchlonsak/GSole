#!/usr/bin/env python3
"""
GlucoSole Recorder
==================
Live-Visualisierung und Aufnahme der 6 Sohlen-Sensoren (resistiv + kapazitiv)
vom ESP32-S3 ueber BLE.

Features:
  - Sohlen-Ansicht: 6 Sensoren als Druck-Heatmap an ihren Positionen
  - rollende Zeitreihen (resistiv und kapazitiv, letzte 10 s)
  - CSV-Aufnahme mit Start/Stop, Session-Name und frei waehlbarem Ordner
  - Live-Statusleiste: Verbindung, Sample-Rate, verlorene Pakete
  - Stream-Steuerung (Start/Stop -> s/p an den ESP)

Installation:
    pip install bleak matplotlib numpy
    (tkinter ist bei Standard-Python unter Windows bereits dabei)

Start:
    python glucosole_recorder.py

CSV-Format (Long, eine Zeile pro Paket, da R und C versetzt ankommen):
    iso_time, t_ms, type(R/C), seq, s1..s6
Spaeter z.B. in pandas mit pivot auf 'type' trennen.

Sensorpositionen unten in SENSOR_POS an die reale Sohle anpassen.
"""

import asyncio
import struct
import threading
import queue
import time
import os
import csv
from collections import deque
from datetime import datetime

import numpy as np
from bleak import BleakScanner, BleakClient

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import tkinter as tk
from tkinter import ttk, filedialog

# ── Konfiguration ─────────────────────────────────────────
DEVICE_NAME = "GlucoSole-Pressure"
SERVICE_UUID = "6f000001-b5a3-f393-e0a9-e50e24dcca9e"
DATA_UUID   = "6f000002-b5a3-f393-e0a9-e50e24dcca9e"
CMD_UUID    = "6f000003-b5a3-f393-e0a9-e50e24dcca9e"
NUM        = 6
WINDOW_S   = 10.0     # Zeitfenster der Live-Plots in Sekunden
R_MAX      = 4095     # ADC-Vollausschlag (resistiv)

# Sensorpositionen auf der Sohle (rechter Fuss, Zehen oben).
# Koordinaten frei waehlbar, bitte an die echte Platzierung anpassen.
SENSOR_POS = [
    (5.0,  1.6),   # S1 Ferse
    (6.0,  4.5),   # S2 Mittelfuss lateral
    (3.6,  4.7),   # S3 Mittelfuss medial
    (3.6,  8.0),   # S4 Ballen innen (MTK1)
    (5.0,  8.6),   # S5 Ballen mitte
    (3.5, 10.6),   # S6 Grosszehe
]

# grobe Fuss-Silhouette (rechter Fuss)
FOOT_OUTLINE = [
    (5.0, 0.3), (3.4, 0.6), (2.7, 1.8), (2.6, 3.5), (2.9, 5.5),
    (2.7, 7.2), (2.8, 8.6), (3.2, 9.6), (3.0, 10.6), (3.2, 11.6),
    (3.9, 11.7), (4.2, 10.7), (4.9, 11.4), (5.2, 10.6), (5.6, 11.2),
    (5.8, 10.5), (6.2, 11.0), (6.4, 10.4), (6.7, 9.4), (6.9, 8.2),
    (7.0, 6.2), (6.7, 4.0), (6.3, 2.0), (5.9, 0.7),
]

# ── Zeitbasis ─────────────────────────────────────────────
T0 = time.perf_counter()
def now():
    return time.perf_counter() - T0

# ── gemeinsamer Zustand (BLE-Thread <-> GUI) ──────────────
state_lock = threading.Lock()
latest   = {0: [0] * NUM, 1: [0] * NUM}                    # 0=resistiv, 1=kapazitiv
hist     = {0: [deque() for _ in range(NUM)],              # je (t, wert)
            1: [deque() for _ in range(NUM)]}
seq_prev = {0: None, 1: None}
drops    = 0
recv_times = deque()                                       # Paketzeiten (fuer Hz)
status   = {"connected": False, "msg": "suche Geraet ..."}
stop_event = threading.Event()
cmd_queue  = queue.Queue()

# ── Aufnahme ──────────────────────────────────────────────
record_lock = threading.Lock()
rec = {"active": False, "writer": None, "file": None,
       "count": 0, "t0": None, "path": None}


def parse_packet(data: bytes):
    """28-Byte-Paket <B B H 6I> zerlegen, Zustand und ggf. CSV aktualisieren."""
    global drops
    if len(data) < 28:
        return
    typ, cnt, seq = struct.unpack_from("<BBH", data, 0)
    vals = struct.unpack_from("<6I", data, 4)
    if typ not in (0, 1):
        return

    tnow = now()
    with state_lock:
        latest[typ] = list(vals)
        cutoff = tnow - WINDOW_S
        for i in range(NUM):
            dq = hist[typ][i]
            dq.append((tnow, vals[i]))
            while dq and dq[0][0] < cutoff:
                dq.popleft()
        prev = seq_prev[typ]
        if prev is not None:
            exp = (prev + 1) & 0xFFFF
            if seq != exp:
                drops += (seq - exp) & 0xFFFF
        seq_prev[typ] = seq
        recv_times.append(tnow)
        c1 = tnow - 1.0
        while recv_times and recv_times[0] < c1:
            recv_times.popleft()

    with record_lock:
        if rec["active"] and rec["writer"] is not None:
            t_ms = (time.perf_counter() - rec["t0"]) * 1000.0
            rec["writer"].writerow([
                datetime.now().isoformat(timespec="milliseconds"),
                f"{t_ms:.1f}", "R" if typ == 0 else "C", seq, *vals
            ])
            rec["count"] += 1


def start_recording(session: str, folder: str) -> str:
    with record_lock:
        if rec["active"]:
            return rec["path"]
        os.makedirs(folder, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = "".join(ch for ch in session if ch.isalnum() or ch in "-_") or "session"
        path = os.path.join(folder, f"{safe}_{ts}.csv")
        f = open(path, "w", newline="")
        w = csv.writer(f)
        w.writerow(["iso_time", "t_ms", "type", "seq"] + [f"s{i+1}" for i in range(NUM)])
        rec.update(active=True, writer=w, file=f, count=0,
                   t0=time.perf_counter(), path=path)
        return path


def stop_recording():
    with record_lock:
        if not rec["active"]:
            return None
        path = rec["path"]
        try:
            rec["file"].flush()
            rec["file"].close()
        except Exception:
            pass
        rec.update(active=False, writer=None, file=None)
        return path


# ── BLE-Schleife (eigener Thread) ─────────────────────────
async def find_device(timeout=10):
    """Sucht das Geraet ueber den Namen ODER die Service-UUID (robuster)."""
    devs = await BleakScanner.discover(timeout=timeout, return_adv=True)
    for d, adv in devs.values():
        name = adv.local_name or d.name or ""
        uuids = [u.lower() for u in (adv.service_uuids or [])]
        if name == DEVICE_NAME or SERVICE_UUID.lower() in uuids:
            return d
    return None


async def ble_loop():
    while not stop_event.is_set():
        with state_lock:
            status["msg"] = "suche Geraet ..."
        dev = await find_device(timeout=10)
        if dev is None:
            with state_lock:
                status["msg"] = "nicht gefunden, neuer Versuch ..."
            continue
        try:
            async with BleakClient(dev) as client:
                with state_lock:
                    status["connected"] = True
                    status["msg"] = f"verbunden ({dev.address})"
                await client.start_notify(DATA_UUID, lambda _, d: parse_packet(bytes(d)))
                await client.write_gatt_char(CMD_UUID, b"s", response=False)

                while client.is_connected and not stop_event.is_set():
                    try:
                        while True:
                            c = cmd_queue.get_nowait()
                            await client.write_gatt_char(CMD_UUID, c, response=False)
                    except queue.Empty:
                        pass
                    await asyncio.sleep(0.1)

                try:
                    await client.write_gatt_char(CMD_UUID, b"p", response=False)
                except Exception:
                    pass
        except Exception as e:
            with state_lock:
                status["msg"] = f"Verbindungsfehler: {e}"
        finally:
            with state_lock:
                status["connected"] = False


def start_ble_thread():
    threading.Thread(target=lambda: asyncio.run(ble_loop()), daemon=True).start()


# ── GUI ───────────────────────────────────────────────────
class App:
    def __init__(self, root):
        self.root = root
        root.title("GlucoSole Recorder")
        root.geometry("1180x680")
        root.minsize(960, 560)
        self.map_source = tk.IntVar(value=0)            # 0=resistiv, 1=kapazitiv
        self.folder = os.path.abspath("recordings")

        self._build_controls()
        self._build_figure()
        start_ble_thread()
        self._tick()
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # --- Steuerleiste rechts + Status oben ---
    def _build_controls(self):
        top = ttk.Frame(self.root, padding=6)
        top.pack(side=tk.TOP, fill=tk.X)
        self.lbl_status = ttk.Label(top, text="...", font=("Segoe UI", 10, "bold"))
        self.lbl_status.pack(side=tk.LEFT)

        main = ttk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True)

        self.plot_frame = ttk.Frame(main)
        self.plot_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        side = ttk.Frame(main, padding=10, width=270)
        side.pack(side=tk.RIGHT, fill=tk.Y)
        side.pack_propagate(False)

        ttk.Label(side, text="Aufnahme", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(side, text="Session-Name:").pack(anchor="w", pady=(4, 0))
        self.ent_name = ttk.Entry(side)
        self.ent_name.insert(0, "proband01")
        self.ent_name.pack(fill=tk.X)
        ttk.Button(side, text="Ordner waehlen ...", command=self.choose_folder).pack(fill=tk.X, pady=(6, 2))
        self.lbl_folder = ttk.Label(side, text=self.folder, wraplength=240, foreground="#666")
        self.lbl_folder.pack(anchor="w")
        self.btn_rec = ttk.Button(side, text="Aufnahme starten", command=self.toggle_record)
        self.btn_rec.pack(fill=tk.X, pady=(8, 2))
        self.lbl_rec = ttk.Label(side, text="bereit", foreground="#444")
        self.lbl_rec.pack(anchor="w")

        ttk.Separator(side).pack(fill=tk.X, pady=10)

        ttk.Label(side, text="Stream", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        fr = ttk.Frame(side)
        fr.pack(fill=tk.X, pady=2)
        ttk.Button(fr, text="Start (s)", command=lambda: cmd_queue.put(b"s")).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(fr, text="Stop (p)", command=lambda: cmd_queue.put(b"p")).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        ttk.Separator(side).pack(fill=tk.X, pady=10)

        ttk.Label(side, text="Fusskarte zeigt", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Radiobutton(side, text="Resistiv (Druck)", variable=self.map_source, value=0).pack(anchor="w")
        ttk.Radiobutton(side, text="Kapazitiv", variable=self.map_source, value=1).pack(anchor="w")

    def choose_folder(self):
        d = filedialog.askdirectory(initialdir=self.folder)
        if d:
            self.folder = d
            self.lbl_folder.config(text=d)

    def toggle_record(self):
        with record_lock:
            active = rec["active"]
        if active:
            path = stop_recording()
            self.btn_rec.config(text="Aufnahme starten")
            self.lbl_rec.config(text=f"gespeichert: {os.path.basename(path) if path else '-'}")
        else:
            path = start_recording(self.ent_name.get().strip(), self.folder)
            self.btn_rec.config(text="Aufnahme stoppen")
            self.lbl_rec.config(text=f"laeuft: {os.path.basename(path)}")

    # --- Matplotlib-Figur ---
    def _build_figure(self):
        self.fig = Figure(figsize=(9, 6), dpi=100)
        gs = self.fig.add_gridspec(2, 2, width_ratios=[1.1, 1.4], height_ratios=[1, 1])
        self.ax_foot = self.fig.add_subplot(gs[:, 0])
        self.ax_r = self.fig.add_subplot(gs[0, 1])
        self.ax_c = self.fig.add_subplot(gs[1, 1])

        fx = [p[0] for p in FOOT_OUTLINE] + [FOOT_OUTLINE[0][0]]
        fy = [p[1] for p in FOOT_OUTLINE] + [FOOT_OUTLINE[0][1]]
        self.ax_foot.fill(fx, fy, color="#e9edf2", zorder=0)
        self.ax_foot.plot(fx, fy, color="#9aa6b2", lw=1.2, zorder=1)

        xs = [p[0] for p in SENSOR_POS]
        ys = [p[1] for p in SENSOR_POS]
        self.scat = self.ax_foot.scatter(xs, ys, c=[0] * NUM, cmap="inferno",
                                         vmin=0, vmax=R_MAX, s=900,
                                         edgecolors="k", linewidths=1.0, zorder=3)
        self.cbar = self.fig.colorbar(self.scat, ax=self.ax_foot, fraction=0.046, pad=0.04)
        self.val_txt = [self.ax_foot.text(xs[i], ys[i], "0", ha="center", va="center",
                                          color="w", fontsize=9, fontweight="bold", zorder=4)
                        for i in range(NUM)]
        for i, (x, y) in enumerate(SENSOR_POS):
            self.ax_foot.text(x, y - 0.95, f"S{i+1}", ha="center", va="center",
                              fontsize=8, color="#333", zorder=4)
        self.ax_foot.set_aspect("equal")
        self.ax_foot.axis("off")
        self.ax_foot.set_xlim(1.5, 7.5)
        self.ax_foot.set_ylim(-0.6, 12.6)
        self.ax_foot.set_title("Sohle (Live-Druck)")

        self.lines_r = [self.ax_r.plot([], [], lw=1.2, label=f"S{i+1}")[0] for i in range(NUM)]
        self.ax_r.set_xlim(-WINDOW_S, 0)
        self.ax_r.set_ylim(0, R_MAX)
        self.ax_r.set_title("Resistiv (ADC roh)")
        self.ax_r.grid(alpha=0.3)
        self.ax_r.legend(loc="upper left", ncol=3, fontsize=7)

        self.lines_c = [self.ax_c.plot([], [], lw=1.2)[0] for i in range(NUM)]
        self.ax_c.set_xlim(-WINDOW_S, 0)
        self.ax_c.set_ylim(0, 1000)
        self.ax_c.set_title("Kapazitiv (touchRead roh)")
        self.ax_c.set_xlabel("Sekunden")
        self.ax_c.grid(alpha=0.3)

        self.fig.tight_layout()
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.plot_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # --- periodisches Update ---
    def _tick(self):
        if stop_event.is_set():
            return
        with state_lock:
            src = self.map_source.get()
            sval = list(latest[src])
            tnow = now()
            hr = [list(hist[0][i]) for i in range(NUM)]
            hc = [list(hist[1][i]) for i in range(NUM)]
            rate = len(recv_times)
            d = drops
            st = dict(status)

        # Fusskarte
        self.scat.set_array(np.array(sval, dtype=float))
        if src == 0:
            self.scat.set_clim(0, R_MAX)
        else:
            m = max(sval) if max(sval) > 0 else 1
            self.scat.set_clim(0, m)
        for i in range(NUM):
            self.val_txt[i].set_text(str(sval[i]))
        self.ax_foot.set_title("Sohle (Live " + ("Druck/Resistiv" if src == 0 else "Kapazitiv") + ")")

        # Zeitreihen resistiv
        for i in range(NUM):
            if hr[i]:
                self.lines_r[i].set_data([t - tnow for (t, _) in hr[i]],
                                         [v for (_, v) in hr[i]])
            else:
                self.lines_r[i].set_data([], [])
        # Zeitreihen kapazitiv (Autoskala)
        cmax = 1
        for i in range(NUM):
            if hc[i]:
                vs = [v for (_, v) in hc[i]]
                self.lines_c[i].set_data([t - tnow for (t, _) in hc[i]], vs)
                cmax = max(cmax, max(vs))
            else:
                self.lines_c[i].set_data([], [])
        self.ax_c.set_ylim(0, cmax * 1.25)

        # Statuszeile
        conn = "verbunden" if st["connected"] else "getrennt"
        with record_lock:
            ra = rec["active"]
            rcount = rec["count"]
            rt0 = rec["t0"]
        rtxt = ""
        if ra:
            dur = (time.perf_counter() - rt0) if rt0 else 0.0
            rtxt = f"  |  REC {rcount} Samples, {dur:0.1f} s"
            self.lbl_rec.config(text=f"laeuft: {rcount} Samples")
        self.lbl_status.config(
            text=f"[{conn}] {st['msg']}   |   {rate} Hz   |   drops: {d}{rtxt}")

        self.canvas.draw_idle()
        self.root.after(60, self._tick)

    def on_close(self):
        stop_event.set()
        stop_recording()
        cmd_queue.put(b"p")
        self.root.after(200, self.root.destroy)


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
