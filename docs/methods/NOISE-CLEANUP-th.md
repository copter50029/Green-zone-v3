# ตัด noise เล็กและเส้นบาง — 25 ตุลาคม 2569

ปัญหาเดิม: กรองกลุ่ม 300 ตร.ม. อย่างเดียวทำให้จุดเล็กรอด หากมีเส้นเขียวบางเชื่อมกับกลุ่มใหญ่ จึงเพิ่ม disk morphological opening รัศมี 2 เมตร (4 พิกเซลบนกริด 0.5 เมตร) ก่อนตรวจพื้นที่กลุ่ม 4 ทิศซ้ำ แล้วสร้าง halo จาก mask ที่เหลือเท่านั้น

ไม่เติมหลุม ไม่เชื่อมช่องว่าง ไม่เพิ่มพิกเซลพืช และคง uncertain/NoData เดิม วิธีนี้เป็นการคัดตามรูปทรง ไม่ใช่โมเดลพิสูจน์ว่าจุดที่ลบไม่ใช่พืช แนวต้นไม้แคบและขอบพุ่มจริงอาจถูกตัดด้วย

```python
from greensight import make_heatmap, clean_saved_results

result = make_heatmap(mask, pixel_m=0.5, min_area_m2=300,
                      clean_radius_m=2, radius_m=50)
# หรือใช้ผลทั้งภาพเดิม ไม่อ่าน radiometry ใหม่
results = clean_saved_results('Output/archive/runs/nike-scenes-20261025',
                              'Output/my-clean-run', clean_radius_m=2)
```

`make_heatmap` และ `analyse_scene` ค่าเริ่มต้นของ library ยังคง clean_radius_m=0 เพื่อรองรับโค้ดเดิม ส่วน data/scenes.json ของงานนี้ตั้ง 2 เมตรแล้ว และ CLI ภาพเดียวใช้ --clean-radius-m 2 เป็นค่าเริ่มต้น

ผลใหม่: Output/archive/runs/nike-clean-20261025 เก็บแยกจากเดิม ตรวจ parent mask hashes และทะเบียนก่อนใช้ เก็บ cleanup_parent พร้อม hash และพื้นที่เดิม, clean_radius_m, cleanup_method และ hashes ของโค้ดใหม่ไว้ใน summary.json สถิติ originalCandidate ของรัน cleanup หมายถึง mask จาก parent ไม่ใช่ raw ratio ก่อน exclusions ใช้ inputCandidatePixels / morphologyRemovedPixels / totalRemovedFromInputM2 ตรวจจำนวนที่ตัดได้
