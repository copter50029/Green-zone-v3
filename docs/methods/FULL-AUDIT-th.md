# ตรวจทั้งสามภาพและแยกชั้นรอตรวจ — 25 ตุลาคม 2569

## สิ่งที่ตรวจจริง

รัน TIFF ต้นฉบับทั้งสามภาพใหม่ด้วยค่าตั้งล่าสุด อ่าน window 512×512 รวม partial edges ก่อนกรองพื้นที่ จากนั้นตรวจซ้ำอีก pass เทียบ raw mask กับข้อมูลทุก window ตรวจ hashes, CRS/affine, กรอบข้อมูลใช้งานได้, NoData ครบทุก band, ไม่มีการเพิ่มพิกเซลพืช, จำนวนพิกเซล/พื้นที่ และขนาดทุก connected component

รอบแรกมี source pixels รวม 1,668,988,808 พิกเซล ซึ่ง **รวม NoData** ด้วย ภายในกรอบที่ใช้ได้จริงมี 108,000,000 พิกเซล (36 ล้านต่อภาพ) การนับนี้เป็น software consistency ไม่ใช่จำนวน labels หรือเปอร์เซ็นต์ accuracy

จัด source RGB / overlay คู่กัน 432 ช่อง ขนาด 500×500 พิกเซลหรือ 250×250 เมตร ครอบคลุม native crop ทั้งหมด 36 ล้านพิกเซลต่อภาพ ไม่ข้ามช่องที่ไม่พบ candidate มี 12 contact sheets ที่ Output/evidence/visual-review ผู้ช่วยตรวจบริบทที่ระดับภาพย่อครบแล้ว แต่ไม่ได้รับรองชนิดต้นไม้หรือสิทธิที่ดินทุกพิกเซล

## สิ่งที่แก้จากการตรวจภาพ

พบต้นไม้/ลานเขียวในบริบทบ้านที่ OSM ไม่ครบ จึงเพิ่ม 86 review-cell polygons ใน data/labels/policies/area-exclusions.geojson พร้อม scene/cell/เหตุผล แยกจากกรอบที่ผู้ใช้ชี้ใต้สนามบินเดิม กรอบใหม่เป็นการคัดแบบอนุรักษ์ตามคำตอบผู้ใช้ว่าให้ตัดบริเวณกำกวมใกล้บ้านออกก่อน

กรอบ 250 เมตรเป็นขอบเขตเซลล์ตรวจ ไม่ใช่แปลงที่ดิน อาจกันถนนหรือพืชส่วนรวมใกล้บ้านออกด้วย ต้องปรับกรอบใน QGIS เมื่อมีขอบเขตหรือหลักฐานดีกว่า เป็น policy exclusion ที่ผู้ช่วยตีความ ไม่ใช่ semantic training ground truth และไม่เปลี่ยนต้นไม้ในบ้านให้กลายเป็น nonvegetation

บันทึกการตรวจทุกช่องใน data/labels/review/visual-cell-review.json สถานะ independent_human_review ยัง pending ทุกแถว ไม่แอบใช้ข้อมูลตรวจบริบทนี้อ้าง accuracy

## กติกาสองกลุ่มตามคำตอบผู้ใช้

- สนามบิน ลานจอดเครื่องบิน และแนวรางที่เห็นชัด: แยกเป็นชั้นสีเหลืองรอตรวจ ไม่รวม candidate_area_m2 ของผลหลัก กรอบ source-based อยู่ data/labels/policies/pending-areas.geojson ไม่ใช่เขตทาง/เขตสนามบินที่รับรอง
- สนามกีฬา โรงเรียน วัด รีสอร์ต หรือโครงการจัดสรรที่อาจมีพื้นที่ร่วม: เก็บเป็น candidate เมื่อไม่ถูกตัดด้วยข้อมูลบริบทที่มี แต่ระบุว่าตัวสถานที่และการเข้าถึงยังไม่ยืนยัน ไม่ตีความสีเขียวเป็นสวนสาธารณะอัตโนมัติ

ยังไม่มีกรอบ transport ที่ตรวจยืนยันว่าครบในทุกภาพ ชั้น pending ของภาพที่ไม่มี polygon จะว่าง หมายถึงยังไม่ได้ระบุบริเวณลักษณะนี้ในภาพนั้น ไม่ใช่หลักฐานว่าไม่มีพื้นที่จำกัดสิทธิ

## โค้ดสั้นสำหรับทีม

```python
from run_nike import run_all
results = run_all(out_dir='Output/my-reviewed-run')
```

run_all อ่าน config เดียว รวมพื้นที่บ้านที่คัดด้วยสายตาและ pending areas ไว้ด้วย `greensight.pending.separate_pending` แยก mask ออกจากกันและคำนวณส่วนเล็กที่ตกเกณฑ์ 300 ตร.ม. หลังแบ่งพื้นที่ ตรวจสมการ:

