// CAN logging sketch for SparkFun RedBoard + CAN-Bus Shield
#include <SPI.h>
#include <SD.h>
#include <mcp_can.h>

// Change to true to enable OBD-II PID polling mode
const bool PID_MODE = false; // false = sniff mode, true = PID mode

// MCP2515 and SD card CS pins on SparkFun CAN-Bus Shield
const int CAN_CS = 10;
const int SD_CS  = 9;
MCP_CAN CAN0(CAN_CS);
File logFile;

// Buffer for incoming frames
unsigned long canId;
byte len;
byte buf[8];

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

  if (CAN0.begin(MCP_STDEXT, CAN_500KBPS, MCP_8MHZ) == CAN_OK) {
    Serial.println(F("CAN init ok"));
  } else {
    Serial.println(F("CAN init failed"));
    while (1) {
      delay(1000);
    }
  }

  CAN0.setMode(MCP_NORMAL);
}

void loop() {
  if (PID_MODE) {
    pollPids();
  } else {
    sniff();
  }
}

void sniff() {
  if (CAN0.checkReceive() == CAN_MSGAVAIL) {
    CAN0.readMsgBuf(&len, buf);
    canId = CAN0.getCanId();
    logFrame(canId, len, buf);
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

  if (CAN0.sendMsgBuf(reqId, 0, 8, data) == CAN_OK) {
    logFrame(reqId, 8, data);
    if (CAN0.checkReceive() == CAN_MSGAVAIL) {
      CAN0.readMsgBuf(&len, buf);
      canId = CAN0.getCanId();
      logFrame(canId, len, buf);
    } else {
      Serial.println(F("No response"));
    }
  } else {
    Serial.println(F("PID send failed"));
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
