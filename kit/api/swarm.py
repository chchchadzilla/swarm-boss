"""
swarm.py -- one boss, a crew of cheaper workers, a hater, and a for-loop that
doesn't take anybody's word for anything.

  pip install anthropic
  set ANTHROPIC_API_KEY   (Windows: setx ANTHROPIC_API_KEY "sk-ant-..." then open a NEW terminal)
  drop .txt / .md / .csv / .json files into ./inputs
  python swarm.py "Rank the top 10 complaints in these reviews, with counts and quotes."

Writes out/report.md, out/receipts.json and out/plan.json, and prints what each model cost.
Prices are Anthropic list prices as of October 2026. Check them before you trust the math.
"""
import asyncio
import json
import pathlib
import random
import re
import sys

import anthropic

BOSS = "claude-fable-5-1"   # want the boss 60% cheaper? use "claude-opus-5-5"
CREW = "claude-sonnet-5-5"
GRUNT = "claude-haiku-5-5"
TIER = {"grunt": GRUNT, "crew": CREW, "boss": BOSS}
UP = {"grunt": "crew", "crew": "boss", "boss": None}
EFFORT = {"grunt": "low", "crew": "medium", "boss": "medium"}
PRICE = {  # $ per million tokens: (input, output)
    "claude-fable-5-1": (10.00, 50.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),  # prompts up to 100K tokens
}

PARALLEL = 8            # workers running at once
MAX_BRIEFS = 40         # hard cap on swarm size
CHUNK_CHARS = 200_000   # ~50K tokens per slice, keeps Haiku under its 100K-token price break
SOLO_CHARS = 600_000    # ~150K tokens. Under this, the boss may just do the job itself
MERGE_CHARS = 400_000   # past this, the crew rolls findings up before the boss reads them

client = anthropic.AsyncAnthropic()
spend = {}  # model -> [input, output, cache_write, cache_read] tokens


def obj(**fields):
    """A JSON-schema object where every field is required."""
    return {"type": "object", "properties": fields, "required": list(fields),
            "additionalProperties": False}


def arr(item):
    return {"type": "array", "items": item}


STR, INT, BOOL = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}
PLAN = obj(
    swarm=BOOL,
    reasoning=STR,
    decisions=STR,
    briefs=arr(obj(id=STR, tier={"type": "string", "enum": ["grunt", "crew", "boss"]}, goal=STR,
                   why=STR, files=arr(STR), example=STR, out_of_scope=STR)),
)
RESULT = obj(status={"type": "string", "enum": ["done", "blocked"]}, summary=STR,
             claims=arr(obj(claim=STR, file=STR, quote=STR)))
VERDICT = obj(flags=arr(obj(claim_id=INT, problem=STR)), gaps=arr(STR))
ROLLUP = obj(points=arr(obj(point=STR, ids=arr(INT))))

PLAN_SYSTEM = f"""You're the boss of a small AI swarm. You plan the work, make the decisions everyone shares, and merge the results, while cheaper models do the bulk work: "grunt" is Claude Haiku 5.5 (mechanical, high-volume work with a clear format, like reading and tagging), "crew" is Claude Sonnet 5.5 (focused work that needs judgment inside a clear brief), and "boss" is you (anything that sets direction or is hard to undo).

First decide whether a swarm is worth it at all. It pays off when the job splits into independent pieces and is too big or too read-heavy for one pass. If the job is one dependent chain, or the material is small enough for you to handle in one pass, set swarm to false and say why; you'll do it yourself.

If it is worth it, write the decisions every worker must share (categories, definitions, formats) so their outputs merge cleanly. Then write one brief per independent slice of files. Each worker sees only its own files and your brief, so give it the goal, why the goal matters to the bigger job, one example of a correct finding, and what's out of scope and why. Pick the cheapest tier that can do each slice well, use at most {MAX_BRIEFS} briefs, and avoid giving two workers the same file unless their goals differ."""

