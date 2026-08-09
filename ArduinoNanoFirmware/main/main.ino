// #include artinya "sertakan pustaka lain ke program ini".
// Servo.h adalah pustaka bawaan Arduino untuk menggerakkan motor servo.
#include <Servo.h>

// =========================================================
//  PemilahBuahNaga - Firmware Arduino Nano
//  LED = hasil klasifikasi | Buzzer = event/alarm
//  + Heartbeat failsafe (motor auto-stop bila Pi diam)
//  Kompatibel dengan semua command lama (led/servo/motor/buzzer)
// =========================================================
//
//  CATATAN UNTUK PEMULA:
//  File ini ditulis dalam bahasa C++ (bukan Python) dan dijalankan di dalam
//  chip Arduino Nano — bukan di Raspberry Pi.
//
//  Pembagian tugasnya begini:
//    - Raspberry Pi = otak. Melihat lewat kamera, berpikir, mengambil keputusan.
//    - Arduino Nano = tangan & kaki. Hanya menerima perintah teks lalu
//                     menggerakkan motor, servo, LED, dan buzzer.
//
//  Setiap program Arduino WAJIB punya dua fungsi:
//    setup() -> dijalankan SEKALI saat Arduino menyala. Untuk persiapan.
//    loop()  -> dijalankan BERULANG selamanya, ribuan kali per detik.
//
//  Istilah penting:
//    pin        : kaki logam di papan Arduino, tempat kabel disambung.
//    digitalWrite(pin, HIGH/LOW) : memberi listrik (HIGH ≈ 5 volt) atau
//                 memutusnya (LOW = 0 volt) pada sebuah pin.
//    millis()   : jumlah milidetik sejak Arduino menyala. Dipakai untuk
//                 mengukur waktu tanpa menghentikan program.
//    const      : nilai tetap yang tidak boleh diubah selama program berjalan.
// =========================================================

// Array (larik) = wadah berisi beberapa nilai sekaligus, ditandai kurung siku [].
// Isinya diakses dengan nomor mulai dari 0: ledPins[0] adalah 11.
const int ledPins[] = {11, 12, 13};                      // nomor pin tiap LED
const char* ledNames[] = {"green", "yellow", "red"};     // nama tiap LED (urutan sama!)
const int numLeds = 3;                                   // jumlah LED
// green  = matang
// yellow = setengah matang
// red    = mentah

// Membuat dua objek servo. Objek ini yang nanti dipakai untuk memerintah servo.
Servo servo1;
Servo servo2;
const int servo1Pin = 4;             // servo 1 tersambung ke pin D4
const int servo2Pin = 5;             // servo 2 tersambung ke pin D5
const int SERVO_OPEN_ANGLE = 51;     // sudut saat lengan membuka (menghadang buah)
const int SERVO_CLOSE_ANGLE = 0;     // sudut saat menutup / "menampol"

// Motor konveyor dikendalikan modul driver L298N lewat dua pin.
// Kombinasi kedua pin menentukan arah putaran:
//   IN1=HIGH, IN2=LOW  -> maju
//   IN1=LOW,  IN2=HIGH -> mundur
//   keduanya LOW       -> berhenti
const int motorIN1 = 2;
const int motorIN2 = 3;

const int buzzerPin = 6;             // buzzer di pin D6

// ----- Heartbeat / watchdog -----
// Pengaman: kalau Raspberry Pi mendadak mati/hang saat motor sedang jalan,
// Arduino akan menghentikan motor sendiri. Tanpa ini, konveyor bisa berputar
// terus tanpa ada yang mengendalikan — berbahaya.
bool watchdogEnabled = false;              // default OFF -> GUI manual tetap normal
const unsigned long HEARTBEAT_TIMEOUT_MS = 2000;   // batas diam: 2000 ms = 2 detik
// "unsigned long" adalah tipe bilangan bulat besar tanpa nilai negatif.
// Dipakai untuk waktu karena millis() bisa mencapai angka yang sangat besar.
unsigned long lastCmdMs = 0;               // kapan perintah terakhir diterima
bool motorRunning = false;                 // apakah motor sedang berputar
bool faultState = false;                   // apakah sedang dalam kondisi gangguan
unsigned long faultBlinkMs = 0;            // patokan waktu kedipan LED saat fault
bool faultLedOn = false;                   // kondisi kedipan sekarang: nyala/mati

