import dig
import sys
import os
import re
import csv
import json
import datetime
import discogs_match
from discogs_match import Discogs
import warnings
from typing import Literal
from pydantic import BaseModel

# checks the discogs links already in a store registry with claude, newest
# releases first, and proposes a better link where one is wrong. writes a csv
# report as it goes, nothing in the registry changes until -apply.
#
#   python3 discogs_validate.py -store juno [-count 100] [-out <csv>]
#   python3 discogs_validate.py -store juno -apply <csv> [-min-confidence 0.8] [-dry-run]
#
# claude is only asked where the rules in discogs_match.py can't decide:
#   links    the rules score the linked record first. strong (or ok, outside
#            preorders) is recorded as correct, a conflict or nothing agreeing
#            as wrong, neither costing a claude call. claude only judges links
#            with a single agreeing field. a replacement for a wrong link comes
#            from the rule matcher (-llm-search has claude pick one instead)
#   candidates  single field matches the nightly job saved instead of linking:
#            claude says yes or no to each
# links the rules already confirmed (discogs.py -rescore, or new matches) are
# skipped, -all checks them too.
#
# re-running with the same -out skips releases already in the report, so a run
# can be stopped and picked up again.

MODEL = "claude-opus-5-5"
EFFORT = "low"
REPORT_DIR = "reports"
# a link or candidate claude couldn't call (unsure, or under -min-confidence)
# isn't asked about again for this long, the answer won't have changed
LLM_COOLOFF_DAYS = 90

CSV_FIELDS = [
    "key", "kind", "artist", "title", "label", "cat", "store_link",
    "old_link", "rules", "verdict", "confidence", "reason",
    "new_link", "new_confidence", "new_rules", "new_reason", "candidate",
    "model", "checked",
]


def arg(name, default=None):
    if name in sys.argv:
        return sys.argv[sys.argv.index(name) + 1]
    return default


# ── discogs ──────────────────────────────────────────────────────────────────

# discogs disambiguates names with a number, "Orion (12)"
def clean_name(name):
    return re.sub(r"\s*\(\d+\)$", "", name or "").strip()


# the parts of a discogs record that matter for matching, kept small
def summarise_record(rec):
    return {
        "type": rec.get("_kind"),
        "artists": [clean_name(a.get("name")) for a in rec.get("artists", [])],
        "title": rec.get("title"),
        "labels": [{"name": clean_name(l.get("name")), "catno": l.get("catno")} for l in rec.get("labels", [])],
        "formats": [" ".join([f.get("name", "")] + f.get("descriptions", [])) for f in rec.get("formats", [])],
        "year": rec.get("year"),
        "country": rec.get("country"),
        "tracklist": [
            f"{t.get('position', '')} {', '.join(clean_name(a.get('name')) for a in t.get('artists', []))} - {t.get('title', '')}".strip()
            for t in rec.get("tracklist", []) if t.get("type_", "track") == "track"
        ][:30],
    }


def summarise_hit(hit):
    return {
        "title": hit.get("title"),
        "type": hit.get("type"),
        "labels": hit.get("label", [])[:3],
        "catno": hit.get("catno"),
        "formats": hit.get("format", [])[:6],
        "year": hit.get("year"),
        "country": hit.get("country"),
    }


def summarise_release(r):
    return {
        "artist": r.get("artist", ""),
        "title": r.get("title", ""),
        "label": r.get("label", ""),
        "cat": r.get("cat", ""),
        "tracks": (r.get("track_names") or [])[:30],
        "store": r.get("store", ""),
    }


# hits from the matcher's searches, most specific first, for claude to pick from
def find_candidates(discogs, r):
    seen = set()
    hits = []
    for params in discogs_match.searches(r):
        for hit in discogs.search(**params):
            if hit["id"] in seen:
                continue
            seen.add(hit["id"])
            hits.append(hit)
        if len(hits) >= 12:
            break
    return hits[:12]


# ── claude ───────────────────────────────────────────────────────────────────

