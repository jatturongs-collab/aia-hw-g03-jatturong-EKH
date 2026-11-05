# บันทึกขั้นตอน (process log)

> เพิ่ม 1 entry ทุกครั้งก่อน commit ต่อท้ายไฟล์ ห้ามลบของเก่า
> ผู้สอนอ่านไฟล์นี้เพื่อดูวิธีคิดของคุณ ไม่ใช่แค่ผลงานสุดท้าย
> ถ้าใช้ AI ช่วยทำงาน AI จะเขียน entry ให้ตาม AGENTS.md ถ้า commit เอง ให้เขียนเองตามแบบด้านล่าง

---

## รอบ 1 · 5 พ.ย. 2569

- **ทำอะไร:** ตั้ง repo จาก template: clone ไว้ใต้ `homework/`, เพิ่ม `.gitignore` กันข้อมูลดิบ (`paper/`, `set/`, `fetch_thaivi/`, `report/`, `data/`), กรอก README, ร่าง `spec.md` และ `help.md`
- **เครื่องมือ / model:** Claude Desktop (Code) · Sonnet 5.5 · Plan mode ก่อนลงมือ
- **Prompt ที่ใช้:**

```text
EKH Stock analysis skill create and delight from skill หลัก คือ thai-hospital-deepdive.
But we need to work follow this github template.
What do you recommend how can I do step by step and later we need to upload into github
```

- **ผลที่ได้:** ได้แผน 4 รอบ (setup → ย้าย skill → ผลลัพธ์ → เอกสาร) และร่าง spec ที่ตอบ 5 หัวข้อของ template ยังต้องให้เจ้าของโปรเจกต์ตรวจเป้าหมายใน spec
- **ตัดสินใจอะไร และเพราะอะไร:** เลือกย้าย skill ทั้งชุด (ตัวเลือก B) ไม่ทำฉบับย่อ เพราะอยากให้ผลงานเป็น skill ตัวจริงที่ใช้ต่อได้ ส่วนข้อมูลดิบไม่ขึ้น repo เพราะเป็นข้อมูลลิขสิทธิ์และไฟล์ใหญ่
- **ขั้นต่อไป:** ย้าย skill เข้า `.claude/skills/ekh-deepdive/`

---

## รอบ 2 · 5 พ.ย. 2569

- **ทำอะไร:** คัดลอก skill `thai-hospital-deepdive` (SKILL.md, scripts, references, assets รวม 45 ไฟล์) ไปไว้ที่ `.claude/skills/ekh-deepdive/` ไม่เอา `.git`, `__pycache__` และโฟลเดอร์ `examples/`
- **เครื่องมือ / model:** Claude Desktop (Code) · Sonnet 5.5
- **Prompt ที่ใช้:**

```text
B  (เลือกย้าย skill ทั้งชุด)
/mnt/c/ai -> '/mnt/g/My Drive/00_AI_Project/' is same as G:\My Drive\00_AI_Project\
```

- **ผลที่ได้:** สแกนหา key/secret ไม่พบ สคริปต์อ่าน root จากตัวแปร `AI_ROOT` จึงไม่ต้องแก้ path และ EKH อยู่ใน taxonomy หมวด 3 อยู่แล้ว ไม่ติดตัวกัน NotHospital
- **ตัดสินใจอะไร และเพราะอะไร:** ไม่เอา `examples/` (รายงาน VIH และ RJH) ขึ้น repo เพราะมีการพูดถึงบทวิเคราะห์โบรกเกอร์ และผลงานของ EKH เองใน `output/` ก็เป็นตัวอย่างอยู่แล้ว
- **ขั้นต่อไป:** นำรายงานและโมเดลของ EKH เข้า `output/` พร้อมบันทึกบทเรียน

---

## รอบ 3 · 5 พ.ย. 2569

- **ทำอะไร:** นำรายงานเชิงลึก EKH (md/html), snapshot Q2/2569 (md/html) และโมเดลการเงิน Excel (xlsx + md) เข้า `output/` และบันทึกบทเรียนใน `PROJECT_MEMORY.md`
- **เครื่องมือ / model:** Claude Desktop (Code) · Sonnet 5.5
- **Prompt ที่ใช้:**

```text
output/ (อย่างน้อย 1 screenshot หรือลิงก์) > output is .md .html and finance report in excel . , you can proceed .
jatturong ตรวจแล้วทำได้เลย
```

- **ผลที่ได้:** ได้ผลงานครบ 3 รูปแบบใน `output/` ไฟล์เหล่านี้คัดลอกมาจากรายงานที่สร้างไว้ก่อนหน้า (deepdive v1, finance model v4, snapshot v2) ไม่ได้รันใหม่ด้วยสำเนา skill ใน repo สแกนไม่พบ key หรือข้อมูลพอร์ตจริง แต่พบตาราง Jitta และการอ้างโบรกเกอร์ 1 บรรทัด
- **ตัดสินใจอะไร และเพราะอะไร:** เจ้าของโปรเจกต์เลือกใช้ไฟล์เดิมตามที่เป็นอยู่ เพราะต้องการส่งก่อน Repair Clinic วันเสาร์ แล้วถามผู้สอนผ่าน `help.md` ข้อ 1 แทนการตัดเอง
- **ขั้นต่อไป:** ตรวจ `spec.md` อีกรอบ, ถามผู้สอนเรื่อง Jitta, และรันรายงานใหม่ด้วยสำเนา skill ใน repo ถ้ามีเวลา

---

## รอบ 4 · 5 พ.ย. 2569

- **ทำอะไร:** เปลี่ยนสถานะ `spec.md` จาก draft เป็น final และสถานะใน README เป็น "พร้อมตรวจ"
- **เครื่องมือ / model:** Claude Desktop (Code) · Sonnet 5.5
- **Prompt ที่ใช้:**

```text
1.. go ahead , 2 &3&4 ignor . .5 . how I do rerun again .
```

- **ผลที่ได้:** เจ้าของโปรเจกต์ตรวจ spec แล้ว ถือเป็นฉบับพร้อมตรวจ ส่วนการส่งฟอร์ม, คอมเมนต์ผู้สอน และเรื่อง Jitta ขอข้ามไปก่อน
- **ตัดสินใจอะไร และเพราะอะไร:** ยังไม่รันรายงานใหม่ในรอบนี้ เพราะต้องการดูวิธีรันก่อนตัดสินใจ
- **ขั้นต่อไป:** ถ้าจะรันซ้ำ ใช้ skill ใน repo ด้วย `AI_ROOT` แล้วนำผลใหม่เข้า `output/`

---
