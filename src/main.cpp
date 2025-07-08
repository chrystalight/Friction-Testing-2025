#include <Arduino.h>


/*****************************************************************************************
 * MD49 Motor Driver Control for Friction Characterization Experiment
 * ---------------------------------------------------------------------------------------
 * Author: Catie Balasubramanian
 * Date: July 8, 2025
 *
 * Description:
 * This script runs on an Arduino Mega to control an EMG49 motor via an MD49 driver.
 * It now includes an automated trial mode using two limit switches (start and end).
 *
 * It communicates with a host PC over the main USB serial port (`Serial`) and controls
 * the MD49 driver over a secondary hardware serial port (`Serial1`).
 *
 * How to Use:
 * 1. Wire the limit switches as described in the documentation.
 * 2. Upload this script to your Arduino Mega.
 * 3. Connect the Arduino to your laptop via USB and open the Serial Monitor.
 * 4. Use the single-character commands to interact with the script. The primary
 * command is 'a' to run a full, automated homing and data collection trial.
 *
 *****************************************************************************************/

//========================================================================================
// == CONFIGURATION PARAMETERS ==
//========================================================================================

// -- Trial Settings --
const unsigned long MANUAL_TRIAL_DURATION_MS = 60000; // Duration for manual trial (60s).

// -- Limit Switch Pins --
const int SWITCH_A_PIN = 2; // Start/Home position switch
const int SWITCH_B_PIN = 3; // End position switch

// -- Motor Settings --
// NOTE: Calibrate these values to achieve the desired 4.2 mm/s cable speed.
// Mode 0: 0=Full Reverse, 128=Stop, 255=Full Forward.
const byte MOTOR_SPEED_CW = 148;      // Clockwise speed for the main trial (e.g., 128 + 20).
const byte MOTOR_SPEED_CCW = 108;     // Counter-clockwise speed for homing (e.g., 128 - 20).
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
#define MD49_GET_ERROR      0x2D

//========================================================================================
// == FUNCTION PROTOTYPES ==
//========================================================================================
void runAutomatedTrial();
void runManualTrial();
void configureMd49();
void stopMotor();
void resetEncoders();
void printInstructions();
void pollAndSendData();


//========================================================================================
// == SETUP FUNCTION ==
//========================================================================================

void setup() {
  // Start serial communication with the host PC
  PC_SERIAL.begin(115200);
  while (!PC_SERIAL) { ; } // Wait for the serial port to connect.

  // Start serial communication with the MD49 motor driver
  MD49_SERIAL.begin(38400); // Default baud rate is 38400 with the jumper on.

  // Configure limit switch pins with internal pull-up resistors.
  // Pin will be HIGH when not pressed, and LOW when pressed.
  pinMode(SWITCH_A_PIN, INPUT_PULLUP);
  pinMode(SWITCH_B_PIN, INPUT_PULLUP);

  delay(100); // Give everything a moment to initialize

  configureMd49(); // Configure the MD49 driver

  // Print welcome message and instructions to the PC
  printInstructions();
}


//========================================================================================
// == MAIN LOOP ==
//========================================================================================

void loop() {
  // Check if the PC has sent a command
  if (PC_SERIAL.available() > 0) {
    char command = PC_SERIAL.read();

    switch (command) {
      case 'a':
        PC_SERIAL.println("COMMAND: Starting new automated trial...");
        runAutomatedTrial();
        break;
      case 's':
        PC_SERIAL.println("COMMAND: Starting manual 60-second trial...");
        runManualTrial();
        break;
      case 'x':
        PC_SERIAL.println("COMMAND: Emergency Stop!");
        stopMotor();
        break;
      case 'r':
        PC_SERIAL.println("COMMAND: Resetting encoder count.");
        resetEncoders();
        break;
      case 'p':
        pollAndSendData();
        break;
    }
  }
}


//========================================================================================
// == HELPER FUNCTIONS ==
//========================================================================================

/**
 * @brief Runs a fully automated trial using the limit switches.
 * 1. Homes the carriage by moving CCW to Switch A.
 * 2. Runs the data collection trial by moving CW to Switch B.
 */
