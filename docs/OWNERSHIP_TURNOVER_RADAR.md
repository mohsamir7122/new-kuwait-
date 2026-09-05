# Ownership and Turnover Radar v1

## الغرض

هذه الوحدة هي أول `Vertical Slice` لاكتشاف الأسهم الحدثية في بورصة الكويت
قبل الانتقال إلى أي `Forecast` أو توصية. وهي تعالج الفجوة التي سمحت لسهم ذي
تغيرات ملكية ودوران مرتفع بأن يبقى خارج قائمة الفحص لمجرد أنه لم يكن ضمن
`Watchlist` أولية أو قائمة كبار الرابحين.

الرادار لا يتوقع السعر ولا يوصي بالشراء أو البيع. وظيفته هي:

- ربط سلسلة تغيرات الملكية والمطلعين والصفقات المتفق عليها زمنيًا.
- قياس حجم الصفقة نسبة إلى الأسهم المصدرة و`Free Float` الصحيح زمنيًا.
- قياس `Relative Volume` والدوران التراكمي.
- قراءة جودة الحركة من `Gap` وموضع آخر سعر داخل النطاق والتراجع من القمة
  وعلاقة السعر بـ`VWAP` والقوة النسبية أمام السوق والقطاع.
- ترتيب جميع الأوراق المدخلة إلى الفحص، لا قائمة أسماء مختارة يدويًا.
- رفض البيانات الحسابية المستحيلة والتعارضات بدل تسويتها صامتًا.

## الحدود العلمية

المخرج هو:

`EVENT_AND_MARKET_ANOMALY_RADAR_ONLY`

ولا يسمح في هذه المرحلة بـ:

- `Live Collection`.
- احتمال رقمي للصعود أو الهبوط.
- `Buy/Sell Recommendation`.
- سعر دخول أو هدف.
- محاكاة أمر تداول.
- استخدام نتيجة الرادار كبديل للإفصاح الرسمي.

القيم البحثية المسموح بها هي:

- `EVENT_CONFIRMED`
- `DISCOVERY_ALERT`
- `HIGH_PRIORITY_WATCH`
- `ANOMALY_WATCH`
- `HUMAN_REVIEW_REQUIRED`
- `ABSTAIN`

وتبقى `trade_eligibility=BLOCKED` في جميع الحالات.

## المدخلات

### Capital Structure

يلزم:

- `security_code`
- `issued_shares`
- `free_float_shares` عندما تتوافر
- `as_of`
- `first_available_at`
- `captured_at`
- بصمات Evidence قابلة للحل داخل الـManifest

لا يجوز استخدام Snapshot بتاريخ اقتصادي سابق إذا لم تكن متاحة عند `decision_at`،
ولا يجوز أن يسبق `captured_at` وقت الإتاحة. كما لا يجوز أن يتجاوز `free_float_shares` عدد الأسهم المصدرة، ولا يجوز استخدام
لقطة Capital Structure أصبحت متاحة بعد `decision_at`.

### Ownership Events

الأنواع الحالية:

- `BENEFICIAL_OWNERSHIP_CHANGE`
- `INSIDER_TRADE`
- `AFFILIATE_TRADE`
- `AGREED_TRADE`
- `BLOCK_TRADE`
- `CONTROL_CHANGE`
- `BOARD_CHANGE`

كل Event تحمل:

- `event_id`
- `canonical_event_id`
- التوقيت الاقتصادي وتوقيت النشر وأول وقت إتاحة ووقت الالتقاط
- `source_role`
- حامل الملكية أو المشتري أو البائع عند انطباق ذلك
- النسبة السابقة والحالية أو عدد الأسهم
- بصمة Evidence

تُستبعد تلقائيًا من القرار التاريخي أي Event كان `first_available_at` لها بعد
`decision_at`. النسخ التي تحمل `canonical_event_id` واحدًا تُزال تكراراتها،
لكن اختلاف Payload الجوهري يحول الحالة إلى `HUMAN_REVIEW_REQUIRED`.

### Historical Bars

يلزم حد أدنى خمس جلسات مرتبة ومؤرخة. تستخدم آخر عشرين جلسة إيجابية الحجم
لبناء وسيط الحجم، وتستخدم آخر ستين عائدًا لرصد الحركات المفاجئة والتقلب
الوصفي.

### Current Session Snapshot

اللقطة الاختيارية تخص `CONTINUOUS_TRADING` أو `CLOSING_AUCTION` أو `CLOSED`.
بيانات ما قبل الافتتاح ومزاد الافتتاح تحتاج عقدًا منفصلًا ولا تُحشر داخل OHLC.
وهي تدعم:

- `market_phase`
- `previous_close_fils`
- `open_fils`
- `high_fils`
- `low_fils`
- `last_fils`
- `volume`
- `turnover_kwd`
- `trade_count`
- إجمالي حجم وقيمة السوق عند التوقيت نفسه
- عائد السوق والقطاع بوحدة `DECIMAL_FRACTION`
- `available_at` و`captured_at`

يرفض الرادار اللقطة إذا:

- كان `Low/High/Open/Last` غير متسق.
- كان Volume موجبًا وTurnover صفرًا أو العكس.
- تجاوز حجم السهم إجمالي حجم السوق.
- تجاوزت قيمة السهم إجمالي قيمة السوق.
- وقع `VWAP` المشتق خارج نطاق الجلسة بما يتجاوز هامش التحقق.
- كانت اللقطة غير متاحة عند `decision_at`.

