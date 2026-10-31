## Description
Please include a summary of the change and which issue is fixed. Please also include relevant motivation and context.

Fixes # (issue)

## Type of change
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Refactoring
- [ ] Performance improvement
- [ ] Test addition or update

## What was run
<!-- Observations, not claims: each command with its exit status, or a link to
the CI run. "Tests pass" without a command or a link does not count. Leave out
what you did not run rather than ticking it. -->

| Command | Exit status or CI link |
|---------|------------------------|
|         |                        |

## Exercised by an agent
<!-- What an AI agent ran or looked at to check the change, and which tool it
was (for example Claude Code, Copilot). This is the agent's claim. Write
"none" if no agent was involved. -->

## Tested by a person
<!-- What a person tried by hand, and what they saw. Only a person fills this
in; an agent leaves it empty. -->

## Checklist
- [ ] My code follows the style guidelines of this project (`CODING_STANDARDS.md`)
- [ ] I have performed a self-review of my own code
- [ ] I have commented my code, particularly in hard-to-understand areas
- [ ] I have made corresponding changes to the documentation
- [ ] My changes generate no new warnings
- [ ] I have added tests that prove my fix is effective or that my feature works
- [ ] Any dependent changes have been merged and published
- [ ] The pull request targets the line it changes (`main`, `fusion` or `meta-vr`), and its head is green

## Backend changes
- [ ] Backend tests run: `cd backend && PYTHONPATH=.:app python3 -m pytest tests -q` (result under "What was run")
- [ ] New dependencies added to `backend/pyproject.toml` and lock file updated

## Frontend changes
- [ ] Frontend tests run: `cd frontend && npm run test:run` (result under "What was run")
- [ ] TypeScript compiles: `cd frontend && npx tsc --noEmit`
- [ ] i18n strings added to both `en.json` and `es.json`

## Screenshots (if applicable)
Add screenshots to show the changes.