// ----- Non-blocking buzzer beeper -----
// "Non-blocking" artinya membunyikan buzzer TANPA menghentikan program.
// Cara mudah tapi salah adalah memakai delay(), karena selama delay() Arduino
// membeku total dan tidak bisa menerima perintah — motor pun jadi tak bisa
// dihentikan. Maka dipakai cara berbasis millis() seperti di bawah ini.
int beepRemaining = 0;              // sisa berapa kali bunyi lagi
bool beepActive = false;            // sedang dalam rangkaian bunyi?
bool beepIsOn = false;              // saat ini buzzer sedang bunyi atau diam
unsigned long beepPhaseMs = 0;      // kapan fase (bunyi/diam) sekarang dimulai
const int BEEP_ON_MS = 80;          // lama satu bunyi: 80 milidetik
const int BEEP_OFF_MS = 120;        // jeda antar bunyi: 120 milidetik

// ----- Ingat hasil klasifikasi terakhir (untuk restore setelah fault) -----
int lastResult = 0;  // 0=none, 1=green/matang, 2=yellow/setengah, 3=red/mentah


// setup() dijalankan SEKALI saja saat Arduino baru menyala atau di-reset.
void setup() {
  // Menyalakan komunikasi serial pada kecepatan 115200 bit per detik.
  // Angka ini WAJIB sama dengan yang diatur di serial_bridge.py.
  Serial.begin(115200);

  // Perulangan for menyiapkan ketiga LED sekaligus.
  // Cara membacanya: mulai i=0; ulangi selama i < 3; tiap putaran i bertambah 1.
  for (int i = 0; i < numLeds; i++) {
    pinMode(ledPins[i], OUTPUT);       // pin dipakai sebagai keluaran (mengirim listrik)
    digitalWrite(ledPins[i], LOW);     // pastikan semua LED mati saat mulai
  }

  // attach() memberi tahu objek servo, ia tersambung ke pin yang mana.
  servo1.attach(servo1Pin);
  servo2.attach(servo2Pin);
  // Kedua servo langsung ditutup agar posisinya pasti dan tidak menghalangi belt.
  servo1.write(SERVO_CLOSE_ANGLE);
  servo2.write(SERVO_CLOSE_ANGLE);

  pinMode(motorIN1, OUTPUT);
  pinMode(motorIN2, OUTPUT);
  // Kedua pin LOW = motor berhenti. Ini penting: jangan sampai motor langsung
  // berputar begitu Arduino menyala.
  digitalWrite(motorIN1, LOW);
  digitalWrite(motorIN2, LOW);

  pinMode(buzzerPin, OUTPUT);
  digitalWrite(buzzerPin, LOW);        // buzzer mulai dalam keadaan diam

  lastCmdMs = millis();                // mulai menghitung waktu dari sekarang
  Serial.println("System ready. Type 'help' for commands.");
}


