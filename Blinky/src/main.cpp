#include <Arduino.h>

void setup()
{
    pinMode(PC13, OUTPUT);
}

void loop()
{
    digitalWrite(PC13, LOW);
    delay(3000);

    digitalWrite(PC13, HIGH);
    delay(1000);
}