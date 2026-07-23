#include <Servo.h>

// =========================================================
//  PemilahBuahNaga - Firmware Arduino Nano
//  LED = hasil klasifikasi | Buzzer = event/alarm
//  + Heartbeat failsafe (motor auto-stop bila Pi diam)
//  Kompatibel dengan semua command lama (led/servo/motor/buzzer)
// =========================================================

const int ledPins[] = {11, 12, 13};
const char* ledNames[] = {"green", "yellow", "red"};
const int numLeds = 3;
// green  = matang
// yellow = setengah matang
// red    = mentah

Servo servo1;
Servo servo2;
const int servo1Pin = 4;
const int servo2Pin = 5;
const int SERVO_OPEN_ANGLE = 51;
const int SERVO_CLOSE_ANGLE = 0;

const int motorIN1 = 2;
const int motorIN2 = 3;

const int buzzerPin = 6;

// ----- Heartbeat / watchdog -----
bool watchdogEnabled = false;              // default OFF -> GUI manual tetap normal
const unsigned long HEARTBEAT_TIMEOUT_MS = 2000;
unsigned long lastCmdMs = 0;
bool motorRunning = false;
bool faultState = false;
unsigned long faultBlinkMs = 0;
bool faultLedOn = false;

// ----- Non-blocking buzzer beeper -----
int beepRemaining = 0;
bool beepActive = false;
bool beepIsOn = false;
unsigned long beepPhaseMs = 0;
const int BEEP_ON_MS = 80;
const int BEEP_OFF_MS = 120;

// ----- Ingat hasil klasifikasi terakhir (untuk restore setelah fault) -----
int lastResult = 0;  // 0=none, 1=green/matang, 2=yellow/setengah, 3=red/mentah


void setup() {
  Serial.begin(115200);

  for (int i = 0; i < numLeds; i++) {
    pinMode(ledPins[i], OUTPUT);
    digitalWrite(ledPins[i], LOW);
  }

  servo1.attach(servo1Pin);
  servo2.attach(servo2Pin);
  servo1.write(SERVO_CLOSE_ANGLE);
  servo2.write(SERVO_CLOSE_ANGLE);

  pinMode(motorIN1, OUTPUT);
  pinMode(motorIN2, OUTPUT);
  digitalWrite(motorIN1, LOW);
  digitalWrite(motorIN2, LOW);

  pinMode(buzzerPin, OUTPUT);
  digitalWrite(buzzerPin, LOW);

  lastCmdMs = millis();
  Serial.println("System ready. Type 'help' for commands.");
}


void loop() {
  unsigned long now = millis();

  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    lastCmdMs = now;
    if (faultState) clearFault();   // command apapun = clear fault
    processCommand(cmd);
  }

  serviceHeartbeat(now);
  serviceBeeper(now);
  serviceFaultBlink(now);
}


// =========================================================
//  HEARTBEAT / FAILSAFE
// =========================================================
void serviceHeartbeat(unsigned long now) {
  // Hanya bertindak kalau watchdog aktif DAN motor sedang jalan.
  if (!watchdogEnabled || !motorRunning || faultState) return;
  if (now - lastCmdMs > HEARTBEAT_TIMEOUT_MS) {
    stopMotor();
    enterFault();
    Serial.println("FAULT: heartbeat lost, motor stopped");
  }
}

void enterFault() {
  faultState = true;
  faultBlinkMs = millis();
  faultLedOn = false;
}

void clearFault() {
  faultState = false;
  digitalWrite(buzzerPin, LOW);
  applyResultLeds();   // kembalikan LED ke hasil klasifikasi terakhir
}

void serviceFaultBlink(unsigned long now) {
  if (!faultState) return;
  if (now - faultBlinkMs >= 300) {
    faultBlinkMs = now;
    faultLedOn = !faultLedOn;
    for (int i = 0; i < numLeds; i++) digitalWrite(ledPins[i], faultLedOn ? HIGH : LOW);
    digitalWrite(buzzerPin, faultLedOn ? HIGH : LOW);
  }
}


