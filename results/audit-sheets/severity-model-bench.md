# News severity — candidate grader bench (#646)

6 run(s) over the same human-graded rows from `severity-audit-sheet.md`, protocol: band. Guards unchanged; the incumbent is re-run as a control rather than quoted from #593.

| model | protocol | band agreement | floor violations | MAE | rejected | s/headline | gate |
|---|---|---:|---:|---:|---:|---:|---|
| `qwen3.5:4b-q4_K_M` (incumbent) | band | 0.760 | 4 | 0.236 | 0.00 | 1.74 | fail |
| `qwen2.5:1.5b-instruct-q4_K_M` | band | 0.562 | 2 | 0.168 | 0.04 | 0.95 | fail |
| `qwen3:1.7b` | band | 0.680 | 4 | 0.198 | 0.00 | 0.38 | fail |
| `gemma3:1b` | band | 0.184 | 4 | 0.235 | 0.02 | 0.52 | fail |
| `llama3.2:3b` | band | 0.760 | 1 | 0.152 | 0.00 | 0.62 | fail |
| `phi4-mini` | band | 0.653 | 4 | 0.260 | 0.02 | 1.07 | fail |

**Gate**: floor violations 0 **and** band agreement >= 0.860 (what #593 published for the incumbent). A candidate that is faster and scores below the gate is recorded and rejected — speed does not buy a missed death.

Rationale honesty is not scored here: the human judged the incumbent's wording, and reusing that column would credit a candidate with an opinion of a different sentence. A winner needs its own `severity-audit`.

**No candidate cleared the gate.** The incumbent keeps the job. A cascade — small model everywhere, incumbent re-grading only rows near a band boundary or carrying a lethal cue — is the remaining option, and it is a separate change with its own measurement.
