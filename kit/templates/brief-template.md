# The brief (what the boss hands each worker)

A brief is context, not a script. The worker starts with a blank head and only knows what's in here, so every line should earn its spot.

```
BRIEF 07 -> grunt

Goal:      Tag each review in inputs/reviews/0301-0350.txt with one complaint
           category from work/decisions.md.

Why:       We're ranking the biggest complaints about a PDF editor across 20,000
           reviews. Your 50 are one slice. Counts get added up across every slice,
           so consistent categories matter more than clever ones.

Look at:   inputs/reviews/0301-0350.txt
           work/decisions.md

Good output looks like:
           r0317 | export-breaks-fonts | "every time I export, my fonts turn into Times New Roman"

Out of scope (and why):
           Summarizing or ranking -- the crew does that after every slice is in.
           New categories -- they'd break the counts. Use "other" plus a short note.

Write to:  work/tags_07.md, then reply with a two-line summary.
```

What's in there, and what's deliberately NOT:

- Goal + why. The 5-family models do noticeably better when they know what the work is FOR.
- File paths instead of pasted content. The worker loads what it needs, when it needs it.
- One example of a correct output. One good example beats twenty rules.
- Boundaries with reasons. A boundary with a reason gets followed; a bare "DON'T" gets lawyered.
- No step-by-step script, no ALL CAPS, no "CRITICAL: YOU MUST." Current models follow instructions closely enough that yelling makes them over-apply the rule.
