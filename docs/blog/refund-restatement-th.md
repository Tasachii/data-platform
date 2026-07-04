# ยอดขายเมื่อวานที่ "เปลี่ยนได้": จัดการ refund ย้อนหลัง 7 วันใน daily pipeline

> Draft สำหรับลง blog — แก้สำนวน/เพิ่มประสบการณ์ส่วนตัวก่อนเผยแพร่

ตอนเริ่มทำ data pipeline แรกในชีวิต ผมนึกว่าโจทย์ daily sales summary คือโจทย์ง่าย:
รับไฟล์ orders รายวัน → รวมยอด → ส่ง dashboard จบ

จนกระทั่งเจอคำถามเดียวที่ทำให้ต้องรื้อ design ใหม่หมด:

**"ถ้า order ของวันจันทร์ ถูก refund วันศุกร์ — ยอดขายวันจันทร์ควรเปลี่ยนไหม?"**

## ปัญหา: ข้อมูลไม่ได้มาเรียงตามเวลา และไม่ได้มาครั้งเดียว

ในโปรเจกต์ [data-platform](https://github.com/Tasachii) ผมจำลองร้าน e-commerce
ที่มี order วันละ ~20,000 รายการ พร้อมความสกปรกแบบที่ source จริงเป็น:

- 3% ของ order ถูก refund ย้อนหลัง 1–7 วัน (มาเป็นแถวใหม่ในไฟล์ของวันหลัง)
- 2% เป็น duplicate จากการ resend ของ source
- 1% เป็น late-arriving: order ของเมื่อวานโผล่ในไฟล์วันนี้

แถวหนึ่งใน CSV จึงไม่ใช่ "หนึ่ง order" แต่เป็น **"หนึ่งเวอร์ชันของ order ณ เวลาหนึ่ง"**
พอมองแบบนี้ design ที่ถูกต้องก็ตามมาเอง

## ทางเลือกสองทางของ refund

| มุมมอง | ความหมาย | ข้อดี | ข้อเสีย |
|---|---|---|---|
| Event view | บันทึก refund ในวันที่มัน "เกิด" (วันศุกร์) | ตัวเลขแต่ละวันไม่เปลี่ยนอีก | ยอดวันศุกร์เป็นลบปนกับยอดขายจริง, trend หลอกตา |
| **Restatement view** | ลดยอด net ของวันที่ order "เกิด" (วันจันทร์) | "ยอดขายสุทธิวันจันทร์" มีความหมายเดียวตลอดกาล | ตัวเลขย้อนหลังเปลี่ยนได้จนกว่า window จะปิด |

ผมเลือก restatement เพราะคำถามที่ business ถามจริงคือ "วันจันทร์ขายได้เท่าไหร่"
ไม่ใช่ "วันศุกร์มี refund กี่บาท" — แต่**ต้อง restate แบบตรวจสอบได้** ไม่ใช่เงียบๆ:
fact เก็บทั้ง `gross_amount`, `refund_amount`, `net_amount` แยกคอลัมน์
ใครสงสัยว่าตัวเลขทำไมขยับ ดูได้ว่า refund กินไปเท่าไหร่

## Implementation: SCD2 + full refresh จาก "สถานะปัจจุบัน"

หัวใจมีสองชิ้น ชิ้นแรกคือเก็บประวัติทุกเวอร์ชันเป็น SCD Type 2:

```sql
select
    order_id,
    status,
    updated_at                      as valid_from,
    lead(updated_at) over w         as valid_to,
    lead(updated_at) over w is null as is_current
from versions
window w as (partition by order_id order by updated_at)
```

order ปกติมีแถวเดียว (`delivered`, is_current=true) ส่วน order ที่โดน refund
มีสองแถว — ประวัติไม่หาย ตอบได้ทั้ง "ตอนนี้สถานะอะไร" และ "เคยเป็นอะไรเมื่อไหร่"

ชิ้นที่สอง: mart สร้างใหม่ทั้งก้อนจาก**สถานะปัจจุบัน**ทุกรอบ ทำให้ restatement
เกิดขึ้นเองโดยไม่ต้องเขียน logic พิเศษ — order ที่กลายเป็น refunded
จะย้ายจากคอลัมน์ net ไปคอลัมน์ refund ของ**วันเดิม**โดยอัตโนมัติ

แลกกับอะไร? ยอดย้อนหลังนิ่งก็ต่อเมื่อพ้น refund window (7 วัน) —
เขียนไว้ใน report ตรงๆ ว่าวันไหนถือว่า final

## บั๊กที่สอนผมมากที่สุด ไม่ได้อยู่ใน refund

ระหว่างพิสูจน์ idempotency (รัน pipeline ซ้ำแล้ว checksum ทุก table ต้องเท่าเดิม)
ผมเจอว่าตาราง rejected records มี 1–2 แถว "กะพริบ" ระหว่างรัน

สาเหตุ: duplicate จาก source **ไม่ได้ byte-identical เสมอ** — instant เดียวกัน
แต่ตัวหนึ่ง serialize เป็น `+07:00` อีกตัวเป็น `+00:00` พอ parse แล้ว
`updated_at` เท่ากันเป๊ะ ตัวจัดอันดับใน dedup เลยเสมอกัน → engine
เลือกผู้ชนะแบบสุ่ม → ค่า raw ที่เก็บใน quarantine สลับไปมาแต่ละรอบ

ทางแก้ไม่ใช่ไปทำข้อมูลให้สะอาดขึ้น แต่คือทำ tie-break ให้เป็น total ordering
เหนือ content — บทเรียนคือ **idempotency ต้องพิสูจน์ด้วย checksum ไม่ใช่สาบาน**
เพราะบั๊กแบบนี้ไม่มีทางเห็นด้วยตาเปล่า

## สรุปสิ่งที่อยากบอกตัวเองก่อนเริ่ม

1. แถวข้อมูล = เวอร์ชัน ไม่ใช่ entity — พอคิดแบบนี้ dedup/SCD2/restatement กลายเป็นเรื่องเดียวกัน
2. เลือกมุมมองบัญชี (event vs restatement) ให้ได้ก่อนเขียน SQL แล้วเขียน trade-off ลง ADR
3. ทุก edge case ที่ inject ต้องมี test ที่จับมัน — ผมให้ generator เขียน manifest
   ของความสกปรกทุกแถว แล้วให้ test suite พิสูจน์ recall 100%
4. รัน pipeline สองรอบแล้ว diff — สิ่งที่ "กะพริบ" คือครูที่ดีที่สุด

โค้ดทั้งหมด (pipeline, dbt models, Airflow DAGs, test 52 ตัว) อยู่ใน repo
`data-platform` พร้อม ADR อธิบายทุก decision ครับ
