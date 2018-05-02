/*
This is a basic example that will print out the header and the content of an ArtDmx packet.
This example uses the read() function and the different getter functions to read the data.
This example may be copied under the terms of the MIT license, see the LICENSE file for details

This example has been modified and extended:
- forward incoming data to DMX
- use DHCP
*/

#include <Artnet.h>
#include <Ethernet.h>
#include <EthernetUdp.h>
#include <SPI.h>
#include <DMXSerial.h>
#include <Adafruit_NeoPixel.h>

#define LEDS_PER_UNIVERSE (512/3)
#define LEDS_STRIPE1 (LEDS_PER_UNIVERSE*3)
#define LEDS_STRIPE2 (LEDS_PER_UNIVERSE*3)
#define LEDS_STRIPE3 (LEDS_PER_UNIVERSE*3)

//#define DEBUG

#ifndef DMX_USE_PORT1
#error Please define DMX_USE_PORT1 in DMXSerial.h!
#endif

Artnet artnet;

// Change ip and mac address for your setup
byte ip[] = {192, 168, 2, 2};
byte mac[] = {0x04, 0xE9, 0xE5, 0x00, 0x69, 0xEC};
// 90-A2-DA-00-7B-62


Adafruit_NeoPixel ledstripe1 = Adafruit_NeoPixel(LEDS_STRIPE1, 4, NEO_GRB + NEO_KHZ800);
Adafruit_NeoPixel ledstripe2 = Adafruit_NeoPixel(LEDS_STRIPE2, 5, NEO_GRB + NEO_KHZ800);
Adafruit_NeoPixel ledstripe3 = Adafruit_NeoPixel(LEDS_STRIPE3, 6, NEO_GRB + NEO_KHZ800);

#define PWM_OFFSET 22

const uint8_t pwmPins[] = {8, 9, 7, 11, 12, 13};

void setup()
{
  Serial.begin(115200);
  Serial.print(F("initializing lights...\t"));
  DMXSerial.init(DMXController, 22);
  for (int i=1;i<1+4*5;i+=4) {
    DMXSerial.write(i+0, 0);
    DMXSerial.write(i+1, 0xff);
    DMXSerial.write(i+2, 0xff);
    DMXSerial.write(i+3, 0xff);
  }

  ledstripe1.begin();
  ledstripe1.setPixelColor(0, ledstripe2.Color(100, 200, 50));
  for (int i=0;i<LEDS_STRIPE1;i++) {
    ledstripe1.setPixelColor(i, ledstripe2.Color(100, 200, 50));
  }
  ledstripe1.show();
  ledstripe2.begin();
  ledstripe2.setPixelColor(0, ledstripe2.Color(100, 200, 50));
  ledstripe2.show();
  ledstripe3.begin();
  ledstripe3.setPixelColor(0, ledstripe2.Color(100, 200, 50));
  ledstripe3.show();

  for (int i=0;i<sizeof(pwmPins)/sizeof(*pwmPins);i++) {
    pinMode(pwmPins[i], OUTPUT);
    analogWrite(pwmPins[i], 255-150);
  }
  
  Serial.println(F("done"));

  Serial.print(F("initializing network...\t"));
  Ethernet.begin(mac);
  ip[0] = Ethernet.localIP()[0];
  ip[1] = Ethernet.localIP()[1];
  ip[2] = Ethernet.localIP()[2];
  ip[3] = Ethernet.localIP()[3];
  artnet.begin(mac, ip);
  Serial.println(F("done"));
  Serial.print(F("IP: "));
  Serial.println(Ethernet.localIP());
}

void setFromDmx(Adafruit_NeoPixel& ledstripe, int offset, int ledstripeLength) {
  for (int i=0;i<512 && i < artnet.getLength() && i/3+offset<ledstripeLength;i+=3) {
    uint32_t c = ledstripe.Color(artnet.getDmxFrame()[i+0],
      artnet.getDmxFrame()[i+1], artnet.getDmxFrame()[i+2]);
    ledstripe.setPixelColor(i/3+offset, c);
  }
  Serial.print("sending data to LED stripe...\t");
  ledstripe.show();
  Serial.println("done");
}

void loop()
{
  if (artnet.read() == ART_DMX)
  {
    #ifdef DEBUG
    // print out our data
    Serial.print("universe number = ");
    Serial.print(artnet.getUniverse());
    Serial.print("\tdata length = ");
    Serial.print(artnet.getLength());
    Serial.print("\tsequence n0. = ");
    Serial.println(artnet.getSequence());
    Serial.print("DMX data: ");
    for (int i = 0 ; i < artnet.getLength() && i < 50 ; i++)
    {
      Serial.print(artnet.getDmxFrame()[i]);
      Serial.print("  ");
    }
    Serial.println();
    Serial.println();
    #endif

    switch (artnet.getUniverse()) {
      case 0:   // Art-Net Controller LITE App
      case 145: // AuroraDMX App
        for (int i=0;i<512 && i < artnet.getLength();i++) {
          DMXSerial.write(i, artnet.getDmxFrame()[i]);
        }
        for (int i=0;i<sizeof(pwmPins)/sizeof(*pwmPins) && PWM_OFFSET+i<artnet.getLength();i++) {
          analogWrite(pwmPins[i], 255-artnet.getDmxFrame()[PWM_OFFSET+i]);
        }
        break;

      case 10: setFromDmx(ledstripe1, 0*LEDS_PER_UNIVERSE, LEDS_STRIPE1); break;
      case 11: setFromDmx(ledstripe1, 1*LEDS_PER_UNIVERSE, LEDS_STRIPE1); break;
      case 12: setFromDmx(ledstripe1, 2*LEDS_PER_UNIVERSE, LEDS_STRIPE1); break;

      case 20: setFromDmx(ledstripe2, 0*LEDS_PER_UNIVERSE, LEDS_STRIPE2); break;
      case 21: setFromDmx(ledstripe2, 1*LEDS_PER_UNIVERSE, LEDS_STRIPE2); break;
      case 22: setFromDmx(ledstripe2, 2*LEDS_PER_UNIVERSE, LEDS_STRIPE2); break;

      case 30: setFromDmx(ledstripe3, 0*LEDS_PER_UNIVERSE, LEDS_STRIPE3); break;
      case 31: setFromDmx(ledstripe3, 1*LEDS_PER_UNIVERSE, LEDS_STRIPE3); break;
      case 32: setFromDmx(ledstripe3, 2*LEDS_PER_UNIVERSE, LEDS_STRIPE3); break;
    }
  }
}