SYSTEM = """You check links between record shop listings and Discogs.

Each listing comes from an online record shop (mostly electronic music on vinyl: \
Juno, Redeye, Phonica, Hardwax, Yoyaku, Decks and similar). Someone linked it to a \
Discogs record with a fuzzy text search, and some of those links are wrong. Decide \
whether a Discogs record is the same record as the listing.

It is the same record when it is the same music by the same artist: the same release, \
or another pressing, format or reissue of it, or its Discogs master. A different \
pressing is fine. It is a different record when the artist differs, or it is another \
release that only shares a title, label or catalogue number with the listing \
(common titles like "Debut" or "Untitled" and short catalogue numbers collide often).

Weigh the evidence roughly in this order: catalogue number together with label, \
artist, the tracklist against the shop's track names, then title. Shops abbreviate, \
add format words to titles ("LP", "12\\"", "repress", "limited"), write "VA" or \
"Various" for compilations, and sometimes list remixers or track titles in place of \
the artist. Shop track names may be missing, partial, or just file names. A shop label \
name can be a sublabel or distributor of the Discogs label.

confidence is your probability, from 0 to 1, that your answer is right. Say "unsure" \
when the evidence is too thin to call either way. Keep reasons to one short sentence \
naming the deciding evidence."""


class Verdict(BaseModel):
    match: Literal["yes", "no", "unsure"]
    confidence: float
    reason: str


class Pick(BaseModel):
    # index into the candidates, -1 when none of them is the record
    candidate: int
    confidence: float
    reason: str


class Claude:
    def __init__(self, model, effort):
        self.client = dig.anthropic_client()
        self.model = model
        self.effort = effort
        self.input_tokens = 0
        self.output_tokens = 0

    def ask(self, prompt, output):
        kwargs = {}
        # opus / sonnet: on a safety decline, retry on anthropic's recommended
        # fallback model rather than failing the release
        if "haiku" not in self.model:
            kwargs = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        # the sdk warns output_format is deprecated for output_config.format,
        # but in this version parse() only builds the schema and validates the
        # reply for a pydantic model passed as output_format
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*output_format.*", category=DeprecationWarning)
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=4000,
                system=SYSTEM,
                output_config={"effort": self.effort},
                messages=[{"role": "user", "content": prompt}],
                output_format=output,
                **kwargs,
            )
        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens
        if response.stop_reason in ("refusal", "max_tokens"):
            raise RuntimeError(f"claude stopped: {response.stop_reason}")
        return response.parsed_output

    def verify(self, release, record):
        return self.ask(json.dumps({
            "task": "Is the discogs record the same record as the shop listing?",
            "shop_listing": summarise_release(release),
            "discogs_record": summarise_record(record),
        }, ensure_ascii=False), Verdict)

    def pick(self, release, hits):
        return self.ask(json.dumps({
            "task": "Which discogs search result, if any, is the same record as the shop "
                    "listing? Answer with its index, or -1 if none of them is.",
            "shop_listing": summarise_release(release),
            "candidates": [{"index": i, **summarise_hit(h)} for i, h in enumerate(hits)],
        }, ensure_ascii=False), Pick)


# ── validate ─────────────────────────────────────────────────────────────────

def hit_url(hit):
    return f"https://www.discogs.com{hit['uri']}" if hit.get("uri", "").startswith("/") else hit.get("uri", "")


# the rule verdict for a record, with the preorder caution the nightly job uses
def rule_verdict(r, record):
    verdict, signals = discogs_match.score(r, discogs_match.candidate_from_record(record))
    if verdict == "ok" and discogs_match.is_preorder(r):
        verdict, signals = "weak", signals + ["preorder"]
    return verdict, signals


def validate_one(discogs, claude, key, r, kind):
    disc = r["discogs"]
    link = disc["candidate"]["url"] if kind == "candidate" else disc.get("url", "")
    row = {
        "key": key,
        "kind": kind,
        "artist": r.get("artist", ""),
        "title": r.get("title", ""),
        "label": r.get("label", ""),
        "cat": r.get("cat", ""),
        "store_link": r.get("link", ""),
        "old_link": link,
        "model": "rules",
        "checked": datetime.datetime.now().isoformat(timespec="seconds"),
    }

    record = discogs.record(link)
    if record is None:
        row.update(rules="no gone", verdict="no", confidence=1.0, reason="discogs record no longer exists")
    else:
        verdict, signals = rule_verdict(r, record)
        row["rules"] = f"{verdict} {'+'.join(signals)}".strip()
        if verdict in ("strong", "ok"):
            row.update(verdict="yes", confidence=1.0, reason="rules")
            return row
        # the rules ruled it out (a conflict, or nothing agreeing): they agreed
        # with claude on 95% of these, not worth paying to hear it again
        if verdict == "no" and "-llm-no" not in sys.argv:
            row.update(verdict="no", confidence=1.0, reason="rules")
        else:
            # a single field agreeing: the rules can't call it, claude can
            v = claude.verify(r, record)
            row.update(verdict=v.match, confidence=round(v.confidence, 2), reason=v.reason, model=claude.model)
            if v.match != "no":
                return row

    # the nightly job already searched for candidates and found nothing better
    if kind == "candidate" or "-no-search" in sys.argv:
        return row
    if "-llm-search" in sys.argv:
        return llm_replacement(discogs, claude, r, row)
    return rule_replacement(discogs, r, row)


