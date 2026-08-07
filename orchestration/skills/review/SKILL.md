---
name: review
description: Review - check worktree-local diff or PR against the linked plan note and code quality, output an approve / request-changes verdict. Use when impl is done and changes need a sanity check before commit.
license: MIT
metadata:
  version: "1.0"
---

# Review Skill

Leaf skill for reviewing impl output. **Effect first, code second**: confirm the change is
right via the cheapest appropriate check (static gates for UI, cheap non-browser runtime for
API/CLI), then do a light pass over the code against the plan note. Agent-driven browser
inspection and screenshots are opt-in (AGENTS.md), not a default review step. Produces a
review note. **Does not change code, commit, or merge.**

Loaded via `y chat --skill review`, usually dispatched by the dev coordinator after the impl
callback (and before `y dev commit`), or directly for an ad-hoc audit.

## Working mode

Runs inside the worktree being reviewed (the caller passes `--work-dir <worktree_path>`), or in
the project main directory if reviewing a PR.

## Workflow

1. `y todo get <todo_id>`: read the todo desc plus the linked plan note.
2. **Get the diff**:
   - **Worktree-local**: `git status` + `git diff` + `git diff --cached` (uncommitted changes)
   - **Already committed in the worktree**: `git log <base>..HEAD` + `git diff <base>..HEAD`
   - **PR**: `gh pr diff <pr-number>` (or `gh pr view <pr-number>`)
3. **Read the plan note** (linked to the todo). That is your spec.
4. **Smoke-verify the effect FIRST, before reading code line by line**: confirm the change is
   right with the cheapest appropriate check. A clean-looking diff that clearly cannot produce
   the plan's effect is still `request-changes`.
   - **UI / visual-delta changes** (layout or style, a new or restyled component, a changed
     rendered value or format, hover/menu state, responsive fit): the default is the AGENTS.md
     static gate (typecheck or build, lint, non-browser tests). Do **not** start a dev server or
     drive a browser as routine review self-verification; screenshots are also opt-in. Runtime
     UI acceptance is left to the user unless they explicitly asked. When they did ask and you
     capture a PNG, **persist it under `$Y_AGENT_HOME/assets/screenshots/`, never `/tmp`**, and
     cite the full path.
   - **Non-UI runtime effects** (CLI output, API response, cheap scriptable smoke): reproduce
     with the command, `curl`, or test suite and compare to what the plan or todo said. These
     stay allowed and are preferred over pure code reading when cheap.
   - **If a requested runtime check cannot be done here** (no runnable surface, needs
     production data or secrets you lack), say so explicitly in the note and fall back to
     verifying that the plan's stated verify step is satisfiable. Do not silently skip it and
     claim it works.
