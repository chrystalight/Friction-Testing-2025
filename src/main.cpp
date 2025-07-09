#include <Arduino.h>
#include <Servo.h>
#include <math.h> // Needed for PI constant

/*****************************************************************************************
 * MD49 Motor Driver Control for Friction Characterization Experiment
 * ---------------------------------------------------------------------------------------
 * Author: Catie Balasubramanian
 * Date: July 9, 2025
 *
 * Description:
 * This script runs on an Arduino Mega to control an EMG49 motor via an MD49 driver
 * and a servo for positioning. It includes an automated trial mode using two limit
 * switches (start and end).
 *
 * REVISION: This version uses a non-blocking state machine in the main loop. It
 * includes a calculated timeout failsafe and allows for setting a precise RPM for
 * the main trial via a serial command. Variable names have been updated for clarity.
 *
 *****************************************************************************************/

//========================================================================================
// == CONFIGURATION PARAMETERS ==
//========================================================================================

// -- Failsafe Physical Parameters --
const float RAIL_LENGTH_MM = 150.0;       // Max travel distance from switch A to B
const float PULLEY_DIAMETER_MM = 30.0;    // Diameter of the motor's pulley
const float MAX_MOTOR_RPM = 143.0;        // UPDATED: From motor datasheet (No load speed)

// -- Servo Settings --
const int SERVO_PIN = 9; // PWM pin for the servo control signal
Servo angleServo;        // Create a servo object
int currentAngle = 90;   // Variable to store the current servo angle, start at 90.

// -- Trial Settings --
const unsigned long MANUAL_TRIAL_DURATION_MS = 60000; // Duration for manual trial (60s).

// -- Limit Switch Pins --
const int SWITCH_A_PIN = 2; // Start/Home position switch
const int SWITCH_B_PIN = 3; // End position switch

// -- Motor Settings (Names updated for clarity) --
// Homing is FORWARD (128 to 255 range)
const byte HOMING_SPEED_BYTE = 148;     // Homing speed (e.g., 128 + 20 for slow forward).
// Trial is REVERSE (0 to 127 range). This is the default value.
byte g_trialSpeedByte = 80;             // Trial speed. Can be changed by the RPM command.

const byte MOTOR_STOP = 128;          // The "stop" value for mode 0.
const byte ACCELERATION = 5;          // Default acceleration value (1-10).

// -- Serial Port Definitions --
#define PC_SERIAL Serial        // Serial port for communication with the host PC (laptop)
#define MD49_SERIAL Serial1     // Hardware serial port for MD49 driver (TX1, RX1)

// -- MD49 Command Definitions --
#define MD49_SYNC_BYTE      (byte)0x00 // The sync byte that must precede all commands.
#define MD49_SET_SPEED1     0x31
#define MD49_SET_ACCEL      0x33
#define MD49_SET_MODE       0x34
#define MD49_RESET_ENCODERS 0x35
#define MD49_ENABLE_REG     0x37 // Enable speed regulation
#define MD49_DISABLE_TOUT   0x38 // Disable auto-timeout
#define MD49_GET_ENCODER1   0x23
#define MD49_GET_CURRENT1   0x27
#define MD49_GET_VOLTS      0x26
#define MD49_GET_VI         0x2C // Get combined Volts and Current
#define MD49_GET_ERROR      0x2D

// == State Machine Definition ==
enum State {
  IDLE,
  HOMING,
  TRIAL_RUNNING,
  MANUAL_TRIAL_RUNNING
};
State currentState = IDLE;
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
void moveServo(int newAngle);


//========================================================================================
// == SETUP FUNCTION ==
//========================================================================================

void setup() {
  // Start serial communication with the host PC
  PC_SERIAL.begin(9600);
  while (!PC_SERIAL) { ; } // Wait for the serial port to connect.

  // Start serial communication with the MD49 motor driver (no jumper = 9600)
  MD49_SERIAL.begin(9600);

  // Attach the servo on its pin and set initial position
  angleServo.attach(SERVO_PIN);
  angleServo.write(currentAngle);

  // Configure limit switch pins with internal pull-up resistors.
  pinMode(SWITCH_A_PIN, INPUT_PULLUP);
  pinMode(SWITCH_B_PIN, INPUT_PULLUP);

  configureMd49(); // Configure the MD49 driver

  // Print welcome message and instructions to the PC
  printInstructions();
}


