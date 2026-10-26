# วิธีประมวลผลเต็มภาพและสถานะการตรวจ — 25 ตุลาคม 2569

## ขอบเขตและเหตุผล

งาน Nike ใน Green-zone-v2 มีทางเรียกเดียว `run_nike.py --all` สำหรับ Theos00/01/02 แยกจาก grid.py ของทีม ไม่ย้าย TIFF หรือลบการแก้ชื่อภาพที่ผู้ใช้ทำไว้ โฟลเดอร์ผลครั้งนี้ `Output/archive/runs/nike-scenes-20261025` อยู่เฉพาะเครื่อง ไม่มีการ push/เปิด PR

ผลใช้ valid pixels ทั้งหมดของ TIFF ไม่ตัดตามกรอบ polygon เดิม ดังนั้นพื้นที่ฐานต่างจากรายงานเก่าที่ใช้กรอบศึกษาเอียง แต่ละภาพมี valid 36,000,000 พิกเซล = 9,000,000 ตร.ม. ผลบน mask/heatmap ที่ crop เป็น 6000×6000 พิกเซลยังอยู่บนกริด native 0.5 เมตรเดิม

## ขั้นตอนที่ทำจริง

1. อ่านทะเบียนภาพและ SHA256 ของ TIFF ก่อนรัน ตรวจ projected CRS หน่วยเมตร north-up square grid และ band numbers
2. เลื่อน window ขนาด 512×512 ตลอดแถว/คอลัมน์ รวม partial edges โดยไม่มีพิกเซลซ้ำ ใช้ band 1 NoData เป็นเพียงตัวข้าม window ว่าง จากนั้นตรวจความใช้ได้ครบทุก bands
3. คำนวณ raw-band ratio `(band4-band3)/(band4+band3)` threshold 0.35; 0.15 ถึงต่ำกว่า 0.35 เป็น uncertain; denominator ไม่บวกแต่ข้อมูล valid เป็น uncertain; NoData/ไม่ finite เป็น 255
4. เขียน raw-mask บนกริด TIFF เดิมให้ครบ รวม NoData ที่ไม่เขียนจริงแบบ sparse จากนั้นหากรอบ valid exact ไม่ใช้ overview หรือ sampling ประมาณกรอบ
5. ตรวจจำนวน valid ก่อน/หลังรวม และ crop เฉพาะกรอบ NoData ภายนอก ไม่ resample การเปลี่ยน origin เป็น offset จริงของกริดเดิมและบันทึกไว้ใน summary
6. อ่าน polygon จาก OSM snapshot ที่เก็บไว้ในเครื่อง: buildings + buffer ตาม cell-centre 2 เมตร, landuse=residential, access=private/no/customers/permit ตัดตามลำดับและนับพื้นที่ candidate ที่ตัดออกแบบไม่ซ้ำ ไม่สร้างขอบที่ดินจาก Point
7. รวม mask ทั้งภาพก่อน connected components แบบ 4 ทิศ เก็บกลุ่ม ≥300 ตร.ม. จากนั้นคำนวณ Euclidean distance transform และแสดง candidate สีเขียวพร้อม halo จางในรัศมี 50 เมตร ไม่มีการกรองแยก tile จึงไม่แตกกลุ่มที่ seam
8. เทียบทะเบียนสวน WGS84 กับกริดของผล เก็บเฉพาะหมุดบนข้อมูลภาพจริง คงพิกัดเดิม พร้อม candidate area/ระยะภายในวง 50 เมตรและ data coverage
9. บันทึก GeoTIFF/GeoJSON, summary, artifact hashes, source/code/config provenance และ status=complete เมื่อจบ สร้าง PNG ย่อและรายงาน HTML เฉพาะแสดงผล
10. ตรวจ hashes ของ artifacts จริงครบสามภาพ ตรวจ native transform/CRS จำนวน candidate/valid จากไฟล์ผล และเตรียมจุดตรวจ 51 จุดโดยไม่มีการเปลี่ยนเป็น labels

## ผลที่ได้

| ภาพ | Candidate หลัง exclusions/กรองกลุ่ม ตร.ม. | อาคารที่ตัดออก ตร.ม. | Residential ที่ตัดออก ตร.ม. |
| --- | --- | --- | --- |
| Theos00 | 473,661.50 | 2,210.50 | 352,299.50 |
| Theos01 | 2,796,586.50 | 24,726.75 | 64,109.00 |
| Theos02 | 621,733.25 | 3,761.25 | 99,289.25 |

พื้นที่ตัดออกเป็น candidate เดิมที่ทับกับแผนที่อ้างอิง ไม่ใช่ขนาดอาคาร/เขตอยู่อาศัยทั้งหมด Private-access removal เป็น 0 ทั้งสามภาพ ไม่ได้แปลว่าไม่มีพื้นที่ส่วนตัว แต่แปลว่าชั้นข้อมูลที่ใช้ไม่ตัด candidate เพิ่มในลำดับนี้