// =========================================================
//  NON-BLOCKING BUZZER
// =========================================================
void startBeeps(int n) {
  if (n <= 0) return;
  beepRemaining = n;
  beepActive = true;
  beepIsOn = false;
  beepPhaseMs = 0;   // 0 = trigger langsung
}

void serviceBeeper(unsigned long now) {
  if (!beepActive || faultState) return;
  if (!beepIsOn) {
    if (beepRemaining > 0 && (beepPhaseMs == 0 || now - beepPhaseMs >= BEEP_OFF_MS)) {
      digitalWrite(buzzerPin, HIGH);
      beepIsOn = true;
      beepPhaseMs = now;
    } else if (beepRemaining == 0) {
      beepActive = false;
    }
  } else {
    if (now - beepPhaseMs >= BEEP_ON_MS) {
      digitalWrite(buzzerPin, LOW);
      beepIsOn = false;
      beepRemaining--;
      beepPhaseMs = now;
    }
  }
}


// =========================================================
//  MOTOR
// =========================================================
void stopMotor() {
  digitalWrite(motorIN1, LOW);
  digitalWrite(motorIN2, LOW);
  motorRunning = false;
}


// =========================================================
//  LED HASIL KLASIFIKASI
// =========================================================
void applyResultLeds() {
  for (int i = 0; i < numLeds; i++) {
    digitalWrite(ledPins[i], ((i + 1) == lastResult) ? HIGH : LOW);
  }
}


// =========================================================
//  COMMAND PARSER
// =========================================================
void processCommand(String cmd) {
  if (cmd == "help") { printHelp(); return; }
  if (cmd == "ping") { Serial.println("pong"); return; }

  int space1 = cmd.indexOf(' ');
  String keyword = (space1 == -1) ? cmd : cmd.substring(0, space1);
  String rest = (space1 == -1) ? "" : cmd.substring(space1 + 1);
  rest.trim();

  if (keyword == "led") {
    cmdLed(rest);
  } else if (keyword == "result") {
    cmdResult(rest);
  } else if (keyword == "servo") {
    cmdServo(rest);
  } else if (keyword == "motor") {
    cmdMotor(rest);
  } else if (keyword == "s1") {
    cmdS1(rest);
  } else if (keyword == "s2") {
    cmdS2(rest);
  } else if (keyword == "buzzer") {
    cmdBuzzer(rest);
  } else if (keyword == "beep") {
    startBeeps(rest.toInt());
    Serial.print("Beep x"); Serial.println(rest.toInt());
  } else if (keyword == "watchdog") {
    if (rest == "on") { watchdogEnabled = true; Serial.println("Watchdog ON"); }
    else if (rest == "off") { watchdogEnabled = false; Serial.println("Watchdog OFF"); }
    else Serial.println("Usage: watchdog <on|off>");
  } else {
    Serial.println("Unknown command. Type 'help'.");
  }
}

void cmdResult(String args) {
  // result <matang|setengah|mentah|none> : LED eksklusif + 1 beep konfirmasi
  args.toLowerCase();
  if (args == "matang" || args == "green")        lastResult = 1;
  else if (args == "setengah" || args == "yellow") lastResult = 2;
  else if (args == "mentah" || args == "red")      lastResult = 3;
  else if (args == "none" || args == "off")        lastResult = 0;
  else { Serial.println("Usage: result <matang|setengah|mentah|none>"); return; }

  applyResultLeds();
  if (lastResult != 0) startBeeps(1);
  Serial.print("Result -> "); Serial.println(args);
}

void cmdLed(String args) {
  int space = args.indexOf(' ');
  if (space == -1) {
    Serial.println("Usage: led <name|pin> <0|1>");
    return;
  }
  String target = args.substring(0, space);
  String valStr = args.substring(space + 1);
  valStr.trim();
  int val = valStr.toInt();

  int pin = -1;
  for (int i = 0; i < numLeds; i++) {
    if (target == ledNames[i] || target == String(ledPins[i])) {
      pin = ledPins[i];
      break;
    }
  }
  if (pin == -1) {
    Serial.println("Unknown LED. Use: green, yellow, red, or pin number.");
    return;
  }
  digitalWrite(pin, val ? HIGH : LOW);
  Serial.print("LED "); Serial.print(target);
  Serial.print(" -> "); Serial.println(val ? "ON" : "OFF");
}

