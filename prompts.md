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
