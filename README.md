# GlucoSole Recorder, Bedienungsanleitung

Mit diesem Programm nimmst du die Druckdaten der GlucoSole-Sohle auf. Es zeigt die
sechs Sensoren live an und speichert alles in eine Tabelle (CSV). Du musst nichts
programmieren, nur ein paar Knöpfe drücken.

---

## Was du brauchst

- Einen Windows-PC mit Bluetooth
- Die GlucoSole-Sohle mit Strom (USB-Kabel oder Akku)
- Den Programm-Ordner (enthält `glucosole_recorder.py` und `start_glucosole.bat`)

---

## Teil A: Einmalig einrichten

Das macht idealerweise einmal jemand Technisches pro PC. Wenn der PC schon
vorbereitet ist, überspring diesen Teil und geh direkt zu Teil B.

1. **Python installieren**: auf https://www.python.org/downloads/ herunterladen und
   installieren. Wichtig: beim Setup unten den Haken **"Add Python to PATH"** setzen.
2. **Programm-Pakete installieren**: das Startmenü öffnen, `cmd` tippen, Enter, dann
   diese Zeile eingeben und Enter drücken:
   ```
   pip install bleak matplotlib numpy
   ```
3. Fertig. Das muss man nie wieder machen.

---

## Teil B: Bei jeder Messung

### 1. Sohle einschalten
Strom anstecken (USB oder Akku). Kurz warten, bis sie hochgefahren ist.

### 2. Programm starten
Doppelklick auf **`start_glucosole.bat`**. Es geht ein Fenster mit einer Fuß-Grafik
und Kurven auf.

### 3. Verbinden (passiert von selbst)
Oben links steht zuerst *"suche Geraet ..."*, kurz danach *"[verbunden]"*. Sobald
verbunden, färbt sich die Sohle und die Kurven laufen. Das kann ein paar Sekunden
dauern, einfach warten.

### 4. Aufnahme machen
1. Rechts bei **Session-Name** die Kennung eintippen, am besten die Probanden-ID,
   zum Beispiel `p01`.
2. Optional über **"Ordner waehlen ..."** festlegen, wohin gespeichert wird.
   Wenn du nichts änderst, landet alles im Unterordner `recordings`.
3. Auf **"Aufnahme starten"** klicken. Der Knopf heißt jetzt "Aufnahme stoppen", und
   oben siehst du mitlaufend die Anzahl der Messpunkte und die Dauer.
4. Die Messung durchführen.
5. Auf **"Aufnahme stoppen"** klicken. Die Datei wird automatisch gespeichert, unten
   rechts steht der Dateiname.

Für jeden Probanden eine eigene Aufnahme starten und stoppen.

### 5. Beenden
Einfach das Fenster schließen. Die laufende Aufnahme wird dabei sauber gespeichert.

---

## Wo liegen die Daten?

Im Unterordner **`recordings`** direkt neben dem Programm. Pro Aufnahme entsteht eine
Datei, benannt nach `Session-Name_Datum_Uhrzeit.csv`, zum Beispiel
`p01_20260815_143012.csv`. Diese Dateien kannst du normal kopieren, sichern oder an
Ruben schicken.

---

## Die Anzeige verstehen

- **Sohle (links)**: jeder Punkt ist ein Sensor. Dunkel heißt wenig Druck, hell heißt
  viel Druck. Die Zahl im Punkt ist der aktuelle Messwert.
- **Kurven (rechts)**: der Verlauf der letzten 10 Sekunden. Oben resistiv (das ist der
  Druck), unten kapazitiv.
- **Oben (Statuszeile)**: ob verbunden, die Datenrate in *Hz*, und *drops*. Kleine
  Drop-Zahlen sind normal und kein Grund zur Sorge.
- **"Fusskarte zeigt"** (rechts unten): Umschalter zwischen Resistiv und Kapazitiv.
  Für die normale Messung auf **Resistiv (Druck)** stehen lassen.

---

## Wenn etwas nicht klappt

**Es bleibt bei "suche Geraet ..." oder findet nichts:**
- Ist die Sohle wirklich an Strom und eingeschaltet?
- Ist am PC Bluetooth eingeschaltet?
- Hängt noch ein Handy oder Tablet an der Sohle? Die Sohle kann sich nur mit *einem*
  Gerät gleichzeitig verbinden. Eine offene BLE-App am Handy (z.B. nRF Connect)
  schließen, dann findet der PC sie.
- Programm schließen und neu starten (Doppelklick auf die .bat).

**Die Werte zappeln nur oder sehen komisch aus:**
- Wenn niemand auf der Sohle steht, sind die Werte erwartbar niedrig oder unruhig.
- Sitzt die Sohle richtig, sind alle Stecker dran? Im Zweifel Ruben fragen.

**Das Fenster reagiert beim Verbinden kurz nicht:**
- Normal. Ein paar Sekunden warten, dann läuft es.

Bei allem, was hier nicht steht: einen Screenshot machen (Statuszeile oben mit drauf)
und Ruben zeigen.

---

## Kurz-Checkliste pro Proband

- [ ] Sohle eingeschaltet
- [ ] Programm verbindet (oben steht "verbunden")
- [ ] Session-Name = Probanden-ID eingetragen
- [ ] "Aufnahme starten" gedrückt
- [ ] Messung durchgeführt
- [ ] "Aufnahme stoppen" gedrückt
- [ ] Datei im Ordner `recordings` vorhanden
