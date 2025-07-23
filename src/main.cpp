#include <Arduino.h>
#include <math.h> // Needed for PI constant

/*****************************************************************************************
 * MD49 Motor Driver Control for Friction Characterization Experiment
 * ---------------------------------------------------------------------------------------
 * Author: Catie Balasubramanian
 * Date: July 10, 2025
 *
 * Description:
 * This script runs on an Arduino Mega to control an EMG49 motor via an MD49 driver.
 *
 * REVISION: This version fixes a logic bug in the command handler that prevented
 * commands from being processed after the hardware self-test was completed. The command
 * handler is now a single, unified switch statement for robustness.
 *
 *****************************************************************************************/

//========================================================================================
// == CONFIGURATION PARAMETERS ==
//========================================================================================

// -- Failsafe Physical Parameters --
const float RAIL_LENGTH_MM = 150.0;       // Max travel distance from switch A to B
const float LEAD_SCREW_TPI = 12.0;        // Threads Per Inch of the lead screw
const float INCH_TO_MM = 25.4;            // Conversion factor for inches to millimeters
const float MAX_MOTOR_RPM = 143.0;        // From motor datasheet (No load speed)

// -- Trial Settings --
const unsigned long MANUAL_TRIAL_DURATION_MS = 60000; // Duration for manual trial (60s).

// -- Limit Switch Pins --
const int SWITCH_A_PIN = 2;  // Start/Home position switch
const int SWITCH_B_PIN = 45; // End position switch

// -- Motor Settings --
const byte HOMING_SPEED_BYTE = 5;
byte g_trialSpeedByte = 168;
const byte MOTOR_STOP = 128;
const byte ACCELERATION = 5;

// -- Serial Port Definitions --
#define PC_SERIAL Serial
#define MD49_SERIAL Serial1

// -- MD49 Command Definitions --
#define MD49_SYNC_BYTE      (byte)0x00
#define MD49_SET_SPEED1     0x31
#define MD49_SET_ACCEL      0x33
#define MD49_SET_MODE       0x34
#define MD49_RESET_ENCODERS 0x35
#define MD49_ENABLE_REG     0x37
#define MD49_DISABLE_TOUT   0x38
#define MD49_GET_ENCODER1   0x23
#define MD49_GET_CURRENT1   0x27
#define MD49_GET_VOLTS      0x26
#define MD49_GET_ERROR      0x2D

// == State Machine Definition ==
enum State {
  HW_TEST, // Initial state, waits for GUI to complete switch tests
  IDLE,
  HOMING,
  TRIAL_RUNNING,
  MANUAL_TRIAL_RUNNING
};
State currentState = HW_TEST; // Start in hardware test mode
unsigned long manualTrialStartTime = 0;

// -- Failsafe Timer Variables --
unsigned long stateStartTime = 0;
unsigned long currentTimeoutDuration = 0;


//========================================================================================
// == FUNCTION PROTOTYPES ==
//========================================================================================
void configureMd49();
void stopMotor();
void resetEncoders();
void printInstructions();
void pollAndSendData();
unsigned long calculateTimeout(byte speedByte);


//========================================================================================
// == SETUP FUNCTION ==
//========================================================================================

void setup() {
  PC_SERIAL.begin(9600);
  while (!PC_SERIAL) { ; }

  MD49_SERIAL.begin(9600);

  pinMode(SWITCH_A_PIN, INPUT_PULLUP);
  pinMode(SWITCH_B_PIN, INPUT_PULLUP);

  configureMd49();

  // Tell the GUI that a hardware test is required before proceeding.
  PC_SERIAL.println("HW_TEST_REQUIRED");
}


//========================================================================================
// == REVISED MAIN LOOP (NON-BLOCKING) ==
//========================================================================================