## المكونات الأربعة

### Movement Risk

يصف قابلية الورقة لحركة غير عادية اعتمادًا على:

- `Relative Volume`.
- دوران `Free Float`.
- دوران خمسة أيام نسبة إلى الأسهم المصدرة.
- عدد الجلسات ذات تغير مطلق لا يقل عن عشرة في المئة.

القيمة `VERY_HIGH` أو `HIGH` لا تحدد اتجاهًا.

### Ownership Event

يفصل بين:

- `CONFIRMED_CONTROL_RELEVANT_EVENT`
- `CONFIRMED_MATERIAL_OWNERSHIP_EVENT`
- `OFFICIAL_EVENT_OBSERVED`
- `NONE_OBSERVED`

الصفقة التي تبلغ عشرين في المئة من الأسهم المصدرة تُوسم
`CONTROL_RELEVANT_BLOCK_GE_20PCT_ISSUED`. والصفقة التي تبلغ أربعين في المئة
من `Free Float` تُوسم `BLOCK_GE_40PCT_FREE_FLOAT`.

هذه Thresholds بحثية شفافة، وليست احتمالات Backtested.

### Directional Confirmation

لا تُبنى من الخبر وحده. تحتاج لقطة سوق وتستخدم:

- Return من الإغلاق السابق.
- `Relative Volume`.
- موضع آخر سعر داخل نطاق الجلسة.
- القوة النسبية أمام السوق.
- علاقة السعر بـ`VWAP`.

القيم هي:

- `POSITIVE_CONFIRMED`
- `NEGATIVE_CONFIRMED`
- `TENTATIVE_POSITIVE`
- `TENTATIVE_NEGATIVE`
- `UNCONFIRMED`
- `NOT_OBSERVED`

### Continuation Structure

بعد تأكيد الاتجاه فقط، يقرأ الرادار:

- `High-to-Last Giveback`.
- موضع الإغلاق أو آخر سعر.
- علاقة السعر بـ`VWAP`.
- شدة Volume.

وقد ينتج:

- `HEALTHY_CONTINUATION_STRUCTURE`
- `MIXED_CONTINUATION_STRUCTURE`
- `ELEVATED_REVERSAL_RISK`
- `NEGATIVE_CONTINUATION_STRUCTURE`
- `NOT_APPLICABLE`

## وحدات القياس والإصدار

كل المخرجات تحمل `method_id=ownership_turnover_radar_v1` ونسخة Machine-readable
من Thresholds. نسب Turnover وBlock Size والعوائد تُكتب بوحدة
`DECIMAL_FRACTION`، بينما تغير الملكية يُكتب بوحدة `PERCENTAGE_POINTS`. لا تُسمى
Ratio بأنها Percent من دون تحويلها، منعًا لالتباس 0.25 مع 25.

اللقطة أثناء التداول تحمل `snapshot_finality=PROVISIONAL_INTRADAY`، أما لقطة
`CLOSED` فتحمل `FINAL_SESSION`.

## لا يوجد Composite Score

لا تنتج الوحدة درجة واحدة تسمح لعامل قوي بإخفاء بوابة فاشلة. تعرض كل Component
ومقاييسها وReason Codes منفصلة. ويفضل تشغيل Hard Gates قبل استخدام ترتيب
التحقيق.

## فحص السوق الكامل

`scan_ownership_turnover_universe` يستقبل كل الحالات المتاحة ويعيد ترتيبها
ترتيب تحقيق Deterministic، مع رفض تكرار `security_code`. الترتيب هو أولوية
بحثية، وليس Ranking استثماريًا أو Recommendation.

## اختبارات Regression

تغطي الاختبارات الحالية اثنتي عشرة حالة:

1. سلسلة تخفيض ملكية ودوران مرتفع قبل ظهور اتجاه.
2. منع Backfill لصفقة لم تكن منشورة عند نقطة القرار التاريخية.
3. تحول الحالة بعد Block Trade وحركة Price/Volume مستقلة عن السوق.
4. اكتشاف `Volume Climax` والتراجع من القمة.
5. رفض حجم سهم يتجاوز إجمالي حجم السوق.
6. عدم تسوية نسخ Event متعارضة صامتًا.
7. عدم تصنيف شراء Insider على أنه Supply.
8. رفض Capital Structure لم تكن متاحة عند وقت القرار.
9. كشف فجوات Ownership Timeline من دون إسقاط التنبيه الصحيح.
10. وسم لقطة الجلسة أثناء التداول بأنها Provisional.
11. ترتيب Full-universe من دون Watchlist Anchoring.
12. منع تجميع Block Trades من أيام مختلفة وكأنها صفقة سيطرة واحدة.

## المرحلة التالية

لا تزال هناك طبقتان منفصلتان قبل التشغيل الفعلي:

1. `Local Evidence Bundle Runner` وJSON Schema ثابتة للرادار.
2. Collector رسمي أو مرخص ينتج هذه المدخلات مع Point-in-Time receipts.

إضافة Collector لا تغير حدود الرادار: لا Recommendation ولا Entry Price قبل
وجود Feed تنفيذي موثوق وتقييم Prospective مستقل.
