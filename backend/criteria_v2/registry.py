"""Jobiew's new, independent six-axis work/interview framework.

This is a STRUCTURAL contract, not a migration of historical ratings.  Both
frameworks must remain separate even when an author discusses both topics.
An absent score is unknown, not zero.  All axes are benefit-oriented (10=best).
"""
from dataclasses import dataclass

WORK = 'work'
INTERVIEW = 'interview'
VERSIONS = {WORK: 'work6_v2', INTERVIEW: 'interview6_v2'}


@dataclass(frozen=True)
class Axis:
    key: str
    label: str
    description: str


WORK_AXES = (
    Axis('work_compensation_fairness', 'حقوق، مزایا و عدالت پرداخت', 'میزان حقوق، تناسب با بازار، افزایش حقوق، پاداش، بیمه و قابل‌اعتماد بودن پرداخت‌ها'),
    Axis('work_life_flexibility', 'تعادل کار و زندگی و انعطاف‌پذیری', 'ساعت کاری، اضافه‌کاری، فشار و استرس، مرخصی، دورکاری و اختیار فرد در مدیریت زمان'),
    Axis('work_growth_career', 'رشد و آینده شغلی', 'امکان ارتقا، یادگیری مهارت‌های جدید، منتورینگ و آموزش، مسیر پیشرفت و افزایش ارزش فرد در بازار کار'),
    Axis('work_management_culture', 'مدیریت و فرهنگ', 'کیفیت مدیر مستقیم، احترام، عدالت رفتاری، فضای تیمی، اعتماد، شفافیت و نبود رفتارهای سمی'),
    Axis('work_stability_security', 'ثبات و امنیت شغلی', 'ریسک تعدیل نیرو، ثبات مالی، قابل‌پیش‌بینی بودن آینده، امنیت قرارداد و پایداری کسب‌وکار'),
    Axis('work_challenge_autonomy', 'چالش‌برانگیز بودن کار و اختیار عمل', 'جذابیت وظایف، استفاده از توانمندی‌ها، استقلال، اثرگذاری و معنادار بودن کار'),
)
INTERVIEW_AXES = (
    Axis('interview_professional_respect', 'احترام و رفتار حرفه‌ای', 'برخورد مصاحبه‌کننده، ادب، توجه، پرهیز از تحقیر و سؤال‌های نامناسب'),
    Axis('interview_information_clarity', 'شفافیت اطلاعات', 'صداقت درباره شرح شغل، حقوق، انتظارات، شرایط همکاری و چالش‌های موقعیت'),
    Axis('interview_quality_fairness', 'کیفیت و عدالت مصاحبه', 'مرتبط بودن سؤال‌ها، تخصص مصاحبه‌کننده، منصفانه بودن ارزیابی و فرصت نشان دادن توانایی‌ها'),
    Axis('interview_time_management', 'نظم و مدیریت زمان', 'وقت‌شناسی، تعداد مراحل، فاصله بین مصاحبه‌ها، طولانی نشدن غیرضروری فرایند'),
    Axis('interview_communication', 'ارتباطات و اطلاع‌رسانی', 'مشخص بودن مراحل، پاسخ‌گویی منابع انسانی، اطلاع از وضعیت درخواست و زمان تصمیم‌گیری'),
    Axis('interview_feedback_outcome', 'نتیجه‌دهی و بازخورد', 'اعلام نتیجه حتی در صورت رد شدن، زمان اعلام نتیجه و ارائه بازخورد مفید'),
)
AXES = {WORK: WORK_AXES, INTERVIEW: INTERVIEW_AXES}
LABELS = {WORK: 'شرایط کاری', INTERVIEW: 'شرایط مصاحبه'}


def axes_for(kind):
    if kind not in AXES:
        raise ValueError(f'Unsupported experience kind: {kind!r}')
    return AXES[kind]


def version_for(kind):
    return VERSIONS[kind] if kind in VERSIONS else axes_for(kind)


def kind_for_version(version):
    for kind, current in VERSIONS.items():
        if current == version:
            return kind
    raise ValueError(f'Unsupported v2 criteria version: {version!r}')


def validate_scoring_payload(payload, *, source_kind, source_sha256):
    """Validate a future *offline* six-axis proposal; NEVER accept old 5-axis data.

    Strictness is intentional: zero and guessed values are not abstentions.
    Evidence and confident judgments are not publication approvals.
    No side effects, external requests, or database writes.
    """
    axes_for(source_kind)
    kind = source_kind
    if not isinstance(payload, dict) or payload.get('criteria_version') != version_for(kind):
        raise ValueError('Wrong criteria version or malformed payload')
    if payload.get('source_kind') != kind or payload.get('source_content_sha256') != source_sha256:
        raise ValueError('Wrong experience kind or outdated source content')
    scores = payload.get('dimensions')
    expected = {x.key for x in axes_for(kind)}
    if not isinstance(scores, dict) or set(scores) != expected:
        raise ValueError('Exactly six keys of the correct experience type are required')
    for key, item in scores.items():
        if not isinstance(item, dict):
            raise ValueError(f'{key}: metric must be an object')
        score, evidence = item.get('score'), item.get('evidence')
        if score is not None and (type(score) is not int or not 1 <= score <= 10):
            raise ValueError(f'{key}: score must be null or integer 1..10')
        if score is None:
            if evidence not in (None, '', []):
                raise ValueError(f'{key}: abstention cannot carry evidence')
        elif not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(f'{key}: a score requires supporting text')
    return scores


def public_axes():
    """Labels and definitions only. Scores deliberately unavailable in phase one."""
    return {kind: [{'key': x.key, 'label': x.label, 'description': x.description, 'score': None}
                   for x in axes] for kind, axes in AXES.items()}