WORKER_SYSTEM = """You're one of several workers, each handling a slice of a bigger job. The boss merges everyone's output, and a script checks every quote you cite against its source file, character for character (it ignores whitespace and capitalization). Claims whose quotes can't be found get thrown out, so copy the supporting text exactly instead of paraphrasing it, and use the file name exactly as it's labeled.

Follow the shared decisions below so your output merges cleanly with everyone else's. If your files don't contain what the brief is after, return no claims and say so in the summary, or set status to "blocked" if the brief itself doesn't make sense. An honest "nothing here" is useful; a guess costs a re-check. Keep the summary short: what you found, and anything the boss should know.

SHARED DECISIONS:
{decisions}"""

HATER_SYSTEM = """You're reviewing work you didn't do. A script has already confirmed that every quote below exists in its source file, so skip that. Look for what the script can't catch: claims that say more than their quote supports, findings that contradict each other or the shared decisions, and anything the job needs that's missing. Only flag what you'd defend. If the work holds up, return empty lists; inventing problems sends the boss chasing nothing."""

ROLLUP_SYSTEM = """You're condensing a batch of verified findings so the boss can read all of them at once. Group findings that say the same thing into one point, keep every finding's id in the point it belongs to, and don't add anything the findings don't say."""

MERGE_SYSTEM = """You're the boss of a swarm, merging the workers' verified findings into the final answer. Every finding below carries an id like [#12] and a receipt: an exact quote a script confirmed is in the source. Build the answer only from these findings, cite the ids behind every claim, and say plainly where the evidence is thin or missing. Lead with the outcome. Write in Markdown."""

SOLO_SYSTEM = """Do this job directly from the files. Back every factual claim with a short exact quote and the file name it came from, and say plainly where the files don't support an answer. Lead with the outcome. Write in Markdown."""


async def ask(model, system, prompt, effort, schema=None, cache=False):
    """One streamed call. Returns JSON (with a schema) or text, or None if declined or cut off."""
    block = {"type": "text", "text": system}
    if cache:  # workers share this prompt, so later ones re-read it at a fraction of the price
        block["cache_control"] = {"type": "ephemeral"}
    params = {
        "model": model,
        "max_tokens": 64000,
        "system": [block],
        "messages": [{"role": "user", "content": prompt}],
        "output_config": {"effort": effort},
    }
    if schema:
        params["output_config"]["format"] = {"type": "json_schema", "schema": schema}
    if model == GRUNT:  # Haiku has no server-side fallback, so it uses the plain endpoint
        stream = client.messages.stream(**params)
    else:  # if a model declines on safety grounds, Anthropic re-routes it instead of stopping
        stream = client.beta.messages.stream(
            **params, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    async with stream as s:
        resp = await s.get_final_message()

    used = spend.setdefault(resp.model, [0, 0, 0, 0])
    u = resp.usage
    used[0] += u.input_tokens
    used[1] += u.output_tokens
    used[2] += getattr(u, "cache_creation_input_tokens", 0) or 0
    used[3] += getattr(u, "cache_read_input_tokens", 0) or 0

    if resp.stop_reason in ("refusal", "max_tokens"):
        return None
    text = "".join(b.text for b in resp.content if b.type == "text")
    if schema is None:
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def load_inputs(folder="inputs"):
    """Every text file in ./inputs. Big ones get cut into slices on line breaks."""
    docs = {}
    for path in sorted(pathlib.Path(folder).rglob("*")):
        if path.suffix.lower() not in {".txt", ".md", ".csv", ".json"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        name = path.relative_to(folder).as_posix()
        if len(text) <= CHUNK_CHARS:
            docs[name] = text
            continue
        part, size, n = [], 0, 1
        for line in text.splitlines(keepends=True):
            if part and size + len(line) > CHUNK_CHARS:
                docs[f"{name}#{n}"] = "".join(part)
                part, size, n = [], 0, n + 1
            part.append(line)
            size += len(line)
        if part:
            docs[f"{name}#{n}"] = "".join(part)
    return docs


SMART_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})


def squish(s):
    return re.sub(r"\s+", " ", s.translate(SMART_QUOTES)).strip().lower()


def check_receipts(claims, flat):
    """The cheapest checker there is: is the quote literally in the file? No model involved."""
    good, bad = [], []
    for c in claims:
        quote = squish(c["quote"])
        (good if len(quote) >= 8 and quote in flat.get(c["file"], "") else bad).append(c)
    return good, bad