5. **Light code pass, only after the effect checks out. Review against:**
   - **Plan adherence**: did impl do what the plan said? Anything skipped, anything
     out-of-scope added?
   - **Surgical scope**: every changed line should trace to a plan sub-task. Flag refactors of
     adjacent code, reformatting, or unrequested "improvements". Pre-existing dead code deleted
     by impl is also a finding unless the plan called for it.
   - **Verifiability**: each completed sub-task has an obvious way to confirm it works (the
     plan's verify step is satisfied, or impl recorded a concrete check). "I think it works" is
     a finding.
   - **Correctness**: obvious bugs, off-by-ones, wrong types, missing error paths.
   - **Code quality**: dead code, duplicated logic, unclear naming, comments stating the
     obvious.
   - **Consistency**: matches surrounding code style and existing conventions.
6. **Write the review note.** First decide whether this is a new note or a new round on an
   existing one (see "One deliverable, one note"). The path is
   `$Y_AGENT_HOME/pages/review-<todo_id>-<slug>.md` (**absolute path**: `--work-dir` is a
   worktree, but the review file must land in the top-level `pages/`), where `<slug>` names the
   **deliverable**, never the round:
   ```markdown
   ---
   title: review for todo <id> — <slug>
   type: review
   project: <project>
   todo: <todo-id>
   verdict: approve | request-changes | partial
   rounds: <n>
   ---

   ## Verdict
   approve | request-changes | partial (context handoff, see "Not yet reviewed")
   Round <n>, <YYYY-MM-DD>. <one line: what this round covered / what changed since the last one>

   ## Open findings (blocking)
   - [file:line] description — why it matters
   (empty on approve; this section is the live list across rounds, not per-round history)

   ## Round <n> — <YYYY-MM-DD> — <verdict>

   ### Smoke verification (effect)
   - checks run: static gate (typecheck/build/tests) and/or cheap non-browser runtime; what was observed
   - browser UI / screenshot only if the user asked: how it was inspected + path(s) under assets/screenshots/

   ### Plan adherence
   - …

   ### Findings (request-changes)
   - [file:line] description — why it matters

   ### Suggestions (nit, non-blocking)
   - …
   ```
   Round 1 fills `## Round 1`. A re-review **appends `## Round <n+1>` at the end** and rewrites
   the header block (front-matter `verdict` / `rounds`, `## Verdict`, `## Open findings`) so the
   top of the file always states the current state. Never edit a past round's text; resolve its
   findings by saying so in the new round.
7. **Link the review to the todo**:
   `y assoc note pages/review-<todo_id>-<slug>.md --todo <todo_id>` (this CLI takes the path
   relative to `$Y_AGENT_HOME`). Run it on appended rounds too; it is idempotent when the note
   is already linked.
8. Call back to the caller with the verdict and the review note path, then **stop**. No repeat
   of the findings in this chat (AGENTS.md "Callback rules"): the note holds them and the
   coordinator reports to the user.
   ```bash
   y chat --chat-id <from_chat> -m "review done: <approve|request-changes>, see $Y_AGENT_HOME/pages/review-<todo_id>-<slug>.md" \
     ${Y_TOPIC:+--from-topic $Y_TOPIC} --trace-id <todo_id>
   ```
   On `request-changes`, the verdict plus the note path *is* the complete callback; at most add
   a clause naming how many blocking findings there are. Never enumerate findings in `-m`. The
   coordinator re-dispatches `impl` pointed at the note.

## One deliverable, one note (a re-review appends a round)

**Note identity follows the deliverable, not the review session.** Every review of the same
change (round 1, the re-review after impl fixed the findings, the re-review after that) lives in
**one** file, gaining a `## Round <n>` section each time. Whether you are the same session
resuming or a fresh session dispatched after a handoff, the note you write to is the same one.
A new session is not a reason for a new file.

**Before writing, look for the existing note:**

```bash
y todo get <todo_id>                                 # linked notes, including earlier review notes
ls $Y_AGENT_HOME/pages/review-<todo_id>-*.md
```

Read any candidate's front matter and `## Verdict`, then decide:

- **Same deliverable → append a round.** The diff you are reviewing continues work whose
  earlier verdict this review supersedes: fixes for that note's findings, a further pass over
  the same sub-task, more work on the same document, module, or feature slice under the same
  plan sub-task.
- **Genuinely separate work → new note.** A distinct plan sub-task or a different deliverable,
  whose earlier verdict stays independently valid after this review lands: a different phase of
  the same migration, a runbook versus the code it describes, two unrelated sub-tasks under one
  long-lived todo.

**Deciding test**: *after this review, does the earlier verdict still stand on its own?* If it
is now stale or superseded → same note, next round. If both verdicts remain true about
different things → separate notes.

**Slug smell**: if the slug you are about to use contains `r2`, `v3`, `-fix`, `round`, `again`,
or `followup`, you are naming a round, not a deliverable. Find the existing note and append
instead.

**Keep it readable as it grows** (same spirit as the plan-note budget, not the same numbers;
rounds are a legitimate reason to grow, bloat is not):

- A round section is normally **40 lines or fewer**: what changed since the last round, the
  checks you ran, the findings. Do not restate the plan, earlier rounds' reasoning, or
  verification you already recorded.
- **Prune before appending.** When a past round's findings are all resolved, condense that
  section to its outcome (`## Round 2 — 2026-08-05 — request-changes: 2 blocking findings on
  the export gate; both fixed in round 3`). Full detail is only worth keeping for the current
  round and for anything still open.
- The soft target for the whole note is **300 lines or fewer**; if appending would blow past
  it, condense resolved rounds first. `## Open findings` at the top is the one live list. A
  reader must never have to diff round sections to learn what is still broken.

## Context handoff (running low on context)

Review is a dispatched leaf, so per AGENTS.md "Context handoff" it **calls back to the
coordinator and never restarts itself**. Do not spawn a successor review session. The
coordinator decides whether the rest of the diff needs a fresh review dispatch.

On a handoff reminder (or an obviously long review):

1. **Write and link the review note now, partial**, at the normal path (appending a round if
   the note already exists), with an explicit `## Not yet reviewed` section listing the files
   and areas still uncovered. The successor session continues in this same note; its coverage
   of the remainder is the next round, not a new file.
2. **Verdict rule under handoff**: report `request-changes` if you already have a blocking
   finding; otherwise use `partial - incomplete review` rather than `approve`. Never approve a
   diff you have not finished reading. An unfinished review claiming approval is worse than no
   review.
3. `y assoc note pages/review-<todo_id>-<slug>.md --todo <todo_id>`.
4. **Call back** saying this is a context handoff, with the note path, the partial verdict, and
   what is left to cover.
5. Stop.

## Verdict rule

- **approve**: no blocking issues; suggestions and nits are fine to leave for follow-up.
- **request-changes**: at least one blocking finding (a correctness bug, a plan
  mis-implementation, missing required behavior). The coordinator should re-dispatch `impl`
  with the review note attached.
- **partial**: only for a context handoff: the diff was not fully covered and no blocking
  finding was found yet. Not an approval. The coordinator should dispatch a fresh review for
  the uncovered areas before commit.

## Notes

- **Read-only**: no code changes, no commits, no `git add` / `git push`. (Cheap non-browser
  smoke, or an on-request app check, is observation, not a code change.)
- **Effect first, then code**: confirm the result is right with the AGENTS.md-appropriate check
  (static for UI by default, cheap CLI/API runtime when applicable) before scrutinizing the
  diff. A wrong effect is `request-changes` no matter how clean the code reads.
- **Anchor on the plan note**: the verdict answers "did impl do what the plan said", not "is
  this code perfect". Out-of-spec polish is a follow-up item to report, not a blocker.
- **Do not expand scope**: if you find unrelated issues outside the diff, note them as
  follow-up items; do not downgrade the verdict for them.
- **Never `y todo add`**: nits, out-of-spec polish, and unrelated issues live in the review
  note's follow-up section and in your callback. Do not turn them into todos yourself. The user
  decides what gets queued (AGENTS.md "Todo creation is authorized, not self-selected"). You
  may only `y todo update --progress` on the todo you were given.
- **One note per deliverable, rounds appended**: a re-review of the same change never creates a
  second file. Check `y todo get <todo_id>` and `ls pages/review-<todo_id>-*.md` before writing.
- **Review files live under `$Y_AGENT_HOME/pages/`** (absolute path), filename
  `review-<todo_id>-<slug>.md`, the slug naming the deliverable. **Never** write to
  `<worktree>/pages/` or any project-local pages dir. Common pitfall: when `--work-dir` is a
  worktree, a relative `pages/foo.md` silently lands at `<worktree>/pages/foo.md`. Always use
  the absolute path. Link it with
  `y assoc note pages/review-<todo_id>-<slug>.md --todo <todo_id>` (relative path for the CLI).
