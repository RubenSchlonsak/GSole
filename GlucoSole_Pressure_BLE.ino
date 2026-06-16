#include "Arduino.h"
#include "esp_adc/adc_oneshot.h"
#include <NimBLEDevice.h>

// ── Konfiguration ─────────────────────────────────────────
const int NUM_SENSORS = 6;

const int SENSOR_PINS[NUM_SENSORS] = { 1,  2,  4,  5,  6,  7};
const int SWITCH_PINS[NUM_SENSORS] = { 8,  9, 10, 11, 12, 13};

const adc_channel_t ADC_CHANNELS[NUM_SENSORS] = {
  ADC_CHANNEL_0,   // GPIO1
  ADC_CHANNEL_1,   // GPIO2
  ADC_CHANNEL_3,   // GPIO4
  ADC_CHANNEL_4,   // GPIO5
  ADC_CHANNEL_5,   // GPIO6
  ADC_CHANNEL_6    // GPIO7
};

const unsigned long INTERVAL = 20;   // ms pro Messung

// ── BLE UUIDs ─────────────────────────────────────────────
#define SERVICE_UUID "6f000001-b5a3-f393-e0a9-e50e24dcca9e"
#define DATA_UUID    "6f000002-b5a3-f393-e0a9-e50e24dcca9e"   // NOTIFY: Messwerte
#define CMD_UUID     "6f000003-b5a3-f393-e0a9-e50e24dcca9e"   // WRITE:  s / p
#define DEVICE_NAME  "GlucoSole-Pressure"

// ── Status ────────────────────────────────────────────────
bool          running         = false;
unsigned long lastMeasurement = 0;
bool          doResistive     = true;

adc_oneshot_unit_handle_t adc_handle = NULL;

NimBLEServer*         pServer      = nullptr;
NimBLECharacteristic* pDataChar    = nullptr;
volatile bool         bleConnected = false;
uint16_t              seqR = 0, seqC = 0;   // Paketzaehler je Typ (Drop-Erkennung)

// ── BLE Paket senden ──────────────────────────────────────
// Layout (Little-Endian, 28 Byte):
//   [0]    type   (0 = resistiv, 1 = kapazitiv)
//   [1]    count  (= NUM_SENSORS, Sanity-Check)
//   [2..3] seq    (uint16)
//   [4..]  6x uint32 Rohwerte
void sendPacket(uint8_t type, const uint32_t* vals) {
  if (!bleConnected || pDataChar == nullptr) return;

  uint8_t buf[4 + NUM_SENSORS * 4];   // 4 + 24 = 28
  buf[0] = type;
  buf[1] = NUM_SENSORS;
  uint16_t seq = (type == 0) ? seqR++ : seqC++;
  buf[2] = seq & 0xFF;
  buf[3] = (seq >> 8) & 0xFF;
  for (int i = 0; i < NUM_SENSORS; i++) {
    memcpy(buf + 4 + i * 4, &vals[i], 4);
  }

  pDataChar->setValue(buf, sizeof(buf));
  pDataChar->notify();
}

// ── BLE Callbacks ─────────────────────────────────────────
class ServerCB : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer* s, NimBLEConnInfo& info) override {
    bleConnected = true;
    Serial.println("[BLE] verbunden");
    // schnelleres Connection-Interval anfordern (7.5..15 ms) fuer hoeheren Durchsatz
    s->updateConnParams(info.getConnHandle(), 6, 12, 0, 100);
  }
  void onDisconnect(NimBLEServer* s, NimBLEConnInfo& info, int reason) override {
    bleConnected = false;
    Serial.println("[BLE] getrennt, Advertising neu");
    NimBLEDevice::startAdvertising();
  }
};

class CmdCB : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* c, NimBLEConnInfo& info) override {
    NimBLEAttValue v = c->getValue();
    if (v.length() == 0) return;
    char cmd = (char)v[0];
    if (cmd == 's' || cmd == 'S') { running = true;  Serial.println("[Status] Gestartet (BLE)"); }
    else if (cmd == 'p' || cmd == 'P') { running = false; Serial.println("[Status] Gestoppt (BLE)"); }
  }
};

