# คัดบริบทบ้านออกจากพื้นที่สีเขียวที่เข้าข่ายสวนส่วนรวม

ตามคำตอบผู้ใช้วันที่ 25 ตุลาคม 2569: ตัดบริเวณที่ปะปนกับบ้านและยังไม่ชัดออกก่อน ยอมเสียต้นไม้ริมทางหรือสวนส่วนรวมใกล้บ้านบางส่วน เพื่อให้ผลหลักเน้นบริเวณที่ควรตรวจเป็นพื้นที่ส่วนรวม

## แยกสองคำถาม

- vegetation: พิกเซลนี้เป็นพืชหรือไม่ ต้นไม้ในบ้านยังคงเป็นพืช
- eligible_green: พิกเซลนี้ควรถูกเสนอเป็นพื้นที่สวนส่วนรวมหรือไม่ ตามเกณฑ์คัดเบื้องต้น ต้นไม้ในบริบทบ้านไม่ให้นับ

เก็บ labels เดิมไว้ ไม่แก้ต้นไม้ในบ้านให้กลายเป็นหลังคาหรือ nonvegetation เพิ่ม data/labels/assistant/assistant-eligible-green.geojson 42 core โดยคง vegetation_class เดิมไว้ มี 6 core พืชในบริบทบ้านที่ผู้ช่วยตีความและคัดออกตามนโยบาย ส่วนพืชอื่นที่ไม่มีหลักฐานส่วนรวมเป็น uncertain สำหรับ eligibility ไม่แต่ง positive public-park labels จากสีเขียวเพียงอย่างเดียว คำตอบชุดนี้ยังไม่ใช่ ground truth และยังไม่ใช้ฝึก ML

## การคัดทั้งภาพที่ใช้จริง

1. ใช้ candidate ทั้งภาพเดิมบนกริด 0.5 เมตรและ exclusions snapshot เดิม ตรวจ hashes ก่อนอ่าน
2. ตัด footprint อาคารทุกชนิดพร้อมระยะ 8 เมตร
3. ตัด landuse=residential พร้อมระยะ 10 เมตร
4. ตัดบริเวณรอบ footprint ที่ระบุ house/residential/apartments/terrace/detached/semidetached_house/bungalow/dormitory ระยะ 20 เมตร รวม access=private/no/customers/permit จาก polygon
5. ตัดเส้นบาง/ส่วนยื่นด้วย disk opening รัศมี 3 เมตร แล้วกรองกลุ่ม 4 ทิศซ้ำ ขั้นต่ำ 300 ตร.ม. ไม่เติมพืชเพิ่ม
6. สร้าง halo ใหม่และตัด alpha เป็นศูนย์บน exclusion mask ด้วย จึงไม่ปล่อยสีจางแผ่กลับทับบริเวณบ้านที่กันไว้

ระยะ 8/10/20 เมตร และรัศมี 3 เมตรเป็นค่าทดลองของโครงการภายใต้นโยบายผู้ใช้ ไม่ใช่ขอบกรรมสิทธิ์หรือมาตรฐานกรุงเทพมหานคร ผลที่เหลือยังเป็น candidate ไม่ใช่สวนสาธารณะที่ยืนยันสิทธิแล้ว OSM ที่ไม่ครบยังทำให้มีบ้านที่ไม่ถูกกันออกได้ ห้ามกล่าวว่าเอาสวนในบ้านออกได้ทั้งหมด

การตรวจบ้านใช้ข้อมูลบริบท ไม่ได้อ้างว่าฝึก classifier ใหม่จาก labels จำนวนน้อย การยืนยันหลังคา/สวนส่วนตัวต้องมี independent labels และข้อมูลที่ดิน/การเข้าถึงเพิ่มตามรายงานเดิม

## เรียกใช้งาน

ค่า data/scenes.json และ CLI ตั้งเกณฑ์ใหม่นี้แล้ว เมื่อรัน --all ให้เลือก output ใหม่ จะใช้กับทั้งสามภาพ โค้ดฐาน grid.py ของเพื่อนไม่ถูกแก้

```python
from greensight import analyse_scene

result = analyse_scene(
    'Images/Theos00.tif', 'Output/my-strict-scene',
    scene_id='Theos00', red_band=3, nir_band=4,
    context_path='data/exclusions/Theos00.geojson',
    registry_path='data/registry/parks15.geojson',
    building_buffer_m=8, house_buffer_m=20, residential_buffer_m=10,
    clean_radius_m=3,
)
```


ในการประมวลผลซ้ำจากผลเดิม ต้องใช้ context bytes ที่ hashes ตรงกับ parent เดิม สำเนาที่ git เก็บมีเนื้อหาเดียวกับ data ปัจจุบัน แต่รูปแบบ CRLF/BOM ต่างกัน จึงกู้ bytes จาก commit 1817988 และตรวจ SHA256 ตรงก่อนใช้ ไม่เปลี่ยนเนื้อหาข้อมูลเพื่อให้ผ่าน hash

## แก้กรณีที่ผู้ใช้ชี้ใต้ลานสนามบิน

เพิ่ม area-exclusions.geojson เป็น polygon บริบทบ้านจากการตีความ source preview Theos00 ขนาด 1000×1000 ซึ่งตรงกับ native crop 6000×6000 จึงแปลงพิกัดกรอบด้วย affine เดิมได้ ไม่เลื่อนหมุดหรือภาพ ใช้เฉพาะ target eligible_green ไม่เปลี่ยน vegetation truth ให้ผิดความหมาย

กรอบนี้เป็น assistant visual policy exclusion ตามการชี้แก้ของผู้ใช้ ไม่ใช่ขอบกรรมสิทธิ์ที่ตรวจรับรองแล้ว คัดทั้ง green core และ alpha ของ halo ออกจากกรอบ และตั้งใน data/scenes.json เพื่อรันซ้ำได้ ผลแยกที่ Output/archive/runs/nike-house-correction-20261025; Theos00 เหลือ candidate 363144.25 ตร.ม. อีกสองภาพไม่เปลี่ยน พื้นที่สีเขียวลดลง 9498.75 ตร.ม. จากรอบก่อน ไม่ใช่พื้นที่ polygon ทั้งกรอบ

clean_saved_results เก็บบริเวณ alpha=0 ของ parent ไว้ด้วย เพื่อไม่ให้การสร้าง halo รอบใหม่ระบายกลับเข้า exclusion เดิม ทดสอบ regression ด้วย polygon ที่ใช้เฉพาะ scene และรักษา NoData/ข้อมูลต้นฉบับ รวมชุดทดสอบทั้งหมด 44 ข้อผ่าน