// loop() dijalankan berulang-ulang selamanya, secepat yang chip mampu.
void loop() {
  // Waktu dibaca SEKALI di awal lalu dipakai bersama semua fungsi di bawahnya,
  // supaya semuanya memakai patokan waktu yang persis sama.
  unsigned long now = millis();

  // Serial.available() memberi tahu berapa banyak huruf yang sudah datang
  // dari Raspberry Pi dan menunggu dibaca.
  if (Serial.available() > 0) {
    // Baca sampai ketemu tanda ganti baris ('\n') — inilah penanda satu
    // perintah selesai, yang tadi ditambahkan oleh serial_bridge.py.
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();                        // buang spasi & enter di ujung
    lastCmdMs = now;                   // catat: Pi masih hidup (reset heartbeat)
    if (faultState) clearFault();   // command apapun = clear fault
    processCommand(cmd);
  }

  // Tiga fungsi ini dipanggil TIAP putaran. Masing-masing memeriksa sendiri
  // apakah sudah waktunya bertindak. Inilah pola non-blocking: semua pekerjaan
  // berjalan "bersamaan" tanpa ada yang saling menunggu.
  serviceHeartbeat(now);     // periksa apakah Pi masih hidup
  serviceBeeper(now);        // urus bunyi buzzer
  serviceFaultBlink(now);    // urus kedipan LED saat gangguan
}


// =========================================================
//  HEARTBEAT / FAILSAFE
// =========================================================
void serviceHeartbeat(unsigned long now) {
  // Hanya bertindak kalau watchdog aktif DAN motor sedang jalan.
  // Tanda ! berarti "tidak"; || berarti "atau".
  // Baris ini dibaca: kalau watchdog mati, ATAU motor tidak jalan, ATAU sudah
  // dalam kondisi fault -> keluar dari fungsi, tidak melakukan apa-apa.
  if (!watchdogEnabled || !motorRunning || faultState) return;
  // Sudah lewat 2 detik sejak perintah terakhir -> Pi kemungkinan mati/hang.
  if (now - lastCmdMs > HEARTBEAT_TIMEOUT_MS) {
    stopMotor();
    enterFault();
    Serial.println("FAULT: heartbeat lost, motor stopped");
  }
}

void enterFault() {
  // Masuk kondisi gangguan: LED berkedip + buzzer bunyi sebagai tanda bahaya.
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
  // Kedipkan tiap 300 milidetik.
  if (now - faultBlinkMs >= 300) {
    faultBlinkMs = now;
    // Tanda ! membalik nilainya: nyala jadi mati, mati jadi nyala.
    faultLedOn = !faultLedOn;
    // Ketiga LED dikedipkan bersamaan sebagai tanda darurat.
    // Bentuk "syarat ? nilaiA : nilaiB" adalah cara singkat if-else:
    // kalau faultLedOn benar pakai HIGH, kalau tidak pakai LOW.
    for (int i = 0; i < numLeds; i++) digitalWrite(ledPins[i], faultLedOn ? HIGH : LOW);
    // Buzzer ikut berkedip seirama LED.
    digitalWrite(buzzerPin, faultLedOn ? HIGH : LOW);
  }
}


// =========================================================
//  NON-BLOCKING BUZZER
// =========================================================
void startBeeps(int n) {
  // Fungsi ini TIDAK langsung membunyikan buzzer; ia hanya "memesan" agar
  // buzzer berbunyi n kali. Yang mengerjakan adalah serviceBeeper() di loop().
  if (n <= 0) return;
  beepRemaining = n;
  beepActive = true;
  beepIsOn = false;
  beepPhaseMs = 0;   // 0 = trigger langsung
}

void serviceBeeper(unsigned long now) {
  // Saat fault, buzzer dikuasai serviceFaultBlink -> jangan diganggu di sini.
  if (!beepActive || faultState) return;
  if (!beepIsOn) {
    // Sedang fase DIAM. Waktunya bunyi lagi kalau masih ada sisa DAN
    // (ini bunyi pertama, atau jeda diamnya sudah cukup).
    if (beepRemaining > 0 && (beepPhaseMs == 0 || now - beepPhaseMs >= BEEP_OFF_MS)) {
      digitalWrite(buzzerPin, HIGH);   // buzzer bunyi
      beepIsOn = true;
      beepPhaseMs = now;               // catat kapan fase bunyi dimulai
    } else if (beepRemaining == 0) {
      beepActive = false;              // jatah bunyi habis -> selesai
    }
  } else {
    // Sedang fase BUNYI. Matikan setelah 80 milidetik.
    if (now - beepPhaseMs >= BEEP_ON_MS) {
      digitalWrite(buzzerPin, LOW);
      beepIsOn = false;
      beepRemaining--;                 // satu bunyi selesai, kurangi sisanya
      beepPhaseMs = now;
    }
  }
}


