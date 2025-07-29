#include <Arduino.h>
#include <HX711_ADC.h>

//========================================================================================
// == SENSOR CONFIGURATION ==
//========================================================================================
const int HX711_DOUT_PIN = 24;
const int HX711_SCK_PIN = 22;
HX711_ADC LoadCell(HX711_DOUT_PIN, HX711_SCK_PIN);

//========================================================================================
// == MOTOR & SYSTEM CONFIGURATION ==
//========================================================================================
const int SWITCH_A_PIN = 2;
const int SWITCH_B_PIN = 3;

const byte HOMING_SPEED_BYTE = 5;
const byte MOTOR_STOP = 128;
const float MAX_MOTOR_RPM = 143.0;
byte g_trialSpeedByte = 168;

#define PC_SERIAL Serial
#define MD49_SERIAL Serial3

#define MD49_SYNC_BYTE      (byte)0x00
#define MD49_SET_SPEED1     0x31
#define MD49_RESET_ENCODERS 0x35
#define MD49_DISABLE_TIMEOUT 0x38

enum State { HW_TEST, IDLE, HOMING, TRIAL_RUNNING };
State currentState = HW_TEST;

// --- ADDED: Variables for debouncing the home switch ---
const unsigned long DEBOUNCE_DELAY = 50; // 50 milliseconds
unsigned long lastDebounceTime = 0;
bool lastSwitchState = HIGH; // The switch is HIGH when not pressed (due to INPUT_PULLUP)
bool homingSwitchState = HIGH;

//========================================================================================
// == FUNCTION PROTOTYPES ==
//========================================================================================
void stopMotor();
void resetEncoders();

//========================================================================================
// == SETUP ==
//========================================================================================
void setup() {
  PC_SERIAL.begin(9600);
  MD49_SERIAL.begin(9600);

  MD49_SERIAL.write(MD49_SYNC_BYTE);
  MD49_SERIAL.write(MD49_DISABLE_TIMEOUT);
  
  pinMode(SWITCH_A_PIN, INPUT_PULLUP);
  pinMode(SWITCH_B_PIN, INPUT_PULLUP);

  LoadCell.begin();
  LoadCell.tare();
  LoadCell.setCalFactor(1.0f);
  
  PC_SERIAL.println("HW_TEST_REQUIRED");
}

//========================================================================================
// == MAIN LOOP ==
//========================================================================================
void loop() {
  switch (currentState) {
    case HOMING:
      // --- MODIFIED: Debounce logic for the home switch ---
      { // Use a block to scope these variables
        bool reading = digitalRead(SWITCH_A_PIN);

        // If the switch state has changed, reset the debounce timer
        if (reading != lastSwitchState) {
          lastDebounceTime = millis();
        }

        // If the reading has been stable for longer than the debounce delay
        if ((millis() - lastDebounceTime) > DEBOUNCE_DELAY) {
          // If the state has actually changed, update the official state
          if (reading != homingSwitchState) {
            homingSwitchState = reading;
            
            // If the new, confirmed state is LOW (pressed)
            if (homingSwitchState == LOW) {
              stopMotor();
              delay(100);
              resetEncoders();
              delay(10);
              MD49_SERIAL.write(MD49_SYNC_BYTE);
              MD49_SERIAL.write(MD49_SET_SPEED1);
              MD49_SERIAL.write(g_trialSpeedByte);
              currentState = TRIAL_RUNNING;
              PC_SERIAL.println("HOMING_COMPLETE");
            }
          }
        }
        lastSwitchState = reading; // Update the last reading
      }
      break;

    case TRIAL_RUNNING:
      if (digitalRead(SWITCH_B_PIN) == LOW) {
        stopMotor();
        currentState = IDLE;
        PC_SERIAL.println("TRIAL_COMPLETE");
      }
      break;

    case IDLE:
    case HW_TEST:
      // Do nothing, wait for commands
      break;
  }

  if (PC_SERIAL.available() > 0) {
    char command = PC_SERIAL.read();
    switch (command) {
      case 'a': // Start Trial
        if (currentState == IDLE) {
          MD49_SERIAL.write(MD49_SYNC_BYTE);
          MD49_SERIAL.write(MD49_SET_SPEED1);
          MD49_SERIAL.write(HOMING_SPEED_BYTE);
          currentState = HOMING;
          // Reset debounce state at the start of homing
          lastSwitchState = digitalRead(SWITCH_A_PIN);
          homingSwitchState = lastSwitchState;
        }
        break;
      
      case 'd': // Poll for SML data
        if (currentState == TRIAL_RUNNING) {
          LoadCell.update();
          long raw_adc = LoadCell.getData();
          PC_SERIAL.print("ADC_VAL:");
          PC_SERIAL.println(raw_adc);
          //PC_SERIAL.println("SENT SML DATA");
        }
        break;

      case 'R': // Read SML Sensor for calibration
        if (currentState == IDLE) {
          long reading_sum = 0;
          const int samples = 10;
          for (int i = 0; i < samples; i++) {
            LoadCell.update();
            reading_sum += LoadCell.getData();
            delay(10);
          }
          long avg_reading = reading_sum / samples;
          PC_SERIAL.print("ADC_VAL:");
          PC_SERIAL.println(avg_reading);
        }
        break;

      case 't': // Set RPM
        if (currentState == IDLE) {
          String rpmString = PC_SERIAL.readStringUntil('\n');
          float targetRPM = rpmString.toFloat();
          if (targetRPM >= 0 && targetRPM <= MAX_MOTOR_RPM) {
            byte speedOffset = (byte)((targetRPM / MAX_MOTOR_RPM) * 127.0);
            g_trialSpeedByte = 128 + speedOffset;
          }
        }
        break;
      
      case 'c': // Check Switches for HW Test
        if (currentState == HW_TEST) {
          PC_SERIAL.print("S:");
          PC_SERIAL.print(digitalRead(SWITCH_A_PIN) == LOW);
          PC_SERIAL.print(digitalRead(SWITCH_B_PIN) == LOW);
          PC_SERIAL.println();
        }
        break;
      
      case 'e': // End HW Test
        if (currentState == HW_TEST) {
          currentState = IDLE;
          PC_SERIAL.println("Arduino Initialized. Ready for commands.");
        }
        break;
      
      case 'x': // Emergency Stop
        stopMotor();
        if (currentState != HW_TEST) {
            currentState = IDLE;
        }
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
