#include <Arduino.h>
#include <HX711_ADC.h> // MODIFIED: Replaced Adafruit_ADS1X15.h

//========================================================================================
// == SENSOR CONFIGURATION (SML Load Cell with HX711) ==
//========================================================================================
// NEW: Define HX711 pins
const int HX711_DOUT_PIN = 24;
const int HX711_SCK_PIN = 22;

// NEW: Create an instance of the HX711 library
HX711_ADC LoadCell(HX711_DOUT_PIN, HX711_SCK_PIN);

//========================================================================================
// == MOTOR & SYSTEM CONFIGURATION ==
//========================================================================================
// -- Limit Switch Pins --
const int SWITCH_A_PIN = 2;  // Start/Home position switch
const int SWITCH_B_PIN = 3; // End position switch

// -- Motor Settings --
const byte HOMING_SPEED_BYTE = 5;
const byte MOTOR_STOP = 128;
const float MAX_MOTOR_RPM = 143.0;
byte g_trialSpeedByte = 168; // Default speed

// -- Serial Port Definitions --
#define PC_SERIAL Serial
#define MD49_SERIAL Serial3

// -- MD49 Command Definitions --
#define MD49_SYNC_BYTE      (byte)0x00
#define MD49_SET_SPEED1     0x31
#define MD49_GET_ENCODER1   0x23
#define MD49_RESET_ENCODERS 0x35

// == State Machine Definition ==
enum State { HW_TEST, IDLE, HOMING, TRIAL_RUNNING };
State currentState = HW_TEST;

//========================================================================================
// == FUNCTION PROTOTYPES ==
//========================================================================================
void stopMotor();
void resetEncoders();
void pollAndSendData();

//========================================================================================
// == SETUP FUNCTION ==
//========================================================================================
void setup() {
  PC_SERIAL.begin(9600);
  MD49_SERIAL.begin(9600);

  pinMode(SWITCH_A_PIN, INPUT_PULLUP);
  pinMode(SWITCH_B_PIN, INPUT_PULLUP);

  // MODIFIED: Initialize the HX711
  LoadCell.begin();
  LoadCell.setCalFactor(1.0f); // NEW: Set cal factor to 1.0 to get tared ADC counts
  // We will tare the sensor after the hardware test is complete.
  
  PC_SERIAL.println("HW_TEST_REQUIRED");
}
//========================================================================================
// == MAIN LOOP ==
//========================================================================================
void loop() {
  // The switch statement below intentionally does not handle HW_TEST
  // as it's the default state managed by serial commands.
  switch (currentState) {
    case HOMING:
      if (digitalRead(SWITCH_A_PIN) == LOW) {
        stopMotor();
        PC_SERIAL.println("Homing complete.");
        delay(100);
        resetEncoders();
        delay(10);
        MD49_SERIAL.write(MD49_SYNC_BYTE);
        MD49_SERIAL.write(MD49_SET_SPEED1);
        MD49_SERIAL.write(g_trialSpeedByte);
        currentState = TRIAL_RUNNING;
      }
      break;

    case TRIAL_RUNNING:
      pollAndSendData();
      if (digitalRead(SWITCH_B_PIN) == LOW) {
        stopMotor();
        PC_SERIAL.println("Trial complete: End switch reached.");
        currentState = IDLE;
      }
      break;

    case IDLE:
      // Do nothing while idle
      break;
  }

  if (PC_SERIAL.available() > 0) {
    char command = PC_SERIAL.read();
    switch (command) {
      case 'a':
        if (currentState == IDLE) {
          PC_SERIAL.println("COMMAND: Starting automated trial...");
          MD49_SERIAL.write(MD49_SYNC_BYTE);
          MD49_SERIAL.write(MD49_SET_SPEED1);
          MD49_SERIAL.write(HOMING_SPEED_BYTE);
          currentState = HOMING;
        }
        break;
      
      case 't':
        if (currentState == IDLE) {
          String rpmString = PC_SERIAL.readStringUntil('\n');
          float targetRPM = rpmString.toFloat();
          if (targetRPM >= 0 && targetRPM <= MAX_MOTOR_RPM) {
            byte speedOffset = (byte)((targetRPM / MAX_MOTOR_RPM) * 127.0);
            g_trialSpeedByte = 128 + speedOffset;
            PC_SERIAL.print("COMMAND: New trial speed byte set to ");
            PC_SERIAL.println(g_trialSpeedByte);
          }
        }
        break;

      case 'R': // Read SML Sensor for calibration
        if (currentState == IDLE) {
          // MODIFIED: Manually average readings using the correct API calls
          long reading_sum = 0;
          const int samples = 10;
          for (int i = 0; i < samples; i++) {
            LoadCell.update();
            reading_sum += LoadCell.getData();
          }
          long avg_reading = reading_sum / samples;
          PC_SERIAL.print("ADC_VAL:");
          PC_SERIAL.println(avg_reading);
        }
        break;
      
      case 'c':
        if (currentState == HW_TEST) {
          bool switchA_state = (digitalRead(SWITCH_A_PIN) == LOW);
          bool switchB_state = (digitalRead(SWITCH_B_PIN) == LOW);
          PC_SERIAL.print("S:");
          PC_SERIAL.print(switchA_state);
          PC_SERIAL.print(switchB_state);
          PC_SERIAL.println();
        }
        break;
      
      case 'e':
        if (currentState == HW_TEST) {
          currentState = IDLE;
          PC_SERIAL.println("Performing initial tare...");
          PC_SERIAL.println("Arduino Initialized. Ready for commands.");
        }
        break;
      
      // NEW: Command to re-tare the scale
      case 'z':
        if (currentState == IDLE) {
            PC_SERIAL.println("Taring function removed -- doing nothing");
        }
        break;

      case 'x':
        stopMotor();
        if (currentState != HW_TEST) {
            currentState = IDLE;
        }
        PC_SERIAL.println("COMMAND: Emergency Stop activated.");
        break;
    }
  }
}

