#!/usr/bin/env python3
"""Jobiew independent source/checkpoint structural audit and private QA preview.

Python standard library only. READ-ONLY source/checkpoint; no external network,
AI call, PostgreSQL access or rights/publication changes. It cannot establish
accuracy of a score or the truth of an author's allegations.

Usage:
 python validate_jobiew_checkpoint.py --source jobiew_dual6_all_stories.zip \
   --checkpoint jobiew_gpt6_private_checkpoint_001_640.zip --out-dir qa_out
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re
import zipfile

AXES = {
    "work": ("work_compensation_fairness", "work_life_flexibility", "work_growth_career", "work_management_culture", "work_stability_security", "work_challenge_autonomy"),
    "interview": ("interview_professional_respect", "interview_information_clarity", "interview_quality_fairness", "interview_time_management", "interview_communication", "interview_feedback_outcome"),
}
LABELS = {
    "work": "تجربهٔ کاری", "interview": "تجربهٔ مصاحبه",
    "work_compensation_fairness": "حقوق و عدالت پرداخت", "work_life_flexibility": "تعادل کار و زندگی", "work_growth_career": "رشد شغلی", "work_management_culture": "مدیریت و فرهنگ", "work_stability_security": "ثبات شغلی", "work_challenge_autonomy": "چالش و اختیار",
    "interview_professional_respect": "احترام حرفه‌ای", "interview_information_clarity": "شفافیت اطلاعات", "interview_quality_fairness": "کیفیت و عدالت مصاحبه", "interview_time_management": "مدیریت زمان", "interview_communication": "ارتباطات", "interview_feedback_outcome": "نتیجه و بازخورد",
}
STATES = {
    "assistant_reviewed_draft", "assistant_reviewed_all_null", "deferred_source_review",
    "excluded_source_quality", "awaiting_assistant_review",
}
class CheckpointError(ValueError):
    pass


MAX_CHECKPOINT_ZIP_BYTES = 120 * 1024 * 1024
MAX_ZIP_UNCOMPRESSED_BYTES = MAX_CHECKPOINT_ZIP_BYTES * 2


def _guard_zip(path, z):
    if (path.stat().st_size > MAX_CHECKPOINT_ZIP_BYTES or
        len(z.infolist()) > 500 or
        sum(info.file_size for info in z.infolist()) > MAX_ZIP_UNCOMPRESSED_BYTES or
        any(info.file_size > MAX_CHECKPOINT_ZIP_BYTES for info in z.infolist())):
        raise CheckpointError('ZIP archive exceeds safe size/member limits')


def require(test, message):
    if not test:
        raise CheckpointError(message)


def digest(binary: bytes) -> str:
    return sha256(binary).hexdigest()


def _unique_object_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON object key')
        result[key] = value
    return result


def strict_json(binary):
    """Reject NaN, infinities, and ambiguous duplicate JSON keys."""
    def bad_constant(value):
        raise CheckpointError('Non-finite JSON value')
    return json.loads(binary, object_pairs_hook=_unique_object_pairs,
                      parse_constant=bad_constant)


def parse_jsonl(binary: bytes, label: str):
    try:
        rows = [strict_json(line) for line in binary.decode('utf-8-sig').splitlines() if line.strip()]
        require(all(isinstance(row, dict) for row in rows), f'{label}: non-object row')
        return rows
    except (ValueError, UnicodeDecodeError, TypeError) as exc:
        raise CheckpointError(f'{label}: invalid UTF-8 JSONL') from exc


def load_source(path: Path):
    require(path.is_file(), "source archive not found")
    src_sha = digest(path.read_bytes())
    with zipfile.ZipFile(path) as z:
        _guard_zip(path, z)
        require(z.testzip() is None, "source archive CRC corrupted")
        manifest = strict_json(z.read('manifest.json'))
        require(manifest.get('format') == 'jobiew_chatgpt_dual6_source_export_v1', 'unexpected source format')
        files = [entry['file'] for entry in manifest['batches']]
        require(len(files) == len(set(files)), 'duplicate source batch in manifest')
        require(len(z.namelist()) == len(files) + 1 and
                set(z.namelist()) == set(files) | {'manifest.json'},
                'source ZIP contents differ from manifest')
        sources = {}
        for batch in manifest["batches"]:
            filename = batch["file"]
            require(bool(re.fullmatch(r"batches/batch_\d{4}\.jsonl", filename)), f"unsafe batch name {filename}")
            raw = z.read(filename)
            require(digest(raw) == batch["sha256"], f"source batch checksum mismatch: {filename}")
            rows = parse_jsonl(raw, filename)
            require(len(rows) == batch['count'] and len(rows) > 0,
                    f'source batch count mismatch: {filename}')
            require(rows[0]['experience_id'] == batch['first_id'] and
                    rows[-1]['experience_id'] == batch['last_id'],
                    f'source batch bounds mismatch: {filename}')
            for row in rows:
                i, story = row["experience_id"], row["story"]
                require(type(i) is int and i > 0 and i not in sources, f"invalid or duplicate source ID: {i}")
                require(row["source_kind"] in AXES, f"unsupported source kind: {i}")
                require(isinstance(story, str) and row["story_length"] == len(story), f"source length mismatch: {i}")
                require(digest(story.encode('utf-8')) == row["story_sha256"], f"source story checksum mismatch: {i}")
                require(bool(re.fullmatch(r"[a-f0-9]{64}", row["source_content_sha256"])), f"invalid content digest: {i}")
                sources[i] = row
        require(len(sources) == manifest["counts"]["all_experiences"], "source count mismatch")
        require(sorted(sources) == list(range(1, len(sources) + 1)), "source IDs are not contiguous")
    return manifest, sources, src_sha


def audit(source_path: Path, checkpoint_path: Path):
    manifest, sources, src_sha = load_source(source_path)
    with zipfile.ZipFile(checkpoint_path) as z:
        _guard_zip(checkpoint_path, z)
        require(z.testzip() is None, "checkpoint ZIP CRC corrupted")
        names = z.namelist()
        expected_names = {'files_sha256.json', 'checkpoint.json',
                          'ledger.jsonl', 'assistant_predictions.jsonl',
                          'quality_audit.json'}
        require(len(names) == len(expected_names) and set(names) == expected_names,
                'checkpoint ZIP has missing, duplicate, or unexpected members')
        checks = strict_json(z.read('files_sha256.json'))
        require(isinstance(checks, dict) and set(checks) == expected_names - {'files_sha256.json'},
                'checkpoint hash manifest must cover every payload member')
        for filename, expected in checks.items():
            require(type(expected) is str and re.fullmatch(r'[a-f0-9]{64}', expected)
                    and digest(z.read(filename)) == expected,
                    f'checkpoint file SHA mismatch: {filename}')
        cp = strict_json(z.read('checkpoint.json'))
        require(cp.get("source_archive_sha256") == src_sha, "checkpoint references DIFFERENT source ZIP")
        ledger = parse_jsonl(z.read("ledger.jsonl"), "ledger")
        predictions = parse_jsonl(z.read("assistant_predictions.jsonl"), "predictions")
    require(len(ledger) == len(sources), "ledger does not cover all source records")
    lmap = {row["experience_id"]: row for row in ledger}
    require(len(lmap) == len(ledger) and set(lmap) == set(sources), "ledger missing/duplicate IDs")
    for i, row in lmap.items():
        source = sources[i]
        require(row["status"] in STATES, f"unknown ledger status: {i}")
        require(row['kind'] == source['source_kind'] and row['company_id'] == source['company_id'] and
                row['story_sha256'] == source['story_sha256'] and
                row['source_content_sha256'] == source['source_content_sha256'], f'ledger/source mismatch: {i}')
        duplicate_of = row.get('exact_duplicate_of_experience_id')
        if duplicate_of is not None:
            require(type(duplicate_of) is int and 0 < duplicate_of < i and
                    sources[duplicate_of]['story_sha256'] == source['story_sha256'],
                    f'unproven exact duplicate marker: {i}')
    pmap = {}
    axis_counts = {a: Counter() for axes in AXES.values() for a in axes}
    counts = Counter()
    kind_counts = Counter()
    companies = defaultdict(lambda: {"work": [], "interview": []})
    for p in predictions:
        i = p["experience_id"]
        require(type(i) is int and i in sources and i not in pmap, f"prediction duplicate/unknown ID: {i}")
        pmap[i] = p
        src, led = sources[i], lmap[i]
        kind = src["source_kind"]
        require(p["kind"] == kind and p["company_id"] == src["company_id"] and
                p["story_sha256"] == src["story_sha256"] and
                p["source_content_sha256"] == src["source_content_sha256"], f"prediction/source mismatch: {i}")
        require(p["state"] == led["status"] and p["state"] in {"assistant_reviewed_draft", "assistant_reviewed_all_null"}, f"prediction/ledger state mismatch: {i}")
        require(p.get("review_status") == "unverified_private_proposal", f"incorrect review status: {i}")
        pred = p["prediction"]
        require(pred["detected_kind"] == kind and type(pred["kind_confidence"]) is int and 0 <= pred["kind_confidence"] <= 100, f"detected kind mismatch: {i}")
        dims = pred["dimensions"]
        require(isinstance(dims, dict) and set(dims) == set(AXES[kind]), f"wrong 6-axis keys: {i}")
        nscore = 0
        for axis, value in dims.items():
            require(isinstance(value, dict) and set(value) == {"score", "confidence", "evidence", "explanation"}, f"invalid axis shape: {i}/{axis}")
            score, conf, ev, reason = (value[k] for k in ("score", "confidence", "evidence", "explanation"))
            require(type(conf) is int and isinstance(ev, str) and isinstance(reason, str) and 8 <= len(reason.strip()) <= 600, f"invalid annotation types: {i}/{axis}")
            if score is None:
                require(conf == 0 and ev == "", f"null axis has evidence/confidence: {i}/{axis}")
                counts["null"] += 1; axis_counts[axis]["null"] += 1
            else:
                require(type(score) is int and 1 <= score <= 10 and 70 <= conf <= 100, f"invalid score/confidence: {i}/{axis}")
                require(12 <= len(ev) <= 450 and ev in src["story"], f"quote absent from story: {i}/{axis}")
                require(not any(marker in ev for marker in ("[email]", "[phone]", "[number]")), f"redacted placeholder in quote: {i}/{axis}")
                counts["numeric"] += 1; axis_counts[axis]["numeric"] += 1
                nscore += 1
        require((nscore == 0) == (p["state"] == "assistant_reviewed_all_null"), f"all-null status incorrect: {i}")
        counts["reviewed"] += 1
        kind_counts[kind] += 1
        companies[src["company_id"]][kind].append(p)
    require(set(pmap) == {i for i,r in lmap.items() if r["status"] in ("assistant_reviewed_draft", "assistant_reviewed_all_null")}, "ledger prediction membership mismatch")
    require(counts["reviewed"] == cp["assistant_reviewed_records"], "checkpoint reviewed count mismatch")
    require(counts["numeric"] == cp["assistant_numeric_axis_proposals"] and counts["null"] == cp["assistant_null_axis_proposals"], "checkpoint axis totals mismatch")
    status_counts = Counter(row["status"] for row in ledger)
    require(dict(status_counts) == cp["status_counts"], "checkpoint status counts mismatch")
    require(sum(status_counts.values()) == len(sources), "invalid status sum")
    require(cp.get('publication') == 'DISABLED' and cp.get('source_rights') == 'NOT_ESTABLISHED'
            and cp.get('independent_semantic_accuracy_established') is False,
            'publication, quality, or rights changed')
    result = {
        "validation": "PASS", "source_records": len(sources), "source_zip_sha256": src_sha,
        "checkpoint_zip_sha256": digest(checkpoint_path.read_bytes()),
        "resume_next_experience_id": cp["resume_next_experience_id"],
        "status_counts": dict(status_counts), "reviewed": counts["reviewed"],
        "numeric_proposals": counts["numeric"], "abstentions": counts["null"],
        "by_kind_reviewed": dict(kind_counts), "by_axis": {k: dict(v) for k,v in axis_counts.items()},
        "companies_with_private_drafts": len(companies),
        "source_rights": "NOT_ESTABLISHED", "company_attribution": "UNVERIFIED",
        "independent_semantic_accuracy": "NOT_ESTABLISHED",
        "confidence_calibration": "NOT_ESTABLISHED",
        "human_approval": "NONE", "publication": "DISABLED",
        "external_api_calls": 0, "database_writes": 0,
    }
    return result, companies


def html_report(result, companies):
    status_order = ["assistant_reviewed_draft", "assistant_reviewed_all_null", "deferred_source_review", "excluded_source_quality", "awaiting_assistant_review"]
    fa = {
        "assistant_reviewed_draft": "پیشنهاد دارای نمره", "assistant_reviewed_all_null": "شش معیار بدون نمره", "deferred_source_review": "ارجاع به بررسی", "excluded_source_quality": "خارج از پردازش", "awaiting_assistant_review": "در انتظار ارزیابی"
    }
    cards = "".join(f'<div class="metric"><div class="mini">{escape(fa[s])}</div><strong>{result["status_counts"].get(s,0):,}</strong></div>' for s in status_order)
    axis_lines = "".join(f'<tr><td>{escape(LABELS[a])}</td><td>{result["by_axis"][a].get("numeric",0)}</td><td>{result["by_axis"][a].get("null",0)}</td></tr>' for k in ("work", "interview") for a in AXES[k])
    company_rows=[]
    for cid, group in companies.items():
        w, it = group["work"], group["interview"]
        nscore=sum(d["score"] is not None for p in w+it for d in p["prediction"]["dimensions"].values())
        company_rows.append((len(w)+len(it), str(cid), len(w), len(it), nscore))
    company_rows.sort(key=lambda x:(-x[0], x[1]))
    tbody="".join(f'<tr data-id="{escape(cid)}"><td><code>{escape(cid)}</code></td><td>{w}</td><td>{it}</td><td>{n}</td><td>{sc}</td></tr>' for n,cid,w,it,sc in company_rows)
    return f'''<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>کنترل خصوصی Jobiew ۶+۶</title><meta name="robots" content="noindex,nofollow"><style>
    :root{{color-scheme:light;font-family:Tahoma,system-ui,sans-serif}}body{{margin:0;background:#f7f9fc;color:#1d2939;line-height:1.8}}
    main{{max-width:1120px;margin:auto;padding:30px 18px 65px}}h1{{font-size:26px;margin:0 0 7px}}h2{{font-size:18px;margin-top:26px}}
    .sub{{color:#53637b}}.notice{{background:#fff2df;border:1px solid #e9bc77;padding:14px 18px;border-radius:14px;margin:18px 0}}
    .metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}}.metric{{background:white;border:1px solid #e1e8ef;padding:15px;border-radius:13px}}.metric strong{{display:block;font-size:25px;font-variant-numeric:tabular-nums}}
    .mini{{font-size:12px;color:#5a687d}}.panel{{background:#fff;border:1px solid #dfe6ef;border-radius:14px;padding:12px 16px;overflow-x:auto}}table{{width:100%;border-collapse:collapse;text-align:right}}
    th,td{{padding:7px 10px;border-bottom:1px solid #edf1f5}}th{{background:#f5f8fb;color:#43536b}}code{{direction:ltr;unicode-bidi:isolate;font-size:12px}}
    input{{font:inherit;padding:10px;border:1px solid #aebccb;border-radius:8px;width:min(100%,330px);box-sizing:border-box}}
    .footer{{font-size:12px;color:#64748b;margin-top:20px}}</style></head><body><main>
    <h1>بازبینی خصوصی خروجی Jobiew ۶+۶</h1><p class="sub">گزارش فقط‌خواندنی و بدون متن روایت‌ها، نام اشخاص یا شرکت‌ها — برای ارزیابی فنی و برنامه‌ریزی ادغام</p>
    <div class="notice"><b>اطلاع مهم:</b> همهٔ نمره‌ها پیش‌نویس تأییدنشده‌اند. صحت ادعاها، اعتبار حقوق استفاده، انتساب شرکت‌ها و دقت مستقل AI تأیید نشده است. این فایل برای سایت عمومی مناسب نیست.</div>
    <div class="metrics">{cards}</div>
    <h2>وضعیت checkpoint</h2><div class="panel"><p>منبع: {result["source_records"]:,} تجربه | دارای خروجی: {result["reviewed"]:,} | نمرهٔ عددی: {result["numeric_proposals"]:,} | null: {result["abstentions"]:,} | ادامه: شناسهٔ {result["resume_next_experience_id"]:,}</p><p>تعداد شناسهٔ شرکت با پیش‌نویس: {result["companies_with_private_drafts"]:,}</p></div>
    <h2>پوشش معیارها</h2><div class="panel"><table><thead><tr><th>معیار</th><th>نمرهٔ عددی</th><th>فاقد نمره</th></tr></thead><tbody>{axis_lines}</tbody></table></div>
    <h2>گروه‌بندی پیش‌نویس‌ها بر شناسهٔ شرکت</h2><div class="panel"><p class="sub">این شمارنده‌ها نمرهٔ تأییدشدهٔ شرکت نیستند؛ فقط پوشش پرونده‌های خصوصی را نشان می‌دهند.</p><input id="filter" placeholder="جستجوی شناسهٔ شرکت" autocomplete="off" oninput="filterRows()"/><table id="companies"><thead><tr><th>شناسه شرکت</th><th>کاری</th><th>مصاحبه</th><th>پرونده</th><th>محور عددی</th></tr></thead><tbody>{tbody}</tbody></table></div>
    <p class="footer">ساخته‌شده آفلاین | هیچ فراخوانی خارجی وجود ندارد | no score writes | publication disabled</p></main>
    <script>function filterRows(){{var s=document.getElementById('filter').value.toLowerCase();document.querySelectorAll('#companies tbody tr').forEach(function(r){{r.hidden=!r.dataset.id.toLowerCase().includes(s);}})}}</script></body></html>'''


def main(argv=None):
    p=argparse.ArgumentParser(description="Audit private Jobiew dual-six source/checkpoint (NO writes to DB or API)")
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    args=p.parse_args(argv)
    result, companies = audit(args.source,args.checkpoint)
    args.out_dir.mkdir(parents=True,exist_ok=True)
    (args.out_dir/"qa_report.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n", encoding="utf-8")
    (args.out_dir/"private_qa_preview.html").write_text(html_report(result, companies),encoding="utf-8")
    print(json.dumps({"validation":result["validation"],"records":result["source_records"],"reviewed":result["reviewed"],"next":result["resume_next_experience_id"],"publication":"DISABLED"},ensure_ascii=False))

if __name__=="__main__":
    main()
