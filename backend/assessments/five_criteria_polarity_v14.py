"""Five dimensions have positive scoring direction, including the historical pressure key.

This module audits score/evidence direction ONLY; it NEVER rewrites scores.
Automatic keyword checks are triage clues, not verified judgments.
"""
from __future__ import annotations
import re

FIRST_KEY = 'work_conditions_pressure'  # stable historical schema key
FIRST_LABEL = 'تعادل کار و زندگی و تناسب حجم کار'
HIGH_MEANS_BETTER = True
DIRECTION = {
    'work_conditions_pressure':'HIGH_IS_GOOD',
    'management_environment':'HIGH_IS_GOOD',
    'growth_development':'HIGH_IS_GOOD',
    'compensation_appreciation':'HIGH_IS_GOOD',
    'stability_security':'HIGH_IS_GOOD',
}

# Deliberately narrow phrases: false negatives preferred to false accusations.
NEGATIVE = [
    r'فشار\s+کاری\s+(?:خیلی\s+)?بالا',
    r'فشار\s+(?:کاری\s+)?زیاد',
    r'حجم\s+(?:کار|کاری)\s+(?:بسیار\s+)?زیاد',
    r'اضافه[\s\u200c-]*کاری\s+(?:زیاد|اجباری|مداوم)',
    r'عدم\s+تعادل\s+(?:بین\s+)?کار',
    r'عدم\s+توازن\s+کار',
    r'بیگاری',
    r'فرسودگی\s+شغلی',
]
POSITIVE = [
    r'حجم\s+(?:کار|کاری)\s+(?:معقول|مناسب|منطقی|متعادل)',
    r'فشار\s+کاری\s+(?:کم|پایین|قابل\s+تحمل)',
    r'فشار\s+کاری\s+وجود\s+ندار',
    r'تعادل\s+(?:کار\s+و\s+زندگی|زندگی\s+و\s+کار)\s+(?:مناسب|خوب|عالی)',
    r'زمان\s+کاری\s+شناور',
    r'ساعت\s+کاری\s+شناور',
    r'امکان\s+دورکاری',
    r'اضافه[\s\u200c-]*کاری\s+ندار',
]

def audit_direction(score, evidence):
    """Return one advisory audit label. No transformation of existing score."""
    if score is None:
        return 'ABSTAIN'
    if type(score) is not int or not 1 <= score <= 10:
        return 'INVALID_SCORE'
    txt = str(evidence or '').replace('ي','ی').replace('ك','ک').replace('‌',' ')
    neg = any(re.search(p,txt,re.I) for p in NEGATIVE)
    pos = any(re.search(p,txt,re.I) for p in POSITIVE)
    if neg and pos:
        return 'AMBIGUOUS_MIXED_SIGNALS_REVIEW'
    if neg and score >= 7:
        return 'POTENTIAL_REVERSED_POLARITY_REVIEW'
    if pos and score <= 4:
        return 'POTENTIAL_REVERSED_POLARITY_REVIEW'
    if neg or pos:
        return 'DIRECTION_CONSISTENT_EXPLICIT_SIGNAL'
    return 'NO_EXPLICIT_POLARITY_SIGNAL'
