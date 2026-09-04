#include <Wire.h>
#include "SparkFun_AS7343.h"

SfeAS7343ArdI2C sensor;
int led_intensity = 4; //default is 12mA
bool led_on = true;

const char* channelNames[18] = {
  "FZ (450nm)",  "FY (555nm)",  "FXL (600nm)", "NIR (855nm)", "VIS_1",       "FD_1",
  "F2 (425nm)",  "F3 (475nm)",  "F4 (515nm)",  "F6 (640nm)",  "VIS_2",       "FD_2",
  "F1 (405nm)",  "F7 (690nm)",  "F8 (745nm)",  "F5 (550nm)",  "VIS_3",       "FD_3"
};

void setup() {
  Serial.begin(115200);
  Wire.begin();

  if (!sensor.begin()) {
    Serial.println("Error: Sensor initialization failed!");
    while (1);
  }

  sensor.powerOn();
  sensor.setAutoSmux(AUTOSMUX_18_CHANNELS);

  // Set GAIN and timing BEFORE enabling measurement:
  sensor.setAgain(8);

  // 2. Enable Measurement AFTER configuration
  sensor.enableSpectralMeasurement(true);

  // Set LED drive current to 1 (~6mA)
  sensor.setLedDrive(led_intensity);
  sensor.ledOn();

  Serial.println("\n==========================================");
  Serial.println("Sensor Gain Initialized to AGAIN 128x ");
  Serial.println("==========================================");
  Serial.println("1. Place sample target exactly 20mm below sensor.");
  Serial.println("2. Type 'w' in Serial Monitor and press Enter to read.\n");
}

void loop() {
  // Wait for user input ('w') to trigger reading
  if (Serial.available()) {
    char c = Serial.read();

    if (c == 'o' || c == 'O') {
      led_intensity++;
      Serial.print("LED POWER INCREASED TO ");
      Serial.println(led_intensity);
      sensor.setLedDrive(led_intensity);
    }

    if (c == 'i' || c == 'I') {
      if (led_intensity > 0) {
        led_intensity--;
        Serial.print("LED POWER DECREASED TO ");
        Serial.println(led_intensity);
        sensor.setLedDrive(led_intensity);
      }
      else
      {
        Serial.println("ERROR: ALREADY AT MIN BRIGHTNESS!");
      }
    }

    if (c == 'l' || c == 'L') {
      if (led_on) {
        led_on = !led_on;
        Serial.print("LED TURNED OFF");
        sensor.ledOff();
      }
      else
      {
        led_on = !led_on;
        Serial.print("LED TURNED ON!");
        sensor.ledOn();
      }
    }

    if (c == 'w' || c == 'W') {
      Serial.println("\n--- RAW SAMPLE DATA ---");

      if (sensor.readSpectraDataFromSensor()) {
        for (int i = 0; i < ksfAS7343NumChannels; i++) {
          uint16_t val = sensor.getChannelData((sfe_as7343_channel_t)i);
          Serial.print(channelNames[i]);
          Serial.print(": ");
          Serial.println(val);
        }
        Serial.println("--------------------------------\n");
        Serial.println("Done! Type 'w' again if you want to re-take the reading.");
      } else {
        Serial.println("Error reading sensor data!");
      }
    }

    if (c == 'c' || c == 'C') {
      Serial.println("\n--- CALIBRATION DATA ---");

      if (sensor.readSpectraDataFromSensor()) {
        for (int i = 0; i < ksfAS7343NumChannels; i++) {
          uint16_t val = sensor.getChannelData((sfe_as7343_channel_t)i);
          Serial.print(channelNames[i]);
          Serial.print(": ");
          Serial.println(val);
        }
        Serial.println("--------------------------------\n");
        Serial.println("Done! Type 'w' again if you want to re-take the reading.");
      } else {
        Serial.println("Error reading sensor data!");
      }
    }
  }
}