void cmdServo(String args) {
  int space = args.indexOf(' ');
  if (space == -1) {
    Serial.println("Usage: servo <1|2> <angle 0-180>");
    return;
  }
  int id = args.substring(0, space).toInt();
  int angle = args.substring(space + 1).toInt();
  angle = constrain(angle, 0, 180);

  if (id == 1) {
    servo1.write(angle);
    Serial.print("Servo 1 -> "); Serial.println(angle);
  } else if (id == 2) {
    servo2.write(angle);
    Serial.print("Servo 2 -> "); Serial.println(angle);
  } else {
    Serial.println("Servo ID must be 1 or 2.");
  }
}

void cmdMotor(String args) {
  if (args == "stop") {
    stopMotor();
    Serial.println("Motor STOP");
  } else if (args == "forward" || args == "f") {
    digitalWrite(motorIN1, HIGH);
    digitalWrite(motorIN2, LOW);
    motorRunning = true;
    Serial.println("Motor FORWARD");
  } else if (args == "backward" || args == "b") {
    digitalWrite(motorIN1, LOW);
    digitalWrite(motorIN2, HIGH);
    motorRunning = true;
    Serial.println("Motor BACKWARD");
  } else {
    Serial.println("Usage: motor <stop|forward|backward>");
  }
}

void cmdS1(String args) {
  if (args == "open") {
    servo1.write(SERVO_OPEN_ANGLE);
    Serial.print("Servo 1 -> OPEN ("); Serial.print(SERVO_OPEN_ANGLE); Serial.println(")");
  } else if (args == "close") {
    servo1.write(SERVO_CLOSE_ANGLE);
    Serial.println("Servo 1 -> CLOSE (0)");
  } else {
    Serial.println("Usage: s1 <open|close>");
  }
}

void cmdS2(String args) {
  if (args == "open") {
    servo2.write(SERVO_OPEN_ANGLE);
    Serial.print("Servo 2 -> OPEN ("); Serial.print(SERVO_OPEN_ANGLE); Serial.println(")");
  } else if (args == "close") {
    servo2.write(SERVO_CLOSE_ANGLE);
    Serial.println("Servo 2 -> CLOSE (0)");
  } else {
    Serial.println("Usage: s2 <open|close>");
  }
}

void cmdBuzzer(String args) {
  if (args == "on") {
    digitalWrite(buzzerPin, HIGH);
    Serial.println("Buzzer ON");
  } else if (args == "off") {
    digitalWrite(buzzerPin, LOW);
    Serial.println("Buzzer OFF");
  } else {
    Serial.println("Usage: buzzer <on|off>");
  }
}

void printHelp() {
  Serial.println(F("--- HELP ---"));
  Serial.println(F("ping                    - keep-alive (balas 'pong'), reset heartbeat"));
  Serial.println(F("watchdog <on|off>       - failsafe: motor auto-stop bila Pi diam >2s"));
  Serial.println(F("result <matang|setengah|mentah|none> - LED hasil + 1 beep"));
  Serial.println(F("led <name|pin> <0|1>    - Control LED (green/yellow/red / 11/12/13)"));
  Serial.println(F("beep <n>                - bunyikan buzzer n kali"));
  Serial.println(F("servo <1|2> <0-180>     - Set servo angle"));
  Serial.println(F("s1 <open|close>         - Servo1 open(51) / close(0)"));
  Serial.println(F("s2 <open|close>         - Servo2 open(51) / close(0)"));
  Serial.println(F("buzzer <on|off>         - Buzzer manual"));
  Serial.println(F("motor <stop|f|b>        - Motor (stop/forward/backward)"));
  Serial.println(F("help                    - Show this help"));
}
