# mira-mutation-audit
Detect pull requests that change tests alongside code but whose tests are vacuous — they execute the changed code without asserting anything meaningful about it — a gap delta-verify cannot catch because it only checks that a test file changed, not that the change has mutation-killing power.
