# Software Factory Smoke Test

Date: 2026-10-26

This file exercises the local software factory flow end to end: a GitHub issue is
picked up by issue-to-PR, QA changes run against the resulting branch, an
independent reviewer inspects the exact head commit, and the delivery watchdog
merges once review and CI are green.

This file is a disposable marker for that smoke test and is safe to remove
afterwards.