# a replacement for a wrong link from the rule matcher: free, no claude. a
# corroborated match is proposed as the new link, a single field match is kept
# as a candidate for a later -candidates run
def rule_replacement(discogs, r, row):
    rejected = (r["discogs"].get("rejected") or []) + [row["old_link"]]
    verdict, signals, cand = discogs_match.match_release(discogs, r, exclude=rejected)
    if verdict is None:
        row["new_reason"] = "rules: nothing found"
        return row
    row["new_rules"] = f"{verdict} {'+'.join(signals)}"
    if verdict in ("strong", "ok"):
        row.update(new_link=cand["url"], new_confidence=1.0, new_reason="rules")
    else:
        row.update(candidate=cand["url"], new_reason="rules: single field match, kept as a candidate")
    return row


# the same with claude choosing from the search hits, then checking its pick
# against the full record. -llm-search, two calls per wrong link
def llm_replacement(discogs, claude, r, row):
    hits = find_candidates(discogs, r)
    # the current link is already known not to fit
    hits = [h for h in hits if hit_url(h).split("-")[0] != row["old_link"].split("-")[0]]
    if not hits:
        row["new_reason"] = "no discogs search results"
        return row

    p = claude.pick(r, hits)
    if p.candidate < 0 or p.candidate >= len(hits):
        row["new_reason"] = p.reason
        return row

    url = hit_url(hits[p.candidate])
    picked = discogs.record(url)
    if picked is None:
        row["new_reason"] = "picked record could not be fetched"
        return row
    v2 = claude.verify(r, picked)
    if v2.match == "yes":
        row.update(new_link=url, new_confidence=round(v2.confidence, 2), new_reason=v2.reason)
    else:
        row["new_reason"] = f"best candidate {url} failed the check: {v2.reason}"
    return row


# bring a report written with older columns up to date, so new rows line up
def upgrade_report(path):
    if not os.path.exists(path):
        return
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames == CSV_FIELDS:
            return
        rows = list(reader)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, restval="", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            row.setdefault("kind", "link")
            writer.writerow(row)
    print(f"updated {path} to the current columns")


def done_keys(path):
    upgrade_report(path)
    if not os.path.exists(path):
        return set()
    with open(path, newline="", encoding="utf-8") as f:
        return {row["key"] for row in csv.DictReader(f)}


def linked(entry):
    d = entry.get("discogs")
    return isinstance(d, dict) and "id" in d and "attempted" not in d


def has_candidate(entry):
    d = entry.get("discogs")
    return isinstance(d, dict) and "attempted" in d and isinstance(d.get("candidate"), dict)


# what a registry entry needs checking as: "link", "candidate" or None
def cooling_off(d):
    checked = d.get("llm_checked")
    if not checked or "-all" in sys.argv:
        return False
    age = (datetime.date.today() - datetime.date.fromisoformat(checked)).days
    return age < LLM_COOLOFF_DAYS


def check_kind(entry):
    if linked(entry):
        d = entry["discogs"]
        if d.get("llm_validated") or cooling_off(d):
            return None
        if d.get("match") in ("strong", "ok") and "-all" not in sys.argv:
            return None
        return None if "-candidates" in sys.argv else "link"
    if has_candidate(entry):
        if cooling_off(entry["discogs"]["candidate"]):
            return None
        return None if "-links" in sys.argv else "candidate"
    return None