พื้นที่ valid ที่อยู่นอกกรอบความครอบคลุม OSM snapshot เดิม: Theos00 55,902.50, Theos01 75,308.25, Theos02 10,964.75 ตร.ม. พื้นที่เหล่านี้ยังไม่ได้ตรวจ exclusions ครบ ห้ามถือว่าไม่มีอาคาร/กรรมสิทธิ์ส่วนตัวโดยอัตโนมัติ

## Band และ calibration

[เอกสาร ArcGIS ของ ESRI หัวข้อ THEOS-2](https://doc.esri.com/en/arcgis-pro/latest/help/data/imagery/satellite-sensor-raster-types.html) ระบุ band order มาตรฐาน 1 Blue, 2 Green, 3 Red, 4 NIR สนับสนุนการตั้งค่าในโค้ด แต่ TIFF ที่ผู้ใช้มีไม่มี band descriptions และ aux.xml ที่พบมีสถิติ ไม่ใช่ product metadata ที่ยืนยันการจัดลำดับ/reflectance calibration เฉพาะไฟล์ จึงยังไม่ประกาศว่าเป็น calibrated NDVI หรือยืนยัน radiometric fidelity ของ pansharpened image

ไม่คัดค่าจาก paper มาแทน calibration ของภาพจริง และไม่เลือก threshold ใหม่เพื่อทำให้หมุดสวนมีสีเขียว

## ความแม่นยำและการตรวจตัวอย่าง

27 software tests ผ่าน รวม uint16/NoData, กลุ่มเท่ากับเกณฑ์ 300 ตร.ม., alpha/ระยะ, การเก็บ partial edges ครั้งเดียว, ผลเท่ากันเมื่อเปลี่ยนขนาด window, การคง NoData ใน sparse output, exclusions ไม่บวกพื้นที่ซ้ำ, การบังคับหลักฐานสวน, roundtrip GeoTIFF และการห้ามเขียนทับผลเดิม

ตัวอย่าง test เป็น synthetic fixtures เท่านั้น ไม่ใช่ labels จริง จำนวน reference polygons ที่คนตรวจแล้วยัง 0 จึง `real_accuracy=null` และ evaluation status เป็น `reviewed_labels_required` เตรียม templates แยก vegetation/eligible_green และฟังก์ชัน evaluate_mask แล้ว ไม่ใช้ pseudo-labels หรือ OSM masks เป็นคำตอบ test

`Output/archive/runs/nike-scenes-20261025/review-samples.geojson` มี 51 จุดตรวจ draft ทั้งจาก spatial grid/candidate/noncandidate ไม่มี class/reviewer/split ที่ยืนยัน ผู้ตรวจต้องตีความภาพและสร้าง polygon references แยกพื้นที่/วันอย่างอิสระก่อนใช้ประเมิน ไม่ใช้คิวที่เลือกจากโมเดลนี้เป็นตัวแทนประชากรโดยไม่ออกแบบ sampling เพิ่ม

## Park verification

พบทะเบียนสวน กทม. บน valid pixels ของ Theos00 จำนวน 2 จุด อีกสองภาพไม่มีหมุดจาก snapshot ที่ครอบคลุม กทม. นี้ จึงสรุปไม่ได้ว่าไม่มีสวนในภาพ

- row-476 สวนหย่อมหน้าบริษัทการท่าอากาศยานดอนเมือง: ภาพป้ายชื่อในทะเบียนและ Street View ธันวาคม 2025 สนับสนุนบริเวณสวนริมถนน แต่ไม่มีขอบสวน/ทางเข้าและการเข้าถึงปัจจุบันที่ยืนยัน ผล detector ไม่พบ retained candidate ในวง 50 เมตร เป็นกรณีที่ต้องตรวจ shadow/พืชขนาดเล็ก/bands/dates ต่อ
- row-35 สวนดอนเมืองประชากร 3: ลิงก์ Maps จากทะเบียนไปพิกัดเดิม แต่ Street View ตอบว่าไม่มีภาพ ณ จุดนั้น และ cached registry ไม่แนบภาพสวน จึงยังตรวจยืนยันทางเข้าหรือการเข้าถึงไม่ได้ การไม่มีภาพไม่ใช่หลักฐานว่าไม่มีสวน

บันทึก desk review แยกใน Theos00/park-review-desk.geojson พร้อมชื่อผู้ตรวจว่าเป็น assistant ไม่ใช่ field survey/human ground truth และไม่มีการย้ายหมุด ยืนยัน public-access records จริง 0 จุด

## ข้อจำกัดที่เหลือเป็นข้อมูลจริงที่ต้องมี

1. Product metadata สำหรับยืนยัน band identity/calibration เฉพาะไฟล์
2. Human-reviewed references ที่เป็นอิสระ เพื่อวัด precision/recall/IoU และ roof/private-green errors จริง
3. ขอบอาคาร/แปลงส่วนตัวที่ครบกว่า OSM และตรวจวันให้ตรงภาพ การกรอง residential อาจตัด public trees ภายใน polygon กว้าง
4. การตรวจสถานที่/หลักฐานปัจจุบันและทางเข้าของสวน ก่อนกล่าวอ้าง public access หรือเดินถึงใน 15 นาที

งานซอฟต์แวร์สำหรับประมวลผลสามภาพและบันทึกหลักฐานดำเนินการแล้ว ข้อจำกัดเหล่านี้ยังไม่ถือว่าผ่านด้วยจำนวน tests หรือการปรับสีแผนที่

## ทำซ้ำและตรวจย้อนหลัง

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe run_nike.py --all --output Output/new-run
```

อ่านผล `summary-all.json`, `checks.json`, `areas.csv`, `tests.log` และ summary/provenance ต่อภาพใน Output ชุดเดิม คำสั่ง run ใหม่ต้องเลือกโฟลเดอร์ใหม่เพื่อรักษาผลเก่า

ข้อมูล OSM มีที่มา attribution © OpenStreetMap contributors และ [ODbL](https://www.openstreetmap.org/copyright) เก็บ retrieved UTC, raw/query/context hashes และ coverage geometry ใน data/exclusions ทุกไฟล์

## ผลปรับปรุงล่าสุด: คัดบริบทบ้านออก (25 ตุลาคม 2569)

ตามผู้ใช้เลือกให้กันพื้นที่กำกวมใกล้บ้านออกก่อน เพิ่มระยะคัดอาคาร/บ้าน/residential เป็น 8/20/10 เมตร และ morphology รัศมี 3 เมตร ก่อนคัดกลุ่ม 300 ตร.ม. ซ้ำ ตัดสี halo จาก exclusion mask ด้วย ผลใหม่แยกที่ `Output/archive/runs/nike-public-final-20261025` ไม่เขียนทับการทดลองเดิมในรายงานนี้

| ภาพ | พื้นที่ candidate หลังคัดเข้ม ตร.ม. |
| --- | ---: |
| Theos00 | 372,643.00 |
| Theos01 | 2,379,871.75 |
| Theos02 | 451,337.00 |


## ผลตรวจครบสามภาพล่าสุด 25 ตุลาคม 2569

ผล authoritative เปลี่ยนเป็น Output/latest/analysis หลังเพิ่มกรอบบริบทบ้านอีก 86 เซลล์จากการดู source/overlay ครบ 432 ช่อง และแยกสนามบิน/แนวรางที่ระบุไว้เป็น pending ตามคำตอบผู้ใช้ ไม่รวมในยอดหลัก ส่วนสนามกีฬา/โรงเรียน/วัด/รีสอร์ต/พื้นที่ร่วมที่ยังไม่ชัดเก็บ candidate พร้อมสถานะ unverified ตามคำตอบอีกข้อ

| ภาพ | ผลหลักเข้าข่าย ตร.ม. | รอตรวจแยก ตร.ม. |
| --- | ---: | ---: |
| Theos00 | 160,152.75 | 180,615.50 |
| Theos01 | 2,161,651.25 | 0.00 |
| Theos02 | 305,740.00 | 0.00 |

ตรวจ source ทุก window รวม valid 108 ล้านพิกเซล ตรวจกลุ่มหลัก 921 กลุ่มครบ เก็บ audit/catalog/hashes และสำเนาโค้ดตาม hashes ครบ 14 modules ต่อภาพ Tests รันสำเร็จล่าสุด 46 ข้อผ่าน การตรวจนี้ไม่ใช่ human-ground-truth accuracy หรือการรับรองสิทธิ/การเข้าถึงสวน ดู [รายงานตรวจล่าสุด](FULL-AUDIT-th.md) และ [README](../../README.md) สำหรับวิธีใช้/ข้อจำกัด/สถานะรันซ้ำ

## Scope ปัจจุบัน: backend-only

ใช้ README และ docs/BACKEND-HANDOFF-th.md สำหรับการรับงานต่อ ไม่มีโมดูลส่งออกเว็บหรือหน้า HTML แล้ว ผล native analysis และภาพหลักฐานยังเก็บไว้ พิกัดทั้งสามภาพถูกวิเคราะห์แยกตามที่ผู้ใช้ยืนยัน ไม่เหมารวมว่าอยู่ดอนเมืองทั้งหมด

ผล lookup ทะเบียนดอนเมืองบน TIFF จริง: Theos00=2, Theos01=0, Theos02=0 ไม่มีจุดใดถูกยืนยันการเข้าใช้จากการ lookup อย่างเดียว Tests backend ล่าสุด 46 ข้อผ่าน พร้อม smoke test TIFF จริงและ audit ผ่านหลังถอดส่วนเว็บ
