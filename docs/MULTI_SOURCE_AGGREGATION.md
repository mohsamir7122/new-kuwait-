# Multi-Source Claim Aggregation v1

## الهدف

هذه الطبقة تجمع Observations من مصادر متعددة داخل الذاكرة، ثم تصالح كل Claim
على حدة قبل تمريرها إلى الرادار. لا تنزّل Dataset دائمة، ولا تكتب إلى القرص أو
Google Drive، ولا تعتبر وجود رقم في مصدر واحد حقيقة مكتملة.

`Investing` وبيانات السوق المرخصة مصادر Market Data. مواقع الشركات والإفصاحات
الرسمية مصادر للأحداث والبيانات المالية. الصحافة وGoogle Drive مصادر Context أو
Archive بحسب حالة الدليل. موقع بورصة الكويت لا يُقبل لمجرد أنه رسمي؛ يجب أن
ينجح الوصول القانوني والاكتمال الدلالي والتوقيت.

## حالات كل Claim

- `RESOLVED`: Single authority صالح لدوره، أو اتفاق مستقل بين عدد المصادر المطلوب.
- `SINGLE_SOURCE`: رقم صالح تقنيًا لكنه غير كافٍ للمصالحة.
- `CONFLICT`: المصادر المستقلة أو النسخ داخل عائلة واحدة متعارضة.
- `MISSING`: لا توجد Observation مؤهلة.
- `INFERRED_ONLY`: توجد Inference معلَّمة، لكن لا توجد حقيقة قابلة للاستخدام.

الـInference لا تدخل في تصويت المصادر، ولا تستبدل Fact، ولا تجعل Claim صالحة
للتنفيذ.

## استقلال المصادر

`source_family` يحدد الناشر أو المزود، بينما `origin_family` يحدد الأصل الذي
نُقلت عنه المعلومة. نسختان صحفيتان تنقلان الإفصاح نفسه تُحسبان كأصل مستقل واحد،
لا كمصدرين مؤكدين.

## بوابات الأهلية

تُستبعد Observation عند أي من الحالات التالية:

- الوصول غير قانوني أو غير مصرح.
- المحتوى الدلالي ناقص، مثل HTML shell بلا الجدول المطلوب.
- وقت الجلسة أو الإتاحة ناقص.
- القيمة مقفلة أو Masked في خدمة Premium.
- الجلسة مختلفة عن Target Session.
- الوحدة مختلفة.
- Google Drive Archive استُخدم لسعر حي بينما السياسة تمنعه.
- Observation لم تكن متاحة عند `decision_at`.
- في وضع `PROSPECTIVE`، جرى التقاطها بعد وقت القرار.

## سياسة المصادر حسب نوع Claim

### Market Tape

الأولوية:

1. `LICENSED_MARKET_DATA`
2. `SECONDARY_MARKET_DATA`
3. `REGULATOR_OR_EXCHANGE` فقط بعد اكتمال الوصول الدلالي والقانوني

لا تُستخدم الصحافة أو Drive لتحديد Current Close أو Previous Close.

### Financial Results and Company Events

يمكن لمصدر `ISSUER_PRIMARY` أن يحسم Claim منفردة إذا كان المستند كاملًا
ومؤرخًا. النسخ الصحفية تحفظ كCross-check وسياق، ولا تُضاعف وزن الإفصاح الأصلي.

### Identity

يمكن استخدام Knowledge Graph أو ISIN أو Listing identifier لتثبيت الهوية، لكن
نجاح التعرف إلى الشركة لا يعني وجود Fundamentals أو Quote صالحة.

## التعامل مع فجوات الذكاء الاصطناعي

يسمح `ProposedInference` بتسجيل أفضل تفسير مهني عندما تكون Fact ناقصة، بشرط:

- تحديد `method`.
- تحديد Assumptions.
- تحديد Claims الداعمة.
- تحديد Confidence نوعية: `LOW`, `MEDIUM`, `HIGH`.
- إبقاء `may_overwrite_fact=false`.
- إبقاء `execution_eligible=false`.

مثال: يمكن استنتاج أن دعمًا حكوميًا كبيرًا قد يحسن نتيجة ربع معين حسابيًا، لكن
لا يجوز عرضه كصافي ربح متوقع ما لم تتوفر بنود المصروفات والتوقيت المحاسبي
الكاملة.

## عدم التخزين

الدالة `aggregate_security_claims` Pure in-memory ولا تقبل Path أو Drive ID أو
Output directory. المخرج يعلن:

- `storage_mode=IN_MEMORY_ONLY`
- `local_persistence=false`
- `drive_persistence=false`
- `silent_gap_filling=false`
- `execution=false`

الحفظ اللاحق، إن أضيف، يجب أن يكون طبقة مستقلة خاضعة لتفويض وسياسة Retention،
ولا يغير حقيقة أن هذه الطبقة لا تجمع Credentials أو Sessions أو Copies دائمة.

## اختبارات الحالات الثلاث

تغطي Regression Tests الجديدة أمثلة حقيقية من البحث:

- اتفاق Investing ومزود مستقل على إغلاق الامتياز 75.3 فلسًا.
- تعارض Previous Close لشمال الزور بين 140 و141 و146 فلسًا.
- اعتماد خسارة مواشي نصف السنوية من مستند الشركة كSingle authority.
- عدم عدّ نسختين صحفيتين لإفصاح دعم مواشي كمصدرين مستقلين.
- رفض قيمة InvestingPro المقفلة بدل تفسيرها صفرًا.
- منع استخدام Google Drive cached profile كسعر حي.

هذه Fixtures تختبر سلوك المصالحة، ولا تدعي أن الأرقام تبقى Current بعد التاريخ
المثبت لكل Observation.
