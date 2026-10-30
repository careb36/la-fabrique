# Skill Registry

**Delegator use only.** Any agent that launches sub-agents reads this registry to resolve compact rules, then injects them directly into sub-agent prompts. Sub-agents do NOT read this registry or individual SKILL.md files.

See `_shared/skill-resolver.md` for the full resolution protocol.

## User Skills

| Trigger | Skill | Path |
|---------|-------|------|
| go-testing | go-testing | /home/careb1983/.gemini/skills/go-testing/SKILL.md |
| skill-creator | skill-creator | /home/careb1983/.gemini/skills/skill-creator/SKILL.md |
| sdd-apply | sdd-apply | /home/careb1983/.gemini/skills/sdd-apply/SKILL.md |
| sdd-archive | sdd-archive | /home/careb1983/.gemini/skills/sdd-archive/SKILL.md |
| sdd-design | sdd-design | /home/careb1983/.gemini/skills/sdd-design/SKILL.md |
| sdd-explore | sdd-explore | /home/careb1983/.gemini/skills/sdd-explore/SKILL.md |
| sdd-init | sdd-init | /home/careb1983/.gemini/skills/sdd-init/SKILL.md |
| sdd-onboard | sdd-onboard | /home/careb1983/.gemini/skills/sdd-onboard/SKILL.md |
| sdd-propose | sdd-propose | /home/careb1983/.gemini/skills/sdd-propose/SKILL.md |
| sdd-spec | sdd-spec | /home/careb1983/.gemini/skills/sdd-spec/SKILL.md |
| sdd-tasks | sdd-tasks | /home/careb1983/.gemini/skills/sdd-tasks/SKILL.md |
| sdd-verify | sdd-verify | /home/careb1983/.gemini/skills/sdd-verify/SKILL.md |
| skill-registry | skill-registry | /home/careb1983/.gemini/skills/skill-registry/SKILL.md |

## Compact Rules

### go-testing
- Use `teatest` for Bubbletea TUI testing.
- Follow Go idiomatic testing patterns (Table-driven tests).
- Mock external dependencies using interfaces.

### sdd-apply
- Follow the task list in order.
- Verify each task with existing or new tests.
- Maintain consistency with project tech stack and style.

## Project Conventions

| File | Path | Notes |
|------|------|-------|
| REFACTORING_PLAN.md | REFACTORING_PLAN.md | Roadmap and status of the project refactor. |
| CONTRIBUTING.md | CONTRIBUTING.md | Git flow and commit conventions. |
| README.md | README.md | General project overview. |
