# รับงาน Nike backend ต่อ

เป้าหมาย: ตรวจพืชจาก TIFF → คัดบริบทบ้าน/จุดเล็ก → heatmap → เทียบสวนในทะเบียน → ส่ง GeoTIFF/GeoJSON/JSON ให้ backend ส่วนอื่นเรียกใช้ ไม่มี UI หรือโมดูลส่งออกเว็บใน scope นี้

## เริ่มจาก 3 ไฟล์

1. README.md สำหรับคำสั่งและข้อจำกัดล่าสุด
2. data/scenes.json สำหรับ TIFF, bands, buffers และ policy polygons
3. run_backend.py (run_backend.cmd on Windows); run_nike.py / verify_parks.py เป็น entry points แล้วจึงอ่านฟังก์ชันใน greensight/

## ขอบเขตแต่ละโมดูล

- detect.py: อ่าน array และสร้าง class mask; ไม่ตัดสินสิทธิที่ดิน
- heatmap.py: morphology → กลุ่ม ≥300 ตร.ม. → RGBA/area stats
- exclusions.py: กันข้อมูลอาคาร/บ้านและกรอบคัดตามภาพ
- pending.py: แยกพื้นที่สนามบิน/แนวรางที่ระบุไว้ ไม่รวมยอดหลัก
- scene.py: ประมวลผลทั้งภาพและเขียนไฟล์ เก็บ hashes/status
- cleanup.py: คัด mask ที่บันทึกไว้ โดยตรวจ parent inputs
- park_lookup.py: หา registered points บน valid pixels ของ TIFF กรอง metadata เขตได้
- park_verify.py: งานตรวจสวนและหลักฐาน ไม่ยืนยันจากพืชใกล้หมุดอัตโนมัติ
- labels.py / label_review.py / evaluate.py: QA labels, คิวให้คนตรวจ และประเมินเฉพาะ references ที่มีคุณสมบัติครบ
- audit.py: ตรวจ source windows/native grids/area/exclusions/pending ทุกกลุ่ม

## กติกาที่ต้องรักษา

รวมภาพก่อนกรองกลุ่ม ไม่กรองแยก tile จนเกิด seam; รักษา NoData ครบทุก band; ไม่เพิ่มพิกเซลพืชด้วยการเติมช่องว่าง; pending ไม่รวมพื้นที่หลัก; ไม่เปลี่ยนต้นไม้ในบ้านเป็น nonvegetation เพื่อให้ accuracy ดูดี; ไม่เปลี่ยน assistant labels เป็น human-reviewed เอง

`make_heatmap` คืน dict: mask, rgba, stats ค่า source ต้องเป็น numpy class mask บนกริด square metre pixels เดียวกัน ไม่มีการแก้ array input

`find_parks_in_image` คืน GeoJSON พร้อม excluded_counts และสถานะทุกจุด needs_review พิกัดตรงกับทะเบียนเดิม ไม่ snap หมุดให้ชนพื้นที่สีเขียว ตัวกรอง don-mueang กรองข้อมูลเขตในทะเบียน ไม่ยืนยันเขตภาพทั้งหมด

## ตรวจสวนต่ออย่างไร

ใช้หน้าทางการ https://greener.bangkok.go.th/en/map-15-minute-garden/ และเก็บหลักฐานให้ครบ: ตำแหน่งจริง ทางเข้าที่ใช้ได้ สิทธิประชาชนและวันที่ตรวจ การมีพิกัดใน snapshot ยืนยันเพียงว่ามีรายการในทะเบียนชุดนั้น

record_park_review ต้องระบุผู้ตรวจ วันที่ decision และหลักฐาน HTTPS พร้อม scope position/public_access เพื่อยืนยันผล ห้ามกรอกชื่อผู้ตรวจแทนคนจริง หรือถือจำนวนต้นไม้รอบหมุดเป็นหลักฐานเปิดสวน

## Labels และงานที่ยังเหลือ

assistant-vegetation.geojson เป็นการตีความจาก RGB 42 core ไม่ใช่ ground truth ส่วน area-exclusions.geojson เป็นกรอบคัดตามนโยบาย ผู้ช่วยตีความ 86 เซลล์ 250 เมตรและกรณีผู้ใช้แก้ไว้ อาจคัดเกินขอบบ้านจริง ต้องปรับเมื่อมีหลักฐานที่ดีกว่า

ยังต้องมี labels อิสระ ยืนยัน band/calibration เฉพาะ TIFF และขอบเขต/การเข้าใช้จริง จึงจะกล่าวอ้าง precision/recall/IoU และว่าเป็นสวนส่วนรวมได้ ไม่ใช้การผ่าน tests แทน accuracy

## ผลตรวจโครงสร้างล่าสุด

backend-only tests รันผ่าน 46 ข้อด้วย Python 3.12.14 ในเครื่อง หลังถอดการสร้าง HTML/ส่งออกเว็บออกแล้ว การเทียบทะเบียนดอนเมืองบน TIFF จริงทั้งสามภาพได้ Theos00=2, Theos01=0, Theos02=0 ทั้งหมดที่พบยัง needs_review

คงข้อมูลต้นฉบับและผล native เดิมไว้ ประวัติ audit เก่าบันทึกโค้ด/ไฟล์ตาม scope ในเวลานั้น จึงอาจอ้างโมดูลเว็บที่ถูกลบออกตามคำสั่งล่าสุด ไม่ใช้ archive code-used เป็น import path ของโปรเจกต์ปัจจุบัน
