"""Public map eligibility shared by the GeoJSON endpoint and the staff checklist.

A location approval is necessary but insufficient: the company must also have
independently verified identity, tech, and Tehran jurisdiction. The source-backed
location event must be the latest event and match the live location fields.
"""
from django.db.models import OuterRef, Subquery, F

from locations.models import CompanyLocation, CompanyLocationReviewEvent


def verified_company_locations():
    """Return exactly the public pins. Never include provisional or stale data."""
    latest = (CompanyLocationReviewEvent.objects
              .filter(company_id=OuterRef('company_id'))
              .order_by('-created_at', '-pk'))
    return (
        CompanyLocation.objects.select_related('company')
        .annotate(
            reviewed_decision=Subquery(latest.values('decision')[:1]),
            reviewed_latitude=Subquery(latest.values('latitude')[:1]),
            reviewed_longitude=Subquery(latest.values('longitude')[:1]),
            reviewed_evidence_url=Subquery(latest.values('evidence_url')[:1]),
        )
        .filter(
            verification_status='verified',
            verified_at__isnull=False,
            company__identity_status='verified',
            company__tech_status='verified',
            company__tehran_status='verified',
            latitude__isnull=False, longitude__isnull=False,
            reviewed_decision='verified',
            reviewed_latitude=F('latitude'),
            reviewed_longitude=F('longitude'),
            reviewed_evidence_url=F('evidence_url'),
        )
        .exclude(evidence_url='')
    )


def company_map_status(company, *, location=None, latest_event=None):
    """Staff-only explanation; consistent with the public endpoint.

    No data is written, and no verification is inferred from a company name,
    address or presence in a source directory.
    """
    if location is None:
        location = CompanyLocation.objects.filter(company=company).first()
    if latest_event is None:
        latest_event = (CompanyLocationReviewEvent.objects
                        .filter(company=company)
                        .order_by('-created_at', '-pk').first())
    checks = [
        {
            'code': 'identity',
            'label': 'هویت شرکت',
            'ok': company.identity_status == 'verified',
            'details': company.get_identity_status_display(),
        },
        {
            'code': 'tech',
            'label': 'فعالیت فناوری',
            'ok': company.tech_status == 'verified',
            'details': company.get_tech_status_display(),
        },
        {
            'code': 'tehran',
            'label': 'ارتباط شرکت با تهران (تأیید مستقل)',
            'ok': company.tehran_status == 'verified',
            'details': company.get_tehran_status_display(),
        },
        {
            'code': 'location',
            'label': 'وضعیت فعلی مکان دفتر',
            'ok': bool(location and location.verification_status == 'verified'
                       and location.verified_at is not None),
            'details': (
                location.get_verification_status_display()
                if location else 'هنوز مکان دفتر ثبت نشده است'),
        },
        {
            'code': 'coordinates',
            'label': 'مختصات و مدرک مکان',
            'ok': bool(location and location.latitude is not None
                       and location.longitude is not None
                       and location.evidence_url),
            'details': (
                'مختصات و لینک مدرک ثبت شده است'
                if location and location.latitude is not None
                and location.longitude is not None and location.evidence_url
                else 'مختصات معتبر و لینک مدرک مکان لازم است'),
        },
        {
            'code': 'latest_review',
            'label': 'آخرین تصمیم مستند دربارهٔ مکان',
            'ok': bool(
                location and latest_event
                and latest_event.decision == 'verified'
                and latest_event.latitude == location.latitude
                and latest_event.longitude == location.longitude
                and latest_event.evidence_url == location.evidence_url),
            'details': (
                'آخرین تأیید با مختصات و مدرک ذخیره‌شده مطابقت دارد'
                if location and latest_event and latest_event.decision == 'verified'
                and latest_event.latitude == location.latitude
                and latest_event.longitude == location.longitude
                and latest_event.evidence_url == location.evidence_url
                else 'تأیید معتبر و مطابق با آخرین نشانی/مختصات ثبت‌شده وجود ندارد'),
        },
    ]
    visible = verified_company_locations().filter(company_id=company.pk).exists()
    return {
        'checks': checks,
        'missing': [item for item in checks if not item['ok']],
        'visible': visible,
        'latest_event': latest_event,
        'location': location,
        'consistent': visible == all(item['ok'] for item in checks),
    }
