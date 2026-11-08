#include <Wire.h>
#include "DFRobot_ADS1115.h"

DFRobot_ADS1115 ads(&Wire);

// Fixed current supplied to outer probes (100.0 mA) for lowresist measurement
const float CONST_CURRENT_MA = 100.0; 

// Current measurement calibration factor
const float calib = 117.0;

// A2 open-circuit offset in mV (-80 mV corresponding to -80 uA error)
const float A2_OFFSET_MV = -118.0;

// How many samples should be read
const int SAMPLES = 50;

void setup(void)
{
  Serial.begin(115200);
  while (!Serial) { ; }

  ads.setAddr_ADS1115(ADS1115_IIC_ADDRESS0);
  ads.init();

  ads.setGain(eGAIN_ONE);    // +/- 4.096V Range (Default for Delta mV)
  ads.setRate(eRATE_128);    // 128 SPS
  ads.setMode(eMODE_CONTIN); // Continuous sampling mode

  delay(200);
}

void loop(void)
{
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 'h' || c == 'H') {
      getReading(1);
    }
    else if (c == 'l' || c == 'L') {
      getReading(2);
    }
    else if (c != '\r' && c != '\n') {
      Serial.println("Error: Invalid command! Type 'h' or 'l'.");
    }
  }
}

void getReading(int mode)
{
  if (ads.checkADS1115())
  {
    float calibrated_a2_mv = 0.0;
    float resistance_ohms = 0.0;

    // --- 1. DIFFERENTIAL FILM DELTA (AIN0 vs AIN1) - eGAIN_ONE ---
    ads.setGain(eGAIN_ONE);       // +/- 4.096V Range
    float diff_lsb_mv = 0.125;    // LSB for eGAIN_ONE

    ads.setMux(eADSMUX_1);
    delay(20); 

    // Flush dummy reads
    readAdsRegDirect(ADS1115_IIC_ADDRESS0, DFROBOT_ADS1115_POINTER_CONVERT);
    delay(8);
    readAdsRegDirect(ADS1115_IIC_ADDRESS0, DFROBOT_ADS1115_POINTER_CONVERT);
    delay(8);

    float sum_diff_mv = 0.0;
    for (int i = 0; i < SAMPLES; i++) {
      int16_t raw_adc = readAdsRegDirect(ADS1115_IIC_ADDRESS0, DFROBOT_ADS1115_POINTER_CONVERT);
      sum_diff_mv += ((float)raw_adc * diff_lsb_mv);
      delay(8);
    }
    float film_delta_mv = abs(sum_diff_mv / SAMPLES);

    // --- 2. MODE-SPECIFIC MEASUREMENTS / CALCULATIONS ---
    if (mode == 1) // HIGH RESISTIVITY READING ('h')
    {
      // A2 buffered monitor uses eGAIN_TWO (+/- 2.048V Range)
      ads.setGain(eGAIN_TWO);       
      float a2_lsb_mv = 0.0625;            

      ads.setMux(eADSMUX_7); // Read Pin A2 vs GND
      delay(20); 

      // Flush dummy reads
      readAdsRegDirect(ADS1115_IIC_ADDRESS0, DFROBOT_ADS1115_POINTER_CONVERT);
      delay(8);
      readAdsRegDirect(ADS1115_IIC_ADDRESS0, DFROBOT_ADS1115_POINTER_CONVERT);
      delay(8);

      float sum_a2_mv = 0.0;
      for (int i = 0; i < SAMPLES; i++) {
        int16_t raw_a2 = readAdsRegDirect(ADS1115_IIC_ADDRESS0, DFROBOT_ADS1115_POINTER_CONVERT);
        sum_a2_mv += ((float)raw_a2 * a2_lsb_mv);
        delay(8);
      }
      
      // Apply offset correction at the mV level (-80 mV offset)
      float raw_a2_avg = sum_a2_mv / SAMPLES;
      calibrated_a2_mv = raw_a2_avg - A2_OFFSET_MV;

      // Convert corrected mV to Amperes (assuming 1 mV = 1 uA scale on 2mA range)
      float current_amps = (abs(calibrated_a2_mv) / 1000.0) * 1e-6; 

      if (current_amps > 1e-12) {
        resistance_ohms = (film_delta_mv * 1e-3) / current_amps;
      }
    }
    else if (mode == 2) // LOW RESISTIVITY READING ('l')
    {
      float current_amps = CONST_CURRENT_MA * 1e-3;
      resistance_ohms = (film_delta_mv * 1e-3) / current_amps;
    }

    // --- 3. SHEET RESISTANCE MATH ---
    float sheet_resistance_ohms_sq = resistance_ohms * 4.5324;

    // --- 4. OUTPUT STREAM ---
    Serial.print("Diff_Delta_mV:");
    Serial.print(film_delta_mv, 6);
    Serial.print(",");
    Serial.print("Calibrated_A2_mV:");
    Serial.print(calibrated_a2_mv, 6);
    Serial.print(",");
    Serial.print("Resistance_Ohms:");
    Serial.print(resistance_ohms, 4);
    Serial.print(",");
    Serial.print("Sheet_R_Ohms_sq:");
    Serial.println(sheet_resistance_ohms_sq, 4);
  }
}

int16_t readAdsRegDirect(uint8_t i2cAddress, uint8_t reg)
{
  Wire.beginTransmission(i2cAddress);
  Wire.write(reg);
  if (Wire.endTransmission() != 0) return 0;

  Wire.requestFrom(i2cAddress, (uint8_t)2);
  if (Wire.available() >= 2) {
    uint8_t buf[2];
    buf[0] = Wire.read();
    buf[1] = Wire.read();
    return (int16_t)((buf[0] << 8) | buf[1]);
  }
  return 0;
}
