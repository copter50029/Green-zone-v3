> เอกสารร่างในเครื่องเท่านั้น ผู้ใช้สั่งยังไม่ส่ง GitHub/เปิด PR งานล่าสุดเพิ่ม full-scene processing และมี 27 tests ผ่าน ดู README หลักสำหรับขอบเขตปัจจุบัน

# Nike: green-zone detection, heatmap and park review functions

เพิ่ม Python functions สำหรับตรวจ candidate vegetation, กรองกลุ่มขั้นต่ำ 300 ตร.ม., สร้าง heatmap และเทียบหมุดสวน Greener Bangkok โดยไม่แก้ grid.py ของทีม

- `detect_green()` รับ band numbers และ valid/exclusion masks ชัดเจน
- `make_heatmap()` คืน mask / RGBA / patch statistics
- `prepare_park_review()` คืนงานตรวจจากทะเบียน และ `record_park_review()` บังคับข้อมูลผู้ตรวจ/หลักฐานก่อนยืนยัน
- README ภาษาไทย คู่มือฟังก์ชัน และตัวอย่าง run_nike.py สำหรับ tile/crop พร้อมผลที่เปิดใน QGIS ได้

Validation: `python -m unittest discover -s tests -v` ผ่าน 20 tests และทดลองไฟล์ tile จริงแล้ว

ข้อจำกัด: band mapping/calibration และ accuracy ยังไม่ยืนยัน; ratio อย่างเดียวไม่รับรองการตัดหลังคา/พื้นที่ส่วนตัว ต้องรวม tile cores ก่อนกรองกลุ่มเพื่อสรุปทั้ง scene; การยืนยันสวนและสิทธิการเข้าถึงยังต้องตรวจโดยคน

Base: main
Head: nike/green-zone-functions

หลัง login GitHub จาก VS Code แล้ว ส่ง branch ด้วย:

```powershell
git push -u origin nike/green-zone-functions
```

จากนั้นเปิด Pull request จาก branch นี้เข้า main และใช้ข้อความด้านบนเป็น description อย่า merge ก่อนเพื่อน review
