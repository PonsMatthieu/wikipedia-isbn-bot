import html
import json
from pathlib import Path
from urllib.parse import quote, urlsplit

from .state import now


def safe_link(url: str, text: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return html.escape(text)
    return '<a href="' + html.escape(url, quote=True) + '" rel="noreferrer">' + html.escape(text) + '</a>'


def write_reports(state, report_dir: Path, *, demo: bool = False) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    rows = state.findings()
    cases = []
    for row in rows:
        page, finding = json.loads(row["page_json"]), json.loads(row["finding_json"])
        cases.append({"id": row["id"], "status": row["status"], "page": {k: v for k, v in page.items() if k != "wikitext"},
                      "finding": finding, "diff": row["diff"], "approved_by": row["approved_by"]})
    payload = {"generated_at": now(), "demo": demo, "stats": state.stats(), "cases": cases}
    json_path, html_path = report_dir / "report.json", report_dir / "report.html"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cards = []
    for case in cases:
        finding, page = case["finding"], case["page"]
        candidates = []
        for candidate in finding["candidates"]:
            evidence = []
            for item in candidate["evidence"]:
                record = item["record"]
                evidence.append("<li>" + safe_link(record["url"], record["source"] + " · " + record["record_id"]) +
                    " — " + html.escape(" | ".join(filter(None, (record["title"], ", ".join(record["authors"]), record["publisher"], record["year"], record["edition"])))) + "</li>")
            mismatch = "; ".join(candidate["mismatches"])
            candidates.append(f'<div class="candidate"><strong>{html.escape(candidate["isbn"])}</strong><span> Score {candidate["score"]:.0%}</span><ul>' + "".join(evidence) + "</ul>" + (f'<p class="warning">{html.escape(mismatch)}</p>' if mismatch else "") + "</div>")
        link = safe_link("https://fr.wikipedia.org/wiki/" + quote(page["title"].replace(" ", "_")), page["title"])
        context = finding["field"]["context"]
        citation = " | ".join(filter(None, (context["title"], ", ".join(context["authors"]), context["publisher"], context["year"])))
        detail = "; ".join(finding["reasons"] + finding["source_errors"])
        cards.append(f'<article><div class="eyebrow">Proposition #{case["id"]} · {html.escape(case["status"])} · révision {page["revision_id"]}</div><h2>{link}</h2><p>{html.escape(citation)}</p><p><b>{html.escape(finding["error_type"])}</b> · Champ {html.escape(finding["field"]["parameter_name"])}</p><pre>{html.escape(finding["field"]["raw_value"])}</pre>' +
                     "".join(candidates) + f'<p class="warning">{html.escape(detail)}</p><details open><summary>Diff proposé</summary><pre>{html.escape(case["diff"] or "Aucune correction proposée")}</pre></details></article>')
    notice = '<p class="demo">DÉMONSTRATION — articles et notices fictifs, aucun appel réseau, aucune édition Wikipédia.</p>' if demo else ""
    document = '''<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Propositions ISBN</title><style>
    :root{color-scheme:light}body{font:16px/1.6 system-ui,sans-serif;background:#f3f5f8;color:#15243a;margin:0}main{max-width:1080px;margin:36px auto;padding:0 22px}h1{font-size:36px;margin-bottom:4px}h2{font-size:23px}a{color:#1642a5}article{background:white;border:1px solid #dce3ec;border-radius:14px;padding:24px;margin:22px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf1f6;padding:16px;border-radius:8px;font:14px/1.6 ui-monospace,monospace}.eyebrow{font-size:13px;letter-spacing:.04em;color:#53647c}.candidate{border-left:4px solid #2a9373;padding:10px 18px;margin:14px 0}.candidate span{float:right}.warning{color:#805020;font-size:14px}.demo{background:#fff0c7;border-radius:10px;padding:16px}footer{color:#53647c;font-size:14px}details summary{cursor:pointer}
    </style><main><div class="eyebrow">Mésange_Futée · Projet ISBN Wikipédia</div><h1>Propositions bibliographiques</h1>''' + notice + '<p>Le score classe les résultats ; il ne mesure pas une probabilité. Vérifier l’édition exacte avant toute approbation.</p>' + ("".join(cards) or '<article>Aucune proposition pour le moment. Le premier run établit la liste de référence.</article>') + '<footer>Généré le ' + html.escape(payload["generated_at"]) + ' · Validation par les commandes approve puis apply · Aucun bouton de publication dans ce rapport</footer></main></html>'
    html_path.write_text(document, encoding="utf-8")
    return json_path, html_path