//========================================================================================
// == REVISED MAIN LOOP (NON-BLOCKING) ==
//========================================================================================

void loop() {
  // --- Part 1: State Machine Logic (manages motor movement and state transitions) ---
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

        // Calculate timeout for the main trial phase (reverse direction)
        float trialSpeedRatio = (float)abs(g_trialSpeedByte - 128) / 128.0; // Range is 0-127, so divide by 128
        float trialRPM = trialSpeedRatio * MAX_MOTOR_RPM;
        float trialLinearSpeed = (trialRPM / 60.0) * (PI * PULLEY_DIAMETER_MM);
        if (trialLinearSpeed > 0) {
            currentTimeoutDuration = (RAIL_LENGTH_MM / trialLinearSpeed) * 1000;
        } else {
            currentTimeoutDuration = 300000;
        }
        
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

  // --- Part 2: Command Handler (always listening for PC commands) ---
  if (PC_SERIAL.available() > 0) {
    char command = PC_SERIAL.read();

    switch (command) {
      case 'a': // Start Automated Trial
        if (currentState == IDLE) {
          PC_SERIAL.println("COMMAND: Starting new automated trial...");
          PC_SERIAL.println("Homing: Moving to Switch A (start position)...");

          // Calculate timeout for the homing phase (forward direction)
          float homingSpeedRatio = (float)abs(HOMING_SPEED_BYTE - 128) / 127.0; // Range is 129-255, so divide by 127
          float homingRPM = homingSpeedRatio * MAX_MOTOR_RPM;
          float homingLinearSpeed = (homingRPM / 60.0) * (PI * PULLEY_DIAMETER_MM);
          if (homingLinearSpeed > 0) {
              currentTimeoutDuration = (RAIL_LENGTH_MM / homingLinearSpeed) * 1000;
          } else {
              currentTimeoutDuration = 300000;
          }
          
          stateStartTime = millis();

          MD49_SERIAL.write(MD49_SYNC_BYTE);
          MD49_SERIAL.write(MD49_SET_SPEED1);
          MD49_SERIAL.write(HOMING_SPEED_BYTE);
          currentState = HOMING;
        }
        break;

      case 's': // Start Manual Trial
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
      
      case 't': // Set Target RPM Command
        if (currentState == IDLE) {
          String rpmString = PC_SERIAL.readStringUntil('\n');
          float targetRPM = rpmString.toFloat();
          if (targetRPM >= 0 && targetRPM <= MAX_MOTOR_RPM) {
            // Convert RPM to a speed byte for REVERSE direction (0-127)
            byte speedOffset = (byte)((targetRPM / MAX_MOTOR_RPM) * 128.0);
            g_trialSpeedByte = 128 - speedOffset; // Update the global trial speed
            PC_SERIAL.print("COMMAND: New trial RPM set to ");
            PC_SERIAL.print(targetRPM);
            PC_SERIAL.print(" (Speed Byte: ");
            PC_SERIAL.print(g_trialSpeedByte);
            PC_SERIAL.println(")");
          } else {
            PC_SERIAL.println("ERROR: Invalid RPM. Must be between 0 and MAX_MOTOR_RPM.");
          }
        }
        break;

      case 'x': // Emergency Stop
        PC_SERIAL.println("COMMAND: Emergency Stop!");
        stopMotor();
        currentState = IDLE;
        break;

      case 'r': // Reset Encoders
        PC_SERIAL.println("COMMAND: Resetting encoder count.");
        resetEncoders();
        break;

      case 'p': // Poll for Data
        pollAndSendData();
        break;

      case '+': // Servo control
        currentAngle += 10;
        moveServo(currentAngle);
        break;

      case '-': // Servo control
        currentAngle -= 10;
        moveServo(currentAngle);
        break;
    }
  }
}


//========================================================================================
// == HELPER FUNCTIONS ==
//========================================================================================

void moveServo(int newAngle) {
  currentAngle = constrain(newAngle, 0, 180);
  PC_SERIAL.print("Moving servo to: ");
  PC_SERIAL.print(currentAngle);
  PC_SERIAL.println(" degrees.");
  angleServo.write(currentAngle);
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