pre_partition_candidate_area_m2 = main_candidate_area_m2 + pending_candidate_area_m2 + subminimum_fragments_removed_after_partition_m2

ห้ามนำ pending_candidate_area_m2 ไปบวกเป็นพื้นที่สวน ส่วน main_candidate_area_m2 เองยังเป็นพื้นที่เสนอให้ตรวจ ไม่ใช่สวนที่ได้รับการรับรอง

ไฟล์ใหม่ pending-mask.tif เป็น 0/1/255 บนกริดเดิม และ pending.tif เป็น RGBA สีเหลืองเฉพาะ candidate ที่แยกไว้ ไม่มี halo ของผลหลักในบริเวณ pending ยืนยันว่า main/pending ไม่ซ้อนกันและไม่เพิ่มพืชจาก raw mask

## จุดที่ยังต้องมีคนหรือหลักฐานเพิ่ม

ไม่มีคนตรวจ labels อิสระ ไม่มี metadata calibration เฉพาะไฟล์ครบ ไม่มีขอบกรรมสิทธิ์/ทางเข้า/เวลาเปิดปัจจุบันครบ จึงไม่มี accuracy จริง การตรวจซ้ำด้วยโปรแกรมและดูภาพย่อไม่สามารถแทนหลักฐานเหล่านี้ได้ ภาพ THEOS01 อยู่คนละตำแหน่งกับกรุงเทพฯ ตามพิกัดต้นฉบับ จึงไม่ใช้การไม่มีหมุดทะเบียนกรุงเทพฯ ตัดสินว่าไม่มีสวนในภาพ

## ผลสุดท้ายหลังตรวจภาพและตอบนโยบายครบ

| ภาพ | Candidate ผลหลัก ตร.ม. | ชั้นรอตรวจ ตร.ม. | กลุ่มหลักที่ตรวจ |
| --- | ---: | ---: | ---: |
| Theos00 | 160,152.75 | 180,615.50 | 104 |
| Theos01 | 2,161,651.25 | 0.00 | 622 |
| Theos02 | 305,740.00 | 0.00 | 195 |

หลักฐาน source-pixel consistency และ component checks ครบทั้งสามภาพอยู่ Output/latest/analysis/audit-all.json เก็บโค้ด exact bytes ตาม hashes ได้ 14/14 modules ต่อภาพ และ input/config/policy snapshots ใน inputs/ ตรวจ native counts, exclusions ทั้ง core และ alpha, pending ไม่ซ้อน main และไม่เพิ่มพืชจาก raw mask

ผลล่าสุดอาจต่างจากการคัดต่อจาก mask เก่าเล็กน้อย เพราะรันจาก radiometry ใหม่และใช้ polygon ก่อน opening/area filtering เช่น Theos00 รอบก่อนเพิ่ม 86 เซลล์และ pending ได้ 363082.25 ตร.ม. ต่างจาก cached correction 363144.25 ตร.ม. 62 ตร.ม. จึงใช้ full-scene rerun ล่าสุดเป็น authoritative run ไม่ผสมตัวเลขข้ามรอบ

Tests รันสำเร็จล่าสุด 46 ข้อผ่าน รวม pending partition/native export/audit การรันซ้ำหลังอัปเดต README ถูก Windows ปฏิเสธการเปิด Python ก่อนเริ่ม tests แม้ grant read permission แล้ว จึงบันทึกเป็น blocked repeat ไม่ใช่ pass ครั้งใหม่ ไม่ใช่ failure ของ test cases โค้ดไม่เปลี่ยนหลังการรันสำเร็จนั้น และตรวจ file hashes/catalog/README/report links ด้วย PowerShell ต่อจนครบ

## ปรับ scope เป็น backend-only (25 ตุลาคม 2569)

ลบตัวสร้าง HTML/ชุดส่งออกเว็บและ tests เฉพาะเว็บตามคำสั่งผู้ใช้ เก็บ tests ตรวจ labels ไว้แยกไฟล์ และให้ run_all/clean_saved_results เขียน summary-all.json โดยตรง ไม่สร้าง index.html

รัน backend tests ใหม่ด้วย Python 3.12.14 ได้ 46 ข้อผ่าน และรัน run_all กับ TIFF tile จริง 2000×2000 พร้อม audit ทุกพิกเซลผ่าน: valid 4,000,000 พิกเซล, candidate 6,597.75 ตร.ม., ไม่มี HTML ผลอยู่ Output/latest/smoke ส่วนการเทียบทะเบียนดอนเมืองกับ TIFF ทั้งสามภาพอยู่ Output/latest/parks

เอกสาร audit ก่อนหน้านี้เป็นหลักฐาน ณ scope เดิม ไฟล์เว็บและโมดูลเว็บใน code-used ถูกลบออกแล้วตามคำสั่งล่าสุด จึงไม่อ้างว่า archive เก่ามีไฟล์ครบทุก module ในสถานะปัจจุบัน
