# Native output fixtures

`edax-4.6-macos-initial-hint.txt` contains the `hint 4` output and following prompt from a terminal transcript supplied on 2026-10-11. Candidate moves, scores, depths, variations, and durations are unchanged.

- Environment: macOS ARM64, clang, Edax v4.6 source `713a434f13b3d15fb69c61b9ba3641aed82c496c`, with the repository's hash-table allocation patch.
- Version output: `Edax version 4.6 Oct 11 2026 22:43:24 for Apple`.
- Arguments: `-eval-file ./deploy/edax/eval.dat -level 8 -n-tasks 1 -book-usage off`.
- Board: standard initial position, Black to move; no `setboard` command.
- Commands: `version`, `hint 4`, `quit`.

`edax-4.6-macos-quiet-initial-hint.txt` is the second same-day transcript's hint output and following prompt. It uses the backend's full arguments: `-eval-file ./deploy/edax/eval.dat -level 8 -n-tasks 1 -book-usage off -ponder off -auto-store off -mode 3 -verbose 0 -width 250`. Commands were `version`, `setboard ...........................OX......XO........................... X`, `hint 4`, and `quit`. All four candidates again have depth8 and score-3. An earlier bare `setboard` produced a warning; the complete command succeeded.

`edax-4.6-macos-adapter-check.json` is an unchanged copy of the actual `check-edax` report from `eval/results/edax-check.json`. It passed four positions in one native process: initial Black, White after d3, a forced-pass two-empty endgame, and the one-empty position after the pass. Exact score+64 matches the rules engine's final disc difference. Native `PA` is parsed as `pass`. The original report retains its original language as evidence.

These fixtures exercise parsing of real outputs. Individual search durations do not represent backend end-to-end performance.

`pytrio-failed-calibration.json` is a minimal metadata excerpt from a real failed calibration on 2026-10-12. It retains status, model/template, tolerance, sample count, and maximum error. It verifies that training rejects a failed report before making cloud calls. It contains no keys, checkpoint paths, or simulated model scores. The full report stays local.
