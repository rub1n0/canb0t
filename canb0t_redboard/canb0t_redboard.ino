// CAN logging sketch for SparkFun RedBoard + CAN-Bus Shield
#include <SPI.h>
#include <SD.h>
#include <Canbus.h>
#include <defaults.h>
#include <global.h>
#include <mcp2515.h>
#include <mcp2515_defs.h>

// Change to true to enable OBD-II PID polling mode
const bool PID_MODE = false; // false = sniff mode, true = PID mode

// SD card CS pin on SparkFun CAN-Bus Shield
const int SD_CS  = 9;
File logFile;

// OBD-II PID commands (service 01)
const unsigned char PID_RPM[8]      = {0x02, 0x01, 0x0C, 0, 0, 0, 0, 0};
const unsigned char PID_SPEED[8]    = {0x02, 0x01, 0x0D, 0, 0, 0, 0, 0};
const unsigned char PID_THROTTLE[8] = {0x02, 0x01, 0x11, 0, 0, 0, 0, 0};
const unsigned char PID_COOLANT[8]  = {0x02, 0x01, 0x05, 0, 0, 0, 0, 0};

void setup() {
  Serial.begin(115200);
  while (!Serial) {
    ; // wait for serial port to connect. Needed for native USB
  }

  Serial.println(F("canb0t :: SparkFun RedBoard CAN logger"));

  if (!SD.begin(SD_CS)) {
    Serial.println(F("SD init failed"));
    while (1) {
      delay(1000);
    }
  }

  logFile = SD.open("canlog.csv", FILE_WRITE);
  if (!logFile) {
    Serial.println(F("Log file open failed"));
    while (1) {
      delay(1000);
    }
  }
  logFile.println(F("timestamp_ms,id,dlc,data"));

  if (Canbus.init(CANSPEED_500)) {
    Serial.println(F("CAN init ok"));
  } else {
    Serial.println(F("CAN init failed"));
    while (1) {
      delay(1000);
    }
  }
}

void loop() {
  if (PID_MODE) {
    pollPids();
  } else {
    sniff();
  }
}

void sniff() {
  tCAN message;
  if (mcp2515_check_message()) {
    if (mcp2515_get_message(&message)) {
      logFrame(message.id, message.header.length, message.data);
    }
  }
}

void pollPids() {
  sendPid(PID_RPM);
  delay(100);
  sendPid(PID_SPEED);
  delay(100);
  sendPid(PID_THROTTLE);
  delay(100);
  sendPid(PID_COOLANT);
  delay(1000); // wait before repeating sequence
}

void sendPid(const unsigned char *data) {
  // Standard OBD-II request ID
  const unsigned long reqId = 0x7DF;

  tCAN txMsg;
  txMsg.id = reqId;
  txMsg.header.rtr = 0;
  txMsg.header.length = 8;
  for (int i = 0; i < 8; i++) {
    txMsg.data[i] = data[i];
  }
  mcp2515_send_message(&txMsg);
  logFrame(txMsg.id, txMsg.header.length, txMsg.data);

  delay(10);
  tCAN rxMsg;
  if (mcp2515_check_message()) {
    if (mcp2515_get_message(&rxMsg)) {
      logFrame(rxMsg.id, rxMsg.header.length, rxMsg.data);
    } else {
      Serial.println(F("No response"));
    }
  } else {
    Serial.println(F("No response"));
  }
}

void logFrame(unsigned long id, byte dlc, byte *data) {
  Serial.print(F("ID: 0x"));
  Serial.print(id, HEX);
  Serial.print(F(" DLC:"));
  Serial.print(dlc);
  Serial.print(F(" Data:"));
  for (int i = 0; i < dlc; i++) {
    Serial.print(' ');
    if (data[i] < 0x10) Serial.print('0');
    Serial.print(data[i], HEX);
  }
  Serial.println();

  unsigned long ts = millis();
  logFile.print(ts);
  logFile.print(',');
  logFile.print(id, HEX);
  logFile.print(',');
  logFile.print(dlc);
  logFile.print(',');
  for (int i = 0; i < dlc; i++) {
    if (i) logFile.print(' ');
    if (data[i] < 0x10) logFile.print('0');
    logFile.print(data[i], HEX);
  }
  logFile.println();
  logFile.flush();
}