async def run_brief(brief, decisions, docs, flat, gate):
    """Two strikes at the brief's tier, then one try a tier up with the failure notes attached."""
    def result(status, tier, summary, claims=(), cut=0):
        return {"id": brief["id"], "tier": tier, "status": status, "summary": summary,
                "claims": list(claims), "cut": cut}

    note = ""
    files = [f for f in brief["files"] if f in docs]
    body = "\n\n".join(f"=== {f} ===\n{docs[f]}" for f in files)
    system = WORKER_SYSTEM.format(decisions=decisions)
    for attempt, tier in enumerate([brief["tier"], brief["tier"], UP[brief["tier"]]], 1):
        if tier is None:
            break
        prompt = f"YOUR BRIEF:\n{json.dumps(brief, indent=2)}{note}\n\nYOUR FILES:\n{body}"
        async with gate:
            r = await ask(TIER[tier], system, prompt, EFFORT[tier], RESULT, cache=True)
        if r and r["status"] == "blocked":
            return result("blocked", tier, r["summary"])
        if r:
            good, bad = check_receipts(r["claims"], flat)
            if len(bad) <= 0.25 * max(1, len(r["claims"])):
                return result("done", tier, r["summary"], good, len(bad))
            problem = (f"{len(bad)} of {len(r['claims'])} quotes weren't in the source, "
                       f"e.g. {bad[0]['quote'][:80]!r}")
        else:
            problem = "the answer came back empty, cut off, or declined"
        print(f"  brief {brief['id']}: strike {attempt} on {tier} ({problem})")
        note = f"\n\nA previous attempt at this brief failed: {problem}. Copy quotes exactly."
    return result("failed", "-", note.strip())


def fmt(c):
    return f"[#{c['id']}] {c['claim']} -- \"{c['quote']}\" ({c['file']})"


async def roll_up(claims, gate):
    """Too many findings for one boss read: the crew boils batches of 200 down to points."""
    async def one(batch):
        async with gate:
            r = await ask(CREW, ROLLUP_SYSTEM, "\n".join(fmt(c) for c in batch), "medium", ROLLUP)
        if r is None:
            return [{"point": "(this batch failed to roll up)", "ids": [c["id"] for c in batch]}]
        return r["points"]
    batches = [claims[i:i + 200] for i in range(0, len(claims), 200)]
    points = [p for ps in await asyncio.gather(*(one(b) for b in batches)) for p in ps]
    return "\n".join(f"- {p['point']} [{', '.join(f'#{i}' for i in p['ids'])}]" for p in points)


def cost_report():
    total, lines = 0.0, []
    for model, (i, o, cw, cr) in spend.items():
        p_in, p_out = PRICE.get(model, (10.00, 50.00))
        cost = ((i + 1.25 * cw + 0.1 * cr) * p_in + o * p_out) / 1e6
        total += cost
        lines.append(f"  {model:<20} in {i + cw + cr:>10,}  out {o:>9,}  ${cost:,.2f}")
    return "\n".join(lines + [f"  {'total':<20} {'':>34}${total:,.2f}"])


