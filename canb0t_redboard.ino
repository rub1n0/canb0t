#include <SPI.h>
#include <mcp_can.h>

// Change to true to enable OBD-II PID polling mode
const bool PID_MODE = false; // false = sniff mode, true = PID mode

// MCP2515 CS pin on SparkFun CAN-Bus Shield
const int CAN_CS = 10;
MCP_CAN CAN0(CAN_CS);

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

    Serial.print(F("ID: 0x"));
    Serial.print(canId, HEX);
    Serial.print(F(" DLC:"));
    Serial.print(len);
    Serial.print(F(" Data:"));
    for (int i = 0; i < len; i++) {
      Serial.print(' ');
      if (buf[i] < 0x10) Serial.print('0');
      Serial.print(buf[i], HEX);
    }
    Serial.println();
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
    if (CAN0.checkReceive() == CAN_MSGAVAIL) {
      CAN0.readMsgBuf(&len, buf);
      canId = CAN0.getCanId();

      Serial.print(F("RESP 0x"));
      Serial.print(canId, HEX);
      Serial.print(F(":"));
      for (int i = 0; i < len; i++) {
        Serial.print(' ');
        if (buf[i] < 0x10) Serial.print('0');
        Serial.print(buf[i], HEX);
      }
      Serial.println();
    } else {
      Serial.println(F("No response"));
    }
  } else {
    Serial.println(F("PID send failed"));
  }
}
