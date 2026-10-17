# Native output fixtures

`teaching-native-cases.json` contains rules-derived demonstrations for positions 16 and 22 of `review-native-positions.json`. Position 16 checks all nine defenses after b1–e1 and demonstrates the unavoidable a1 corner; position 22 has shared corner access, which must not be described as the cause of the score difference. No model output is used in this fixture.

`review-native-positions.json` contains 22 original positions and the complete 64-event history from the actual Edax-backed game used in the 2026-10-17 review API checks. It includes displayed-hint adoption, both player perspectives, tied opening moves, and exact endgames. Generated prose and model/account metadata were removed; scores, boards, variations, and played moves were preserved. It tests evidence selection, rule-derived comparisons, legal variation replay, and rejection of unsupported coaching references.

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
