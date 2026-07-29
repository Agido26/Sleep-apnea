/*
  ECG Real-Time Data Acquisition via USB
  Project: Sleep Apnea Screening Tool
  Sampling Frequency: 250 Hz (4 ms interval)
  Baud Rate: 115200
*/

// تعريف منافذ الأردوينو
const int ecgPin = A0;        // منفذ قراءة إشارة الـ ECG التناظرية
const int loPlusPin = 10;     // (اختياري) منفذ LO+ لحساس AD8232 لكشف انفصال الأقطاب
const int loMinusPin = 11;    // (اختياري) منفذ LO- لحساس AD8232

// إعدادات تردد العينات (Sampling Frequency)
const unsigned long sampleIntervalMicros = 4000; // 4000 us = 4 ms -> fs = 250 Hz
unsigned long previousMicros = 0;

void setup() {
  // تهيئة الاتصال التسلسلي بسرعة عالية عبر USB
  Serial.begin(115200);
  
  // تهيئة منافذ كشف الأقطاب كمدخلات (إذا لم تكن تستخدمها، يمكنك تعليق هذين السطرين)
  pinMode(loPlusPin, INPUT);
  pinMode(loMinusPin, INPUT);

  // الانتظار حتى يستقر الاتصال
  while (!Serial) {
    ; // انتظر اتصال الـ USB
  }
}

void loop() {
  unsigned long currentMicros = micros();

  // التحقق مما إذا مر الوقت المحدّد لأخذ عينة جديدة (250Hz)
  if (currentMicros - previousMicros >= sampleIntervalMicros) {
    previousMicros = currentMicros; // تحديث العداد الزمني

    /* 
       فحص اتصال الأقطاب بجسم المريض (Leads-Off Detection):
       إذا كان أحد المنافذ يعطي قيمة HIGH فهذا يعني أن الأقطاب غير متصلة بشكل صحيح.
    */
    if ((digitalRead(loPlusPin) == 1) || (digitalRead(loMinusPin) == 1)) {
      // إرسال رمز خاص لبايثون ليتعرف على أن الحساس مفصول (مثلاً القيمة -1 أو 0)
      Serial.println(-1);
    } 
    else {
      // قراءة القيمة التناظرية (من 0 إلى 1023) وإرسالها لبايثون في سطر جديد
      int ecgValue = analogRead(ecgPin);
      Serial.println(ecgValue);
    }
  }
}