void loop() {
  // --- Part 1: State Machine Logic (only runs when NOT in hardware test mode) ---
  if (currentState != HW_TEST) {
    switch (currentState) {
      case IDLE:
        break;

      case HOMING:
        if (digitalRead(SWITCH_A_PIN) == LOW) {
          stopMotor();
          PC_SERIAL.println("Homing complete. Switch A reached.");
          delay(500);
          resetEncoders();
          delay(10);
          
          PC_SERIAL.println("Trial Running: Moving to Switch B (end position)...");
          currentTimeoutDuration = calculateTimeout(g_trialSpeedByte);
          stateStartTime = millis();

          MD49_SERIAL.write(MD49_SYNC_BYTE);
          MD49_SERIAL.write(MD49_SET_SPEED1);
          MD49_SERIAL.write(g_trialSpeedByte);
          currentState = TRIAL_RUNNING;
        }
        else if (millis() - stateStartTime > currentTimeoutDuration) {
          stopMotor();
          PC_SERIAL.println("ERROR: Timeout: Check your limit switches");
          currentState = IDLE;
        }
        break;

      case TRIAL_RUNNING:
        if (digitalRead(SWITCH_B_PIN) == LOW) {
          stopMotor();
          PC_SERIAL.println("Trial complete. Switch B reached.");
          currentState = IDLE;
        }
        else if (millis() - stateStartTime > currentTimeoutDuration) {
          stopMotor();
          PC_SERIAL.println("ERROR: Timeout: Check your limit switches");
          currentState = IDLE;
        }
        break;

      case MANUAL_TRIAL_RUNNING:
        if (millis() - manualTrialStartTime >= MANUAL_TRIAL_DURATION_MS) {
          stopMotor();
          PC_SERIAL.println("Manual trial complete.");
          currentState = IDLE;
        }
        break;
    }
  }

  // --- Part 2: Command Handler (always listening for PC commands) ---
  if (PC_SERIAL.available() > 0) {
    char command = PC_SERIAL.read();

    // A single, unified switch statement to handle all commands
    switch (command) {
      // --- Normal Operation Commands (ignored during HW Test) ---
      case 'a':
        if (currentState == IDLE) {
          PC_SERIAL.println("COMMAND: Starting new automated trial...");
          currentTimeoutDuration = calculateTimeout(HOMING_SPEED_BYTE);
          stateStartTime = millis();
          MD49_SERIAL.write(MD49_SYNC_BYTE);
          MD49_SERIAL.write(MD49_SET_SPEED1);
          MD49_SERIAL.write(HOMING_SPEED_BYTE);
          currentState = HOMING;
        }
        break;
      case 's':
        if (currentState == IDLE) {
          PC_SERIAL.println("COMMAND: Starting manual 60-second trial...");
          resetEncoders();
          delay(10);
          MD49_SERIAL.write(MD49_SYNC_BYTE);
          MD49_SERIAL.write(MD49_SET_SPEED1);
          MD49_SERIAL.write(g_trialSpeedByte);
          manualTrialStartTime = millis();
          currentState = MANUAL_TRIAL_RUNNING;
        }
        break;
      case 't':
        if (currentState == IDLE) {
          String rpmString = PC_SERIAL.readStringUntil('\n');
          float targetRPM = rpmString.toFloat();
          if (targetRPM >= 0 && targetRPM <= MAX_MOTOR_RPM) {
            byte speedOffset = (byte)((targetRPM / MAX_MOTOR_RPM) * 127.0);
            g_trialSpeedByte = 128 + speedOffset;
            PC_SERIAL.print("COMMAND: New trial RPM set to ");
            PC_SERIAL.print(targetRPM);
            PC_SERIAL.print(" (Speed Byte: ");
            PC_SERIAL.print(g_trialSpeedByte);
            PC_SERIAL.println(")");
          } else {
            PC_SERIAL.println("ERROR: Invalid RPM.");
          }
        }
        break;
      case 'p':
        if (currentState != HW_TEST) {
          pollAndSendData();
        }
        break;

      // --- Hardware Test Commands (only work during HW Test) ---
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
          printInstructions(); // Print normal instructions now
        }
        break;

      // --- Global Commands (work in any state) ---
      case 'x':
        PC_SERIAL.println("COMMAND: Emergency Stop!");
        stopMotor();
        if (currentState != HW_TEST) {
            currentState = IDLE;
        }
        break;
      case 'r':
        PC_SERIAL.println("COMMAND: Resetting encoder count.");
        resetEncoders();
        break;
    }
  }
}


//========================================================================================
// == HELPER FUNCTIONS ==
//========================================================================================