def validate(store, out):
    token = arg("-discogs-key") or json.load(open("discogs-auth.json"))["token"]
    discogs = Discogs(token, float(arg("-api-sleep", 1.1)))
    claude = Claude(arg("-model", MODEL), arg("-effort", EFFORT))
    count = int(arg("-count", 0))

    reg = dig.load_registry(store)
    done = done_keys(out)
    # registries are in insertion order, so newest last
    todo = [(k, check_kind(reg[k])) for k in reversed(list(reg))
            if k not in done and not dig.validate_release(k, reg[k])]
    todo = [(k, kind) for k, kind in todo if kind]
    if count:
        todo = todo[:count]
    n_cand = sum(1 for _, kind in todo if kind == "candidate")
    print(f"{store}: {len(todo) - n_cand} links and {n_cand} candidates to check, {len(done)} already in {out}")

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    new_file = not os.path.exists(out)
    tally = {"yes": 0, "no": 0, "unsure": 0, "fixed": 0, "rules": 0, "errors": 0}
    with open(out, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new_file:
            writer.writeheader()
        for i, (key, kind) in enumerate(todo, 1):
            r = reg[key]
            name = f"{r.get('artist', '')} - {r.get('title', '')} [{r.get('cat', '')}]"
            if kind == "candidate":
                name += " (candidate)"
            try:
                row = validate_one(discogs, claude, key, r, kind)
            except KeyboardInterrupt:
                print("stopped, re-run to carry on from here")
                break
            except Exception as e:
                tally["errors"] += 1
                print(f"[{i}/{len(todo)}] ERROR {name}: {e}")
                continue
            writer.writerow(row)
            f.flush()
            tally[row["verdict"]] += 1
            if row["model"] == "rules":
                tally["rules"] += 1
            by = "rules" if row["model"] == "rules" else f"{row['confidence']:.2f}"
            line = f"[{i}/{len(todo)}] {row['verdict'].upper():6} {by:5} {name}"
            if row["verdict"] != "yes":
                line += f"\n    old  {row['old_link']}\n    why  {row['reason']}"
                if row.get("new_link"):
                    tally["fixed"] += 1
                    line += f"\n    new  {row['new_link']} ({row['new_confidence']:.2f})"
                elif row.get("new_reason"):
                    line += f"\n    none {row['new_reason']}"
            print(line, flush=True)

    print(f"done: {tally['yes']} correct, {tally['no']} wrong, {tally['unsure']} unsure, "
          f"{tally['fixed']} replacements found, {tally['errors']} errors")
    print(f"{tally['rules']} decided by the rules, {tally['yes'] + tally['no'] + tally['unsure'] - tally['rules']} by claude "
          f"({claude.input_tokens} tokens in, {claude.output_tokens} out)")
    print(f"report: {out}")


# ── apply ────────────────────────────────────────────────────────────────────

# write a reviewed report back to the registry and firebase:
#   correct links are marked llm_validated (or, when the rules decided, with
#   their match) so later runs skip them
#   wrong links with a confirmed replacement are swapped for it
#   wrong links with no replacement are cleared, the old one remembered as
#   rejected so the nightly job doesn't put the same false positive back
#   confirmed candidates become links, rejected ones are dropped
# rows under -min-confidence, and unsure rows, keep their link (or candidate),
# marked so the validator doesn't pay to ask again for LLM_COOLOFF_DAYS
def apply(store, path):
    min_conf = float(arg("-min-confidence", 0.8))
    reg = dig.load_registry(store)
    changed = {}
    counts = {"validated": 0, "replaced": 0, "cleared": 0, "promoted": 0, "dropped": 0,
              "parked": 0, "skipped": 0}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = row["key"]
            entry = reg.get(key)
            conf = float(row["confidence"] or 0)
            if row.get("kind") == "candidate":
                if entry and has_candidate(entry) and entry["discogs"]["candidate"]["url"] == row["old_link"]:
                    if apply_candidate(entry, row, conf, min_conf, counts):
                        changed[key] = entry
                        continue
                counts["skipped"] += 1
                continue
            if not entry or not linked(entry) or entry["discogs"].get("url") != row["old_link"]:
                counts["skipped"] += 1
                continue
            if row["verdict"] == "yes" and row["model"] == "rules":
                verdict, _, signals = row["rules"].partition(" ")
                entry["discogs"].update(match=verdict, signals=signals.split("+") if signals else [],
                                        matcher=discogs_match.MATCHER_VERSION)
                counts["validated"] += 1
            elif row["verdict"] == "yes" and conf >= min_conf:
                entry["discogs"]["llm_validated"] = conf
                counts["validated"] += 1
            elif row["verdict"] == "no" and row["new_link"] and float(row["new_confidence"] or 0) >= min_conf:
                rejected = (entry["discogs"].get("rejected") or []) + [row["old_link"]]
                entry["discogs"] = {
                    "url": row["new_link"],
                    "id": discogs_match.url_id(row["new_link"]),
                    "matcher": discogs_match.MATCHER_VERSION,
                    "rejected": rejected,
                }
                if row.get("new_rules"):
                    verdict, _, signals = row["new_rules"].partition(" ")
                    entry["discogs"].update(match=verdict, signals=signals.split("+") if signals else [])
                else:
                    entry["discogs"]["llm_validated"] = float(row["new_confidence"])
                counts["replaced"] += 1
                print(f"replace {key}: {row['old_link']} -> {row['new_link']}")
            elif row["verdict"] == "no" and conf >= min_conf:
                rejected = (entry["discogs"].get("rejected") or []) + [row["old_link"]]
                entry["discogs"] = {"attempted": True, "matcher": discogs_match.MATCHER_VERSION,
                                    "checked": datetime.date.today().isoformat(), "tries": 1,
                                    "rejected": rejected}
                if discogs_match.is_preorder(entry):
                    entry["discogs"]["preorder"] = True
                if row.get("candidate"):
                    _, _, signals = row.get("new_rules", "").partition(" ")
                    entry["discogs"]["candidate"] = {"url": row["candidate"],
                                                     "id": discogs_match.url_id(row["candidate"]),
                                                     "signals": signals.split("+") if signals else []}
                counts["cleared"] += 1
                print(f"clear   {key}: {row['old_link']}")
            else:
                # unsure, or not sure enough: the link stays, marked so the
                # validator leaves it for LLM_COOLOFF_DAYS
                entry["discogs"].update(llm_checked=row["checked"][:10], llm_verdict=row["verdict"])
                counts["parked"] += 1
            changed[key] = entry

    print(f"{counts['validated']} validated, {counts['replaced']} replaced, "
          f"{counts['cleared']} cleared, {counts['promoted']} candidates linked, "
          f"{counts['dropped']} candidates dropped, {counts['parked']} unsure (left for "
          f"{LLM_COOLOFF_DAYS} days), {counts['skipped']} no longer match the registry")
    if "-dry-run" in sys.argv or not changed:
        return
    dig.write_registry(store, reg)
    dig.setup_firebase_auth()
    dig.patch_releases(changed)
    print(f"wrote diig-registry/{store}/ and patched {len(changed)} releases")


# a candidate the llm confirmed becomes the link, one it rejected is dropped
# (and remembered, so the nightly job doesn't offer it again)
def apply_candidate(entry, row, conf, min_conf, counts):
    disc = entry["discogs"]
    if conf < min_conf or row["verdict"] == "unsure":
        disc["candidate"].update(llm_checked=row["checked"][:10], llm_verdict=row["verdict"])
        counts["parked"] += 1
        return True
    cand = disc.pop("candidate")
    if row["verdict"] == "yes":
        entry["discogs"] = {"url": cand["url"], "id": cand["id"], "llm_validated": conf,
                            "matcher": discogs_match.MATCHER_VERSION}
        counts["promoted"] += 1
        print(f"link    {row['key']}: {cand['url']}")
    else:
        disc["rejected"] = disc.get("rejected", []) + [cand["url"]]
        counts["dropped"] += 1
    return True


def display_help():
    print("discogs_validate.py")
    print("")
    print("  -store <name>          store registry to check (required)")
    print("  -out <csv>             report path, default reports/<store>-discogs.csv")
    print("                         re-running with the same path resumes")
    print("  -count <n>             stop after n releases")
    print("  -no-search             only judge existing links, don't look for new ones")
    print("  -llm-no                also ask claude about links the rules rule out")
    print("  -llm-search            have claude find replacements, not the rule matcher")
    print("  -links / -candidates   check only links, or only the nightly job's candidates")
    print("  -all                   also check links the rules already confirmed, and")
    print(f"                         ones claude was unsure of in the last {LLM_COOLOFF_DAYS} days")
    print("  -model <id>            claude model, default " + MODEL)
    print("  -effort <level>        low, medium, high..., default " + EFFORT)
    print("  -discogs-key <token>   else discogs-auth.json")
    print("  -api-sleep <s>         gap between discogs requests, default 1.1")
    print("")
    print("  -apply <csv>           write a reviewed report to the registry and firebase")
    print("  -min-confidence <x>    only act on rows at least this sure, default 0.8")
    print("  -dry-run               with -apply, print what would change")
    print("  -key <json>            firebase service account, else diig-auth.json")
    print("")
    print("  -anthropic-key <key>   else ANTHROPIC_API_KEY, else anthropic-auth.json")


def main():
    if "-help" in sys.argv or "-store" not in sys.argv:
        display_help()
        return
    store = arg("-store")
    if "-apply" in sys.argv:
        apply(store, arg("-apply"))
    else:
        validate(store, arg("-out", f"{REPORT_DIR}/{store}-discogs.csv"))


if __name__ == "__main__":
    main()
