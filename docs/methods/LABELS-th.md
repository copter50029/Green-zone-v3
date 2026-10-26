# Labels จากภาพต้นฉบับ — 25 ตุลาคม 2569

## ผลที่ทำจริง

อ่าน RGB ต้นฉบับทั้งสามภาพจากกริดตรวจ 4×4 บริเวณต่อภาพ รวม 48 crop ขนาด 300×300 พิกเซล เลือก polygon สี่เหลี่ยมเฉพาะส่วนด้านในวัตถุ ไม่ใช้ prediction mask เป็นคำตอบ ได้ 42 polygon: 34 ตัวอย่างที่ผู้ช่วยตีความค่อนข้างชัด และ 8 uncertain ที่กันออกจากการใช้งานฝึก/ประเมิน

มีตัวอย่างต้นไม้/พืช หลังคาขาว น้ำเงิน เข้ม และเขียว ถนน ลาน เครื่องบิน ทางดิน และน้ำ เก็บต้นไม้ในบ้านเป็นพืชสำหรับ target=vegetation การเป็นสวนสาธารณะหรือการเข้าใช้ต้องใช้หลักฐานอีกชุด ห้ามเปลี่ยนความหมาย target เพื่อให้คะแนนดูดี

ไฟล์: `data/labels/assistant/assistant-vegetation.geojson` เก็บ scene, source_window, geometry EPSG:4326, class, object_type, split, region_id, เหตุผล และผู้ตีความ รูปและผล QA อยู่ `Output/evidence/labels/` ในเครื่อง

## การตรวจและการแก้คำตอบ

ตรวจภาพ source และส่วนขยายของ core ซ้ำ ลดขอบตัวอย่างที่ติดผิววัตถุอื่น กันเงามืด/ดินปนหญ้า/วัตถุสีน้ำตาลเป็น uncertain พื้นมืดที่เห็นเส้นจราจรระบุเป็นถนนแทนน้ำ หลังคาสีเขียวใช้รูปร่างเหลี่ยมและบริบทอาคารประกอบ ไม่ตัดสินจากสีเขียวอย่างเดียว ตัวอย่างพืชที่ระบุชนิดไม่ได้ใช้ vegetation_unspecified

แบ่งตามบริเวณ crop: คอลัมน์กริด 0–1 เป็น train, 2 เป็น validation, 3 เป็น test ทุก polygon ในบริเวณเดียวอยู่ split เดียวกัน ตรวจแล้ว polygon ไม่ซ้อนและต่าง split ห่างอย่างน้อย 50 เมตร ทั้งนี้ยังเป็นการเลือก core แบบเจาะจง ไม่ใช่การสุ่มตัวอย่างพื้นที่แบบเป็นตัวแทนทั้งหมด

`validate_labels()` ตรวจ ID, provenance, uncertainty, region/split, source window, geometry เทียบกริด TIFF ภายใน 1 มม., จำนวนพิกเซล/พื้นที่, NoData ครบทุก band, การซ้อนและระยะห่าง เก็บ SHA256 ของภาพหลักฐานแต่ละ crop ใน label-qa.json การผ่าน QA นี้ยืนยันความสอดคล้องของไฟล์ ไม่ใช่ความถูกต้องของการตีความวัตถุ

## สิ่งที่ยังยืนยันไม่ได้

origin=assistant_visual และ human_review_status=pending ทุกตัวอย่าง ไม่มีการอ้างชื่อมนุษย์ตรวจแทน ไม่มีตัวอย่างหญ้าล้วนที่ยืนยันได้ และ hard negative หลังคาเขียวมีเพียงหนึ่งตัวอย่าง ชุดนี้ยังเล็กเกินไปสำหรับกล่าวอ้างว่าโมเดลตัดหลังคาหรือพื้นที่ส่วนตัวได้ครบ ต้องเพิ่มวัตถุและบริเวณอิสระ พร้อมให้ผู้ตรวจทานยืนยันก่อนใช้รายงานความแม่นยำจริง

ไม่แก้ไฟล์ human test references ให้กลายเป็น reviewed และ evaluate_mask() ยังคงปฏิเสธ assistant labels การยืนยัน calibration ต้องอาศัย metadata เฉพาะผลิตภัณฑ์ การยืนยันสิทธิและการเข้าถึงสวนต้องมีหลักฐานปัจจุบันจากหน่วยงาน/ผู้ตรวจพื้นที่ ไม่สามารถสรุปจาก RGB หรือ labels ชุดนี้

## ใช้งานสั้นๆ

```python
import json
from greensight import validate_labels

with open('data/labels/assistant/assistant-vegetation.geojson', encoding='utf-8') as f:
    labels = json.load(f)
qa = validate_labels(labels, 'Images', minimum_split_gap_m=50,
                     evidence_dir='Output/evidence/labels')
print(qa['usable_assistant_labels'], qa['withheld_uncertain'])
```

หากเครื่องเพื่อนไม่มีภาพหลักฐาน ให้เว้น evidence_dir แต่ยังต้องมี TIFF ต้นฉบับใน Images ภาพดาวเทียม/crop ไม่ถูกอัปโหลด GitHub ไฟล์ source_window ใช้เปิดพื้นที่เดิมซ้ำใน QGIS ได้

ข้อจำกัด split ที่ตรวจพบ: Theos01 validation ยังไม่มี negative และ Theos02 test ยังไม่มี positive จึงยังประเมินรายภาพครบสองคลาสไม่ได้ ต้องเพิ่มตัวอย่างอิสระก่อนฝึก/รายงานผล ชุดนี้เป็นจุดเริ่มตรวจทาน ไม่ใช่ชุดข้อมูลที่ครบสมดุลแล้ว