void bleInit() {
  NimBLEDevice::init(DEVICE_NAME);
  NimBLEDevice::setMTU(247);   // Paket ist 28 Byte, braucht MTU > 31

  pServer = NimBLEDevice::createServer();
  pServer->setCallbacks(new ServerCB());

  NimBLEService* svc = pServer->createService(SERVICE_UUID);
  pDataChar = svc->createCharacteristic(DATA_UUID, NIMBLE_PROPERTY::NOTIFY);
  NimBLECharacteristic* cmdChar =
      svc->createCharacteristic(CMD_UUID, NIMBLE_PROPERTY::WRITE);
  cmdChar->setCallbacks(new CmdCB());
  svc->start();

  NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
  adv->setName(DEVICE_NAME);
  adv->addServiceUUID(SERVICE_UUID);
  adv->enableScanResponse(true);   // Name passt nicht neben die 128-Bit-UUID ins Haupt-Paket -> in Scan-Response
  NimBLEDevice::startAdvertising();
  Serial.println("[BLE] Advertising als \"" DEVICE_NAME "\"");
}

// ── ADC Init / Deinit ─────────────────────────────────────
void adcInit() {
  if (adc_handle != NULL) return;
  adc_oneshot_unit_init_cfg_t cfg = { .unit_id = ADC_UNIT_1 };
  adc_oneshot_new_unit(&cfg, &adc_handle);

  adc_oneshot_chan_cfg_t ch_cfg = {
    .atten    = ADC_ATTEN_DB_12,
    .bitwidth = ADC_BITWIDTH_12
  };
  for (int i = 0; i < NUM_SENSORS; i++) {
    adc_oneshot_config_channel(adc_handle, ADC_CHANNELS[i], &ch_cfg);
  }
}

void adcDeinit() {
  if (adc_handle == NULL) return;
  adc_oneshot_del_unit(adc_handle);
  adc_handle = NULL;
}

// ── Serielle Befehle (Fallback / Debug) ───────────────────
void handleSerial() {
  if (!Serial.available()) return;
  String cmd = Serial.readStringUntil('\n');
  cmd.trim(); cmd.toLowerCase();
  if      (cmd == "s") { running = true;  Serial.println("[Status] Gestartet"); }
  else if (cmd == "p") { running = false; Serial.println("[Status] Gestoppt");  }
  else Serial.println("[Fehler] s = Start  |  p = Stop");
}

// ── Resistive Messung (alle 6) ────────────────────────────
void measureResistive() {
  adcInit();
  for (int i = 0; i < NUM_SENSORS; i++) {
    pinMode(SWITCH_PINS[i], OUTPUT);
    digitalWrite(SWITCH_PINS[i], HIGH);
  }
  delayMicroseconds(300);

  uint32_t vals[NUM_SENSORS];
  Serial.print("[R] ");
  for (int i = 0; i < NUM_SENSORS; i++) {
    int raw = 0;
    adc_oneshot_read(adc_handle, ADC_CHANNELS[i], &raw);
    vals[i] = (uint32_t)raw;
    float v = raw / 4095.0f * 3.3f;
    Serial.printf("S%d:%4d(%.2fV) ", i + 1, raw, v);
  }
  Serial.println();
  sendPacket(0, vals);
}

// ── Kapazitive Messung (alle 6) ───────────────────────────
void measureCapacitive() {
  adcDeinit();
  for (int i = 0; i < NUM_SENSORS; i++) {
    pinMode(SWITCH_PINS[i], INPUT);    // High-Z
  }
  delay(5);

  uint32_t vals[NUM_SENSORS];
  Serial.print("[C] ");
  for (int i = 0; i < NUM_SENSORS; i++) {
    uint32_t t = touchRead(SENSOR_PINS[i]);
    vals[i] = t;
    Serial.printf("S%d:%lu ", i + 1, t);
  }
  Serial.println();
  sendPacket(1, vals);
}

// ── Setup ─────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(1000);

  for (int i = 0; i < NUM_SENSORS; i++) {
    pinMode(SWITCH_PINS[i], INPUT);
  }

  Serial.print("Touch initialisieren");
  for (int i = 0; i < 5; i++) {
    for (int j = 0; j < NUM_SENSORS; j++) {
      touchRead(SENSOR_PINS[j]);
    }
    delay(20);
    Serial.print(".");
  }
  Serial.println(" OK");

  bleInit();

  Serial.println("\n=== ESP32-S3 Druckmessung (6 Sensoren) ===");
  Serial.println("  s -> Start  |  p -> Stop   (Serial oder BLE)");
}

// ── Loop ──────────────────────────────────────────────────
void loop() {
  handleSerial();
  if (!running) return;
  if (millis() - lastMeasurement < INTERVAL) return;
  lastMeasurement = millis();

  if (doResistive) measureResistive();
  else             measureCapacitive();

  doResistive = !doResistive;
}