async def main():
    if len(sys.argv) < 2:
        sys.exit('usage: python swarm.py "what you want done with the files in ./inputs"')
    job = " ".join(sys.argv[1:])
    docs = load_inputs()
    if not docs:
        sys.exit("No .txt / .md / .csv / .json files found in ./inputs")
    out = pathlib.Path("out")
    out.mkdir(exist_ok=True)
    total = sum(len(t) for t in docs.values())
    print(f"{len(docs)} input slices, roughly {total // 4:,} tokens. The boss is planning...")

    preview = 300 if len(docs) <= 200 else 80
    listing = "\n".join(f"- {n} (~{len(t) // 4:,} tokens): {t[:preview]!r}"
                        for n, t in docs.items())
    plan = await ask(BOSS, PLAN_SYSTEM, f"THE JOB:\n{job}\n\nTHE FILES:\n{listing}", "high", PLAN)
    if plan is None:
        sys.exit("The boss couldn't produce a plan (declined or cut off). Try rewording the job.")
    (out / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

    if not plan["swarm"] and total <= SOLO_CHARS:
        print(f"The boss says skip the swarm: {plan['reasoning']}\nDoing it solo...")
        body = "\n\n".join(f"=== {n} ===\n{t}" for n, t in docs.items())
        report = await ask(BOSS, SOLO_SYSTEM, f"THE JOB:\n{job}\n\nTHE FILES:\n{body}", "medium")
        report = report or "(the boss declined or ran out of room)"
        (out / "report.md").write_text(report, encoding="utf-8")
        print(f"Wrote out/report.md\n\nWhat it cost:\n{cost_report()}")
        return

    briefs = plan["briefs"][:MAX_BRIEFS]
    if not briefs:
        sys.exit(f"The boss wrote no briefs: {plan['reasoning']}")
    print(f"{len(briefs)} briefs: " + ", ".join(f"{b['id']}->{b['tier']}" for b in briefs))

    flat = {n: squish(t) for n, t in docs.items()}
    gate = asyncio.Semaphore(PARALLEL)
    jobs = (run_brief(b, plan["decisions"], docs, flat, gate) for b in briefs)
    results = await asyncio.gather(*jobs)

    claims = []
    for r in results:
        for c in r["claims"]:
            claims.append({"id": len(claims) + 1, "brief": r["id"], **c})
    cut = sum(r["cut"] for r in results)
    print(f"{len(claims)} findings with valid receipts ({cut} cut for fake or altered quotes).")
    print("The hater is reading...")

    sample = random.sample(claims, min(150, len(claims)))
    hater_prompt = (f"THE JOB:\n{job}\n\nSHARED DECISIONS:\n{plan['decisions']}\n\n"
                    f"FINDINGS (a random sample of {len(sample)} out of {len(claims)}):\n"
                    + "\n".join(fmt(c) for c in sample))
    verdict = await ask(CREW, HATER_SYSTEM, hater_prompt, "high", VERDICT)
    verdict = verdict or {"flags": [], "gaps": []}
    flagged = {f["claim_id"]: f["problem"] for f in verdict["flags"]}
    kept = [c for c in claims if c["id"] not in flagged]
    if sample and len(flagged) > 0.2 * len(sample):
        print(f"  heads up: the hater flagged {len(flagged)} of {len(sample)} sampled findings."
              " Treat the rest with suspicion.")

    findings = "\n".join(fmt(c) for c in kept)
    if len(findings) > MERGE_CHARS:
        print("Too many findings for one read. The crew is rolling them up...")
        findings = await roll_up(kept, gate)
    notes = "\n".join(f"- brief {r['id']} ({r['tier']}, {r['status']}): {r['summary']}"
                      for r in results)
    gaps = "\n".join(f"- {g}" for g in verdict["gaps"]) or "- none reported"
    print("The boss is merging...")
    merge_prompt = (f"THE JOB:\n{job}\n\nSHARED DECISIONS:\n{plan['decisions']}\n\n"
                    f"WORKER NOTES:\n{notes}\n\nGAPS THE HATER FOUND:\n{gaps}\n\n"
                    f"VERIFIED FINDINGS:\n{findings}")
    report = await ask(BOSS, MERGE_SYSTEM, merge_prompt, "medium")

    by_id = {c["id"]: c for c in kept}
    cited = sorted({int(n) for n in re.findall(r"#(\d+)", report or "")} & by_id.keys())
    receipts = "\n".join(f"- [#{i}] {by_id[i]['file']}: \"{by_id[i]['quote']}\"" for i in cited)
    report = report or "(the boss declined or ran out of room)"
    report_md = f"{report}\n\n---\n\n## Receipts\n\n{receipts}\n"
    (out / "report.md").write_text(report_md, encoding="utf-8")
    dump = {
        "kept": kept,
        "flagged_by_hater": [{**c, "problem": flagged[c["id"]]}
                             for c in claims if c["id"] in flagged],
        "briefs": [{k: r[k] for k in ("id", "tier", "status", "summary", "cut")} for r in results],
    }
    (out / "receipts.json").write_text(json.dumps(dump, indent=2), encoding="utf-8")
    print(f"Wrote out/report.md and out/receipts.json\n\nWhat it cost:\n{cost_report()}")


if __name__ == "__main__":
    asyncio.run(main())