//========================================================================================
// == HELPER FUNCTIONS ==
//========================================================================================

void stopMotor() {
  MD49_SERIAL.write(MD49_SYNC_BYTE);
  MD49_SERIAL.write(MD49_SET_SPEED1);
  MD49_SERIAL.write(MOTOR_STOP);
}

void resetEncoders() {
  MD49_SERIAL.write(MD49_SYNC_BYTE);
  MD49_SERIAL.write(MD49_RESET_ENCODERS);
}

// --- Binary Data Packet Definition ---
struct DataPacket {
  uint32_t timestamp;
  int32_t encoder_val;
  int32_t sml_raw_adc; // MODIFIED: Changed from int16_t to int32_t for 24-bit data
} __attribute__((packed));

void pollAndSendData() {
  // 1. Get SML Raw ADC Value
  // MODIFIED: First update the sensor, then get the data
  LoadCell.update();
  long raw_adc = (long)LoadCell.getData();

  // 2. Get Encoder Value
  long encoder_val = 0;
  MD49_SERIAL.write(MD49_SYNC_BYTE);
  MD49_SERIAL.write(MD49_GET_ENCODER1);
  unsigned long startTime = millis();
  while (MD49_SERIAL.available() < 4) {
    if (millis() - startTime > 50) { break; } // Timeout
  }
  if (MD49_SERIAL.available() >= 4) {
    byte b1 = MD49_SERIAL.read(); byte b2 = MD49_SERIAL.read();
    byte b3 = MD49_SERIAL.read(); byte b4 = MD49_SERIAL.read();
    encoder_val = ((long)b1 << 24) | ((long)b2 << 16) | ((long)b3 << 8) | (long)b4;
  }
  
  // 3. Construct and send binary packet
  DataPacket packet;
  packet.timestamp = millis();
  packet.encoder_val = encoder_val;
  packet.sml_raw_adc = raw_adc;

  PC_SERIAL.write('>'); // Start byte
  PC_SERIAL.write((uint8_t*)&packet, sizeof(packet));
  PC_SERIAL.write('<'); // End byte
}