unsigned long calculateTimeout(byte speedByte) {
    float speedRatio = 0.0;
    if (speedByte > 128) {
        speedRatio = (float)(speedByte - 128) / 127.0;
    } else if (speedByte < 128) {
        speedRatio = (float)(128 - speedByte) / 128.0;
    }

    if (speedRatio > 0) {
        float motorRPM = speedRatio * MAX_MOTOR_RPM;
        float motorRPS = motorRPM / 60.0;
        float mmPerRev = (1.0 / LEAD_SCREW_TPI) * INCH_TO_MM;
        float linearSpeed_mm_per_sec = motorRPS * mmPerRev;
        
        if (linearSpeed_mm_per_sec > 0) {
            return (unsigned long)((RAIL_LENGTH_MM / linearSpeed_mm_per_sec) * 1000.0 * 1.1);
        }
    }
    return 300000; 
}

void configureMd49() {
  MD49_SERIAL.write(MD49_SYNC_BYTE);
  MD49_SERIAL.write(MD49_SET_MODE);
  MD49_SERIAL.write((byte)0x00);
  delay(10);
  MD49_SERIAL.write(MD49_SYNC_BYTE);
  MD49_SERIAL.write(MD49_SET_ACCEL);
  MD49_SERIAL.write(ACCELERATION);
  delay(10);
  MD49_SERIAL.write(MD49_SYNC_BYTE);
  MD49_SERIAL.write(MD49_ENABLE_REG);
  delay(10);
  MD49_SERIAL.write(MD49_SYNC_BYTE);
  MD49_SERIAL.write(MD49_DISABLE_TOUT);
  delay(10);
}

void stopMotor() {
  MD49_SERIAL.write(MD49_SYNC_BYTE);
  MD49_SERIAL.write(MD49_SET_SPEED1);
  MD49_SERIAL.write(MOTOR_STOP);
}

void resetEncoders() {
  MD49_SERIAL.write(MD49_SYNC_BYTE);
  MD49_SERIAL.write(MD49_RESET_ENCODERS);
}

void printInstructions() {
    PC_SERIAL.println("MD49 Friction Experiment Controller Initialized.");
    PC_SERIAL.println("---------------------------------------------");
    PC_SERIAL.println("INIT_COMPLETE");
}

 struct DataPacket {
  uint32_t timestamp;
  int32_t encoder_val;
  uint8_t current_val;
  uint8_t voltage_val;
} __attribute__((packed));

void pollAndSendData() {
  long encoder_val = 0;
  byte current_val = 0;
  byte voltage_val = 0;
  unsigned long startTime;

  MD49_SERIAL.write(MD49_SYNC_BYTE);
  MD49_SERIAL.write(MD49_GET_ENCODER1);
  startTime = millis();
  while (MD49_SERIAL.available() < 4) {
    if (millis() - startTime > 50) { goto send_packet; }
  }
  byte b1 = MD49_SERIAL.read(); byte b2 = MD49_SERIAL.read();
  byte b3 = MD49_SERIAL.read(); byte b4 = MD49_SERIAL.read();
  encoder_val = ((long)b1 << 24) | ((long)b2 << 16) | ((long)b3 << 8) | (long)b4;

  MD49_SERIAL.write(MD49_SYNC_BYTE);
  MD49_SERIAL.write(MD49_GET_VOLTS);
  startTime = millis();
  while (MD49_SERIAL.available() < 1) {
    if (millis() - startTime > 50) { goto send_packet; }
  }
  voltage_val = MD49_SERIAL.read();

  MD49_SERIAL.write(MD49_SYNC_BYTE);
  MD49_SERIAL.write(MD49_GET_CURRENT1);
  startTime = millis();
  while (MD49_SERIAL.available() < 1) {
    if (millis() - startTime > 50) { goto send_packet; }
  }
  current_val = MD49_SERIAL.read();

send_packet:
  DataPacket packet;
  packet.timestamp = millis();
  packet.encoder_val = encoder_val;
  packet.current_val = current_val;
  packet.voltage_val = voltage_val;

  PC_SERIAL.write('>');
  PC_SERIAL.write((uint8_t*)&packet, sizeof(packet));
  PC_SERIAL.write('<');
}
