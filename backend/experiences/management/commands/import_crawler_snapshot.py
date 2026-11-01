"""Import a CONSISTENT READ-ONLY snapshot of crawler SQLite into the Django DB.

Run repeatedly: source URLs are stable keys; human moderation state is untouched.
Never point Django DATABASES at the crawler's SQLite file.
"""
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Q
from companies.models import Company
from experiences.models import PublicExperience


def identity_from_url(url):
    return 'c' + hashlib.sha256(url.encode('utf-8')).hexdigest()[:20]


def load_json(value, default):
    try:
        obj=json.loads(value or '')
        return obj if isinstance(obj,type(default)) else default
    except (TypeError,ValueError):return default


def as_datetime(value):
    try:return datetime.fromisoformat(value) if value else None
    except (ValueError,TypeError):return None


class Command(BaseCommand):
    help='Import work and interview source data from a read-only SQLite snapshot (never calls Claude).'

    def add_arguments(self, parser):
        parser.add_argument('--snapshot',required=True)
        parser.add_argument('--dry-run',action='store_true')
        parser.add_argument('--limit',type=int,default=0)

    def handle(self, *args, **opts):
        source=Path(opts['snapshot']).resolve()
        if not source.is_file():raise CommandError(f'Snapshot missing: {source}')
        if opts['limit']<0:raise CommandError('--limit must be >=0')
        uri=source.as_uri()+'?mode=ro'
        totals={'source_rows':0,'new_companies':0,'new_experiences':0,'updated_experiences':0,
                'unchanged_experiences':0,'skipped':0,'work':0,'interview':0}
        try:
            with closing(sqlite3.connect(uri,uri=True,timeout=20)) as conn:
                conn.row_factory=sqlite3.Row
                conn.execute('PRAGMA query_only = ON')
                if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                    raise CommandError('Snapshot integrity_check failed')
                if opts['dry_run']:
                    counts=conn.execute('SELECT review_type,COUNT(*) AS n FROM reviews GROUP BY review_type').fetchall()
                    self.stdout.write(json.dumps({'snapshot':str(source),'read_only':True,'counts':{r['review_type']:r['n'] for r in counts},'dry_run':True},ensure_ascii=False))
                    return
                sql='SELECT * FROM reviews ORDER BY url'
                if opts['limit']:sql+=f" LIMIT {int(opts['limit'])}"
                with transaction.atomic():
                    for r in conn.execute(sql):
                        totals['source_rows']+=1
                        kind=r['review_type']
                        url=(r['url'] or '').strip()
                        c_url=(r['company_url'] or '').strip()
                        if kind not in ('work','interview') or not url.startswith(('https://','http://')) or not c_url.startswith(('https://','http://')):
                            totals['skipped']+=1;continue
                        totals[kind]+=1
                        cid=identity_from_url(c_url)
                        company,created=Company.objects.get_or_create(id=cid,defaults={
                            'source_url':c_url,'source_name':r['company'] or '',
                            'display_name':r['company'] or '(بدون نام)'})
                        if created:totals['new_companies']+=1
                        new_fields={'company':company,'source_site':r['source'],'source_kind':kind,
                            'title':r['title'] or '', 'job_title':r['job_title'] or '',
                            'body':r['body'] or '', 'pros':load_json(r['pros_json'],[]),
                            'cons':load_json(r['cons_json'],[]),
                            'published_jalali':r['published_jalali'] or '',
                            'employment_period_jalali':r['employment_period_jalali'] or '',
                            'source_rating_5':r['rating_5'],
                            'source_dimension_ratings':load_json(r['dimension_ratings_json'],{}),
                            'content_sha256':r['content_sha256'],
                            'crawled_at_utc':as_datetime(r['crawled_at_utc'])}
                        obj,created=PublicExperience.objects.get_or_create(source_url=url,defaults=new_fields)
                        if created:totals['new_experiences']+=1
                        elif obj.content_sha256 != r['content_sha256']:
                            for key,val in new_fields.items():setattr(obj,key,val)
                            obj.save(update_fields=list(new_fields))
                            totals['updated_experiences']+=1
                        else:totals['unchanged_experiences']+=1
                    # Counts come from imported source rows, never from guessed source-site counts.
                    for x in Company.objects.annotate(nwork=Count('experiences',filter=Q(experiences__source_kind='work')),
                                                     ninterview=Count('experiences',filter=Q(experiences__source_kind='interview'))).iterator():
                        if x.source_work_count!=x.nwork or x.source_interview_count!=x.ninterview:
                            Company.objects.filter(pk=x.pk).update(source_work_count=x.nwork,source_interview_count=x.ninterview)
        except sqlite3.DatabaseError as exc:
            raise CommandError(f'Cannot read source SQLite snapshot: {exc}') from exc
        self.stdout.write(json.dumps({'snapshot':str(source),'read_only':True,'status':'ok',**totals},ensure_ascii=False))