// =========================================================
//  MOTOR
// =========================================================
void stopMotor() {
  // Kedua pin LOW = tidak ada beda tegangan = motor berhenti.
  digitalWrite(motorIN1, LOW);
  digitalWrite(motorIN2, LOW);
  motorRunning = false;
}


// =========================================================
//  LED HASIL KLASIFIKASI
// =========================================================
void applyResultLeds() {
  // Menyalakan tepat SATU LED sesuai lastResult, sisanya dimatikan.
  // Kenapa (i + 1)? Karena nomor array mulai dari 0, sedangkan lastResult
  // memakai 1/2/3 (dengan 0 berarti "tidak ada"). Jadi ledPins[0] cocok
  // dengan lastResult == 1, dan seterusnya.
  for (int i = 0; i < numLeds; i++) {
    digitalWrite(ledPins[i], ((i + 1) == lastResult) ? HIGH : LOW);
  }
}


// =========================================================
//  COMMAND PARSER
//  ("parser" = pembaca/pengurai perintah teks menjadi tindakan)
// =========================================================
void processCommand(String cmd) {
  // Dua perintah paling sering dipakai diperiksa lebih dulu agar cepat.
  if (cmd == "help") { printHelp(); return; }
  if (cmd == "ping") { Serial.println("pong"); return; }

  // Memecah perintah menjadi dua bagian pada spasi PERTAMA.
  // Contoh: "motor forward" -> keyword="motor", rest="forward"
  // indexOf(' ') memberi posisi spasi pertama, atau -1 kalau tidak ada spasi.
  int space1 = cmd.indexOf(' ');
  // Kalau tidak ada spasi, seluruh teks dianggap keyword dan rest kosong.
  String keyword = (space1 == -1) ? cmd : cmd.substring(0, space1);
  String rest = (space1 == -1) ? "" : cmd.substring(space1 + 1);
  rest.trim();

  // Rangkaian if-else memilih fungsi mana yang dipanggil sesuai keyword.
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
    // toInt() mengubah teks "3" menjadi angka 3.
    startBeeps(rest.toInt());
    Serial.print("Beep x"); Serial.println(rest.toInt());
  } else if (keyword == "watchdog") {
    if (rest == "on") { watchdogEnabled = true; Serial.println("Watchdog ON"); }
    else if (rest == "off") { watchdogEnabled = false; Serial.println("Watchdog OFF"); }
    else Serial.println("Usage: watchdog <on|off>");
  } else {
    // Perintah tak dikenal -> beri tahu, jangan diam saja.
    Serial.println("Unknown command. Type 'help'.");
  }
}

void cmdResult(String args) {
  // result <matang|setengah|mentah|none> : LED eksklusif + 1 beep konfirmasi
  // toLowerCase() menjadikan huruf kecil semua, agar "MATANG" tetap dikenali.
  args.toLowerCase();
  // Tiap hasil punya dua nama yang diterima (Indonesia & warna), supaya
  // perintah dari Pi maupun dari pengujian manual sama-sama jalan.
  if (args == "matang" || args == "green")        lastResult = 1;
  else if (args == "setengah" || args == "yellow") lastResult = 2;
  else if (args == "mentah" || args == "red")      lastResult = 3;
  else if (args == "none" || args == "off")        lastResult = 0;
  else { Serial.println("Usage: result <matang|setengah|mentah|none>"); return; }

  applyResultLeds();
  // Bunyi konfirmasi hanya bila ada hasil (bukan "none").
  if (lastResult != 0) startBeeps(1);
  Serial.print("Result -> "); Serial.println(args);
}

