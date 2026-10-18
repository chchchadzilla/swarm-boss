# The kit

Everything the guide tells you to copy, as real files. Copying out of a PDF eats indentation -- use these instead.

```text
kit/
├── claude-code/              <- Lane A (no code). Copy the CONTENTS of this folder into your job folder.
│   ├── CLAUDE.md             <- the boss's rules
│   └── .claude/agents/
│       ├── grunt.md          <- Haiku 5.5, low effort: volume work
│       ├── crew.md           <- Sonnet 5.5, medium effort: judgment inside a brief
│       ├── hater.md          <- Sonnet 5.5, high effort, read-only: finds what's wrong
│       └── Explore.md        <- pins Claude Code's built-in search helper to Haiku (the money-leak plug)
├── templates/
│   ├── kickoff-prompt.md     <- what you paste to start a job
│   └── brief-template.md     <- what a good worker brief looks like, and why
└── api/
    └── swarm.py              <- Lane B: one file, one dependency (pip install anthropic)
```

Quick start, Lane A: copy `claude-code/` into a new folder, drop your stuff in `inputs/`, open the folder in Claude Code, `/model fable`, `/effort high`, paste the kickoff prompt. If `.claude/agents/` is brand new, restart Claude Code once.

Quick start, Lane B: `pip install anthropic`, set `ANTHROPIC_API_KEY`, put `swarm.py` next to an `inputs/` folder of text files, run `python swarm.py "what you want done"`.

Prices and model names are October 2026. If you break it, tell me how so I can make it better.