void runAutomatedTrial() {
  // --- Homing Phase ---
  PC_SERIAL.println("Homing: Moving to Switch A (start position)...");
  MD49_SERIAL.write(MD49_SYNC_BYTE);
  MD49_SERIAL.write(MD49_SET_SPEED1);
  MD49_SERIAL.write(MOTOR_SPEED_CCW);

  // Wait until Switch A is pressed (pin goes LOW)
  while (digitalRead(SWITCH_A_PIN) == HIGH) {
    // You can add a timeout here for safety if needed
    delay(10);
  }
  stopMotor();
  PC_SERIAL.println("Homing complete. Switch A reached.");
  delay(500); // Pause before starting the trial

  // --- Data Collection Phase ---
  resetEncoders(); // Reset encoders for a clean trial measurement
  delay(10);
  
  PC_SERIAL.println("Trial Running: Moving to Switch B (end position)...");
  MD49_SERIAL.write(MD49_SYNC_BYTE);
  MD49_SERIAL.write(MD49_SET_SPEED1);
  MD49_SERIAL.write(MOTOR_SPEED_CW);
  
  // Wait until Switch B is pressed (pin goes LOW)
  while (digitalRead(SWITCH_B_PIN) == HIGH) {
    // Your main PC should be polling for DAQ data during this loop.
    // We can also poll for motor data and send it to the PC.
    pollAndSendData();
    delay(20); // Delay to match ~50Hz polling, adjust as needed.
  }
  stopMotor();
  PC_SERIAL.println("Trial complete. Switch B reached.");
}

/**
 * @brief Runs a single, manually timed experimental trial.
 */
void runManualTrial() {
  resetEncoders();
  delay(10);
  PC_SERIAL.println("Manual trial running...");
  MD49_SERIAL.write(MD49_SYNC_BYTE);
  MD49_SERIAL.write(MD49_SET_SPEED1);
  MD49_SERIAL.write(MOTOR_SPEED_CW);

  unsigned long startTime = millis();
  while (millis() - startTime < MANUAL_TRIAL_DURATION_MS) {
    if (PC_SERIAL.available() > 0 && PC_SERIAL.read() == 'x') {
      PC_SERIAL.println("COMMAND: Manual trial stopped early by user.");
      stopMotor();
      return;
    }
    delay(10);
  }
  stopMotor();
  PC_SERIAL.println("Manual trial complete.");
}

/**
 * @brief Sends initial configuration commands to the MD49 driver.
 */
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

/**
 * @brief Immediately stops the motor.
 */
void stopMotor() {
  MD49_SERIAL.write(MD49_SYNC_BYTE);
  MD49_SERIAL.write(MD49_SET_SPEED1);
  MD49_SERIAL.write(MOTOR_STOP);
}

/**
 * @brief Resets the MD49's internal encoder count to zero.
 */
void resetEncoders() {
  MD49_SERIAL.write(MD49_SYNC_BYTE);
  MD49_SERIAL.write(MD49_RESET_ENCODERS);
}

/**
 * @brief Prints the command instructions to the PC serial monitor.
 */
void printInstructions() {
    PC_SERIAL.println("MD49 Friction Experiment Controller Initialized.");
    PC_SERIAL.println("---------------------------------------------");
    PC_SERIAL.println("Commands:");
    PC_SERIAL.println("  'a' -> Start a full AUTOMATED trial (Home to A, Run to B)");
    PC_SERIAL.println("  's' -> Start a MANUAL 60-second trial");
    PC_SERIAL.println("  'x' -> Emergency STOP motor");
    PC_SERIAL.println("  'r' -> Reset encoder count");
    PC_SERIAL.println("  'p' -> Poll for current data (encoder, current, volts)");
    PC_SERIAL.println("---------------------------------------------");
}

/**
 * @brief Polls the MD49 for data and sends it to the PC in CSV format.
 */
void pollAndSendData() {
  MD49_SERIAL.write(MD49_SYNC_BYTE);
  MD49_SERIAL.write(MD49_GET_ENCODER1);
  delay(20);
  long encoder_val = 0;
  if (MD49_SERIAL.available() >= 4) {
    byte b1 = MD49_SERIAL.read(); byte b2 = MD49_SERIAL.read();
    byte b3 = MD49_SERIAL.read(); byte b4 = MD49_SERIAL.read();
    encoder_val = ((long)b1 << 24) | ((long)b2 << 16) | ((long)b3 << 8) | (long)b4;
  }

  MD49_SERIAL.write(MD49_SYNC_BYTE);
  MD49_SERIAL.write(MD49_GET_CURRENT1);
  delay(20);
  byte current_val = 0;
  if (MD49_SERIAL.available() >= 1) { current_val = MD49_SERIAL.read(); }

  MD49_SERIAL.write(MD49_SYNC_BYTE);
  MD49_SERIAL.write(MD49_GET_VOLTS);
  delay(20);
  byte voltage_val = 0;
  if (MD49_SERIAL.available() >= 1) { voltage_val = MD49_SERIAL.read(); }
  
  PC_SERIAL.print("DATA,"); PC_SERIAL.print(millis());
  PC_SERIAL.print(","); PC_SERIAL.print(encoder_val);
  PC_SERIAL.print(","); PC_SERIAL.print(current_val);
  PC_SERIAL.print(","); PC_SERIAL.println(voltage_val);
}