void cmdLed(String args) {
  // Perintah ini butuh 2 bagian: nama LED dan nilai 0/1.
  int space = args.indexOf(' ');
  if (space == -1) {
    Serial.println("Usage: led <name|pin> <0|1>");
    return;
  }
  String target = args.substring(0, space);       // "green" atau "11"
  String valStr = args.substring(space + 1);      // "0" atau "1"
  valStr.trim();
  int val = valStr.toInt();

  // Cari pin yang sesuai. -1 dipakai sebagai penanda "belum ketemu".
  int pin = -1;
  for (int i = 0; i < numLeds; i++) {
    // Boleh menyebut nama ("green") atau langsung nomor pin ("11").
    // String(ledPins[i]) mengubah angka pin menjadi teks agar bisa dibandingkan.
    if (target == ledNames[i] || target == String(ledPins[i])) {
      pin = ledPins[i];
      break;      // sudah ketemu -> hentikan pencarian
    }
  }
  if (pin == -1) {
    Serial.println("Unknown LED. Use: green, yellow, red, or pin number.");
    return;
  }
  // Di C++, angka selain 0 dianggap "benar". Jadi val=1 -> HIGH, val=0 -> LOW.
  digitalWrite(pin, val ? HIGH : LOW);
  Serial.print("LED "); Serial.print(target);
  Serial.print(" -> "); Serial.println(val ? "ON" : "OFF");
}

void cmdServo(String args) {
  // Perintah servo bebas sudut, dipakai saat kalibrasi manual.
  int space = args.indexOf(' ');
  if (space == -1) {
    Serial.println("Usage: servo <1|2> <angle 0-180>");
    return;
  }
  int id = args.substring(0, space).toInt();       // nomor servo: 1 atau 2
  int angle = args.substring(space + 1).toInt();   // sudut yang diminta
  // constrain(nilai, min, max) memaksa nilai tetap di rentang aman.
  // Ini melindungi servo dari perintah sudut mustahil (misal 500 derajat)
  // yang bisa membuatnya mentok dan rusak.
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
  // Bentuk singkat "f" dan "b" disediakan agar mudah diketik saat menguji
  // lewat Serial Monitor.
  } else if (args == "forward" || args == "f") {
    // Maju: IN1 diberi listrik, IN2 tidak.
    digitalWrite(motorIN1, HIGH);
    digitalWrite(motorIN2, LOW);
    motorRunning = true;      // penanda ini yang mengaktifkan pengawasan heartbeat
    Serial.println("Motor FORWARD");
  } else if (args == "backward" || args == "b") {
    // Mundur: kebalikannya, IN2 yang diberi listrik.
    digitalWrite(motorIN1, LOW);
    digitalWrite(motorIN2, HIGH);
    motorRunning = true;
    Serial.println("Motor BACKWARD");
  } else {
    Serial.println("Usage: motor <stop|forward|backward>");
  }
}

void cmdS1(String args) {
  // Jalan pintas untuk servo 1: cukup "open" atau "close", sudutnya sudah
  // ditetapkan di konstanta atas. Inilah yang dipakai sistem saat sortir.
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
  // Sama persis dengan cmdS1, hanya untuk servo 2.
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
  // Menyalakan buzzer terus-menerus (berbeda dengan "beep" yang berbunyi
  // sekian kali lalu berhenti sendiri).
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
  // F("...") adalah trik hemat memori khas Arduino: teksnya disimpan di memori
  // program (flash, 32 KB) alih-alih memori kerja RAM yang cuma 2 KB di Nano.
  // Tanpa F(), belasan baris teks bantuan ini saja bisa menghabiskan RAM dan
  // membuat Arduino tiba-tiba restart sendiri.
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
