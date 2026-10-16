---
title: Learning
type: prd
project: y-agent
feature: learning
status: approved
---

# Learning

> **Status: approved.** Roy approved the V1 scope on 2026-10-11 (todo 3861),
> accepting all six recommended answers recorded under Approved Scope Decisions.

## Problem Statement

Roy regularly shares something and says "学习一下": an X post, a blog or WeChat
article, a GitHub repository, or a video. The agent work behind these requests
is already good, but every run invents its own shape, so the results are hard to
find again and hard to act on.

A bounded review of the learning-tagged todos from 2026-09-01 to 2026-10-11
(3857, 3856, 3853, 3839, 3825, 3809, 3795, 3791, 3735, 3724, 3711, 3706, 3704,
3590, 3461, 3348, 3344) shows:

| Finding | Evidence |
|---------|----------|
| Source types recur: X posts, articles (blog / WeChat), GitHub repos, videos. | posts 3839, 3825, 3735, 3711, 3704; articles 3791, 3706, 3795, 3590, 3348; repos 3856, 3809, 3724, 3461; videos 3857, 3853 |
| About a third of the requests leave no note. The answer exists only in todo progress and a manager chat. | 3839, 3795, 3735, 3711, 3706, 3704 ("delivered in manager chat e7432a") |
| Note naming and metadata drift. Some notes are missing the `todo` field, the `learning` tag, or front matter tags entirely. | `pages/study-3856-morluto-rea.md` (no `learning` tag), `pages/transcript-3857-...md` (no tags, no todo), `pages/research-memoh.md`, `pages/loopx.md`, `pages/git-knowledge-loop.md` (no id in name) |
| The `learning` tag is not applied consistently. | 3857, the representative video study, is untagged. |
| Source carriers (`y link`) are created only sometimes, mostly by hand, and fetches sometimes fail. | 3344 (Jina 403, carriers created via `y assoc link`), 3348, 3590 |
| The best notes already share a structure: verdict first, pinned source facts, "what is new vs restated", relevance to Roy as proposals, and sources. | `pages/study-3809-gefei-seo-cookbook.md` (pinned commit SHA), `pages/research-3590-ai-craft-and-career.md` (verified vs unverified table), `pages/study-3825-...md` |
| Takeaways sometimes become real changes, but nothing tracks them back to the source. | 3825 → shared diagram rule in plan/review skills; 3856 → `rea` skill; 3724 → AGENTS.md size guard proposal |
| Video studies need retrieval, transcription, and artifact handling that text sources do not. | 3853 (caption track via yt-dlp), 3857 (local ASR, `assets/transcript-3857/`, term corrections) |

As a result, Roy cannot answer "what did I learn about X", "which proposals from
my reading did I actually adopt", or "where is that video transcript" without
remembering todo ids.

## Solution

Treat learning as one lightweight, standardized workflow plus a small retrieval
surface. Do not build a generic knowledge base.

1. **One workflow (skill)** handles every "learn this" request. It classifies the
   source (post / article / repo / video), retrieves it with existing tools,
   writes one standardized learning note, and registers the existing carriers
   (todo tag, link, note association, optional entity). Video retrieval and
   transcription follow the `video-learning` skill (todo 3861 deliverable 1).
2. **One note contract.** Every request produces a note, including quick answers.
   The note separates source facts, assistant interpretation, and actionable
   takeaways, and records provenance.
3. **One `learning` module (V1, read-mostly)** gives Roy a list, filters, and a
   takeaway view over those notes, plus a conformance check. It stores nothing
   new: all data lives in existing notes, todos, links, tags, and entities.

## User Stories

1. As Roy, I want to share a URL with "学习一下" and get the same kind of output every time, so that I know what to expect without writing a detailed request.
2. As Roy, I want the workflow to detect whether the source is a post, article, repository, or video, so that it uses the right retrieval path.
3. As Roy, I want quick summaries (one-shot search bot answers) saved as short notes too, so that nothing I asked about exists only in a chat.
4. As Roy, I want a deeper "study" depth for sources that deserve it, so that cheap questions stay cheap and important ones get verification.
5. As Roy, I want the note to open with the conclusion and verdict, so that I can stop reading after the first screen.
6. As Roy, I want source facts kept apart from the assistant's interpretation and from proposals for me, so that I never mistake an inference for what the author said.
7. As Roy, I want unverified claims marked as unverified (for example, the author's claims or a repost date used in place of the original date), so that I don't over-trust them.
8. As Roy, I want the exact source pinned (URL, author, publish time, fetch time, commit SHA for repos, media id for videos), so that I can tell which version I learned from.
9. As Roy, I want short verbatim quotes kept where wording matters, so that I can check the interpretation against the original.
10. As Roy, I want actionable takeaways written as proposals with a cheapest-trial suggestion, so that learning leads to decisions without changing anything automatically.
11. As Roy, I want each takeaway to carry a status (proposed / adopted / declined) and a pointer to where it was adopted, so that I can see what my reading actually changed.
12. As Roy, I want an adopt / try / skip verdict for tools and repos, so that a repo study ends in a decision.
13. As Roy, I want every source URL saved as a link carrier tagged `learning` and associated with the todo, so that I can find the source from the link list too.
14. As Roy, I want the note associated with the todo and tagged `learning`, so that `y tag get learning` and the todo detail view both find it.
15. As Roy, I want the source linked to an existing entity (person, product, project) when one exists, so that the knowledge graph connects without creating entities for every author.
16. As Roy, I want video studies to try existing captions first and fall back to local transcription, so that audio stays local and costs stay at zero by default.
17. As Roy, I want video transcripts to keep timestamps, label generated text as generated, and list uncertain terms and corrections, so that I can trust and fix them.
18. As Roy, I want transcript and media artifacts kept in a per-todo local asset directory referenced from the note, so that I can find them later without them being committed or uploaded.
19. As Roy, I want any paid service, external upload, cookie use, or publication to require my approval for that task, so that a past approval is never treated as standing permission.
20. As Roy, I want a Learning panel that lists my learning notes newest first, each row showing the title, the original source link, tags, a link to the study report note, a one-line summary, the study time, source type, and verdict, so that I can scan what I studied and jump to the source or the report from the list.
21. As Roy, I want to filter that list by source type, tag, and verdict, and search it by title / summary / author / URL, so that I can answer "what did I read about MCP".
22. As Roy, I want a view of open takeaways (still `proposed`), so that I can revisit good ideas I haven't acted on.
23. As Roy, I want clicking an item to open a Learning detail view (title, summary, sources with pins, tags, verdict, takeaways with status and refs, artifacts, the todo, and the report note), so that I see one study's whole record in one place.
24. As Roy, I want `y learning list` / `y learning takeaways` on the CLI, so that agents and I can query the same index from a terminal.
25. As Roy, I want `y learning lint` to report notes that break the contract (missing front matter fields, missing todo association, missing link carrier), so that drift is visible without a migration.
26. As Roy, I want old learning notes shown as "legacy" rather than hidden or rewritten, so that history stays reachable without a bulk migration.
27. As Roy, I want notes in Chinese by default, with structured fields in English, so that the content reads naturally and stays machine-filterable.
28. As Roy, I want the workflow to treat fetched content as untrusted data, never as instructions, so that a malicious post cannot steer the agent.
29. As Roy, I want personal context used only when it changes the "relevance to Roy" section, with the smallest lookup and nothing private sent to external search, so that studying a public post never leaks private notes.
30. As Roy, I want the detail view to open the full report in the existing note reader instead of re-rendering it, so that there is no second Markdown reader to maintain.
31. As Roy, I want each learning note to carry a one-line summary written by the workflow, so that list rows and the detail header say what the source is about without opening the report.
32. As Roy, I want each list row to show when I studied the source, and the detail view to also show when the source was published and fetched, so that I can place a study in time and tell an old source from an old study.
33. As Roy, I want each learning note to carry a readable one-line title that matches its report heading, so that list rows and the detail header show a human title instead of a filename.

## Implementation Decisions

### Workflow lives in a skill; the module only indexes

The repeatable "learn this" procedure is agent judgment work, so it is a skill,
not module code (consistent with the module system rule: judgment stays in chat
dispatch, deterministic work in modules / routines). V1 adds one general
learning skill (or generalizes the `video-learning` skill into one) with
per-source branches:

| Source | Retrieval order | Pin |
|--------|-----------------|-----|
| X post | pinned X search bot (`grok-x`), then `y link fetch` | post id, author, post time, fetch time |
| Article | `y link fetch` on the canonical URL (tracking params removed), then `px` for context | URL, author, publish time (or "unverified"), fetch time |
| Repository | shallow clone / read README, docs, key code | commit SHA, license, fetch time |
| Video | `video-learning` skill: captions first, then local transcription | media id, duration, caption vs generated |

Depth is either `quick` (one-shot answer, short note) or `study` (verification,
full structure). An explicit depth in the request wins. Otherwise "学习" means
`study` and "总结 / 看看" means `quick` (decision 6).

### Note contract

Notes go in `pages/learn-<todo_id>-<slug>.md`. Front matter (keys in English):

```yaml
type: learning
title: <one line, plain text, same as the report H1>
todo: <todo_id>
depth: quick | study
source_kind: post | article | repo | video | other
sources:            # one or more
  - url: <canonical url>
    author: <name or unknown>
    published_at: <ISO or "unverified">
    fetched_at: <ISO>
    pin: <commit sha | post id | media id | null>
    link_id: <y link id or null>
summary: <one line, Chinese by default: what the source says and why it matters>
verdict: adopt | try | skip | none
takeaways:
  - text: <one line>
    status: proposed | adopted | declined
    ref: <todo id / commit / content key or null>
artifacts: <assets/... directory or null>
entities: [<entity slug>]
tags: [learning, ...]
```

`title` is optional in the contract (added 2026-10-12). The learning skill
writes a nonblank, plain-text, single-line title for every new or touched note,
matching the report's H1, never derived from the filename or the summary. When
it is missing, the module shows the note's filename. Untouched legacy notes are
not backfilled.

`summary` is optional in the contract so that legacy notes stay valid, but the
learning skill always writes it (added 2026-10-12). Lint warns, without
failing, on an absent or blank `summary`. It is a plain one-line
description, not a copy of the 结论 section.

Body sections, in order: 结论 (verdict and the one-paragraph answer), 来源事实
(what the source says, with short quotes, verified vs unverified), 解读 (the
assistant's analysis: what is new vs restated, pushback), 对 Roy 的可执行项
(proposals with the cheapest trial), 来源 (links, pins, artifact paths, method).
A `quick` note may merge the middle sections but keeps the three-way separation
in its wording.

### Carriers reused, nothing new stored

- Todo: tagged `learning` (plus canonical topic tags), and is the trace.
- Note: registered and associated to the todo, and tagged `learning`.
- Link: each source URL gets a link carrier tagged `learning` and associated to the todo. A failed fetch still creates the carrier (3344 precedent).
- Entity: associate only when a matching entity already exists. Do not auto-create entities.
- Media / transcripts: `/Users/roy/luohy15/assets/transcript-<todo_id>/` (gitignored, local), referenced from `artifacts`. Downloaded media follows the `video-learning` skill's retention rule.
- The X account media feature (`media-management`) is unrelated: it archives Roy's own output, while Learning covers content Roy consumes.

### `learning` module V1

- UI-only panel plus a CLI group. The API reads notes and tags only through existing owner-bound host contract `note_*` / `tag_*` capabilities. No new tables, no migration.
- Index = notes tagged `learning`. Notes with `type: learning` front matter are "conforming"; the rest show as "legacy" using title and path only.
- Panel list row (added 2026-10-12): title (front-matter `title`, else the note filename); original source link (first source URL, opens externally; "+N" when there are more); tags; report note link (opens the note in the existing note reader); one-line `summary`; time (the study date, taken from the note's creation time; added 2026-10-12); plus source kind and verdict. Legacy and summary-less notes render the missing fields as absent, never as placeholders that look like data.
- Panel also has filters (source kind, tag, verdict, depth), text search over title / summary / author / URL, and an "Open takeaways" view.
- Detail view (module `detail` surface, added 2026-10-12): opened by clicking a row. It shows the header (title, summary, verdict, depth, study date), all sources with author / published / fetched / pin / link carrier, tags, takeaways with status and ref, the artifacts path, the linked todo, and an "Open report" action into the existing note reader. It is read-only and does not render the note body itself. A legacy note's detail shows only title, path, tags, and the report action.
- CLI: `y learning list [--kind --verdict --tag --search]` (rows include study date, source URL, tags, note path, summary), `y learning show <note>` (the detail record), `y learning takeaways [--status proposed]`, `y learning lint [--since]` (read-only report).
- Takeaway status changes are edits to note front matter, made by the agent or by Roy. V1 has no takeaway editor UI.

### Approved Scope Decisions

Roy approved all six recommended answers on 2026-10-11 (todo 3861):

1. V1 is the skill + note contract + read-only `learning` module over existing notes, with no new tables.
2. Quick answers also write a short note (`depth: quick`). Nothing ends up only in a chat.
3. Takeaway status tracking is in V1, stored as three front-matter states (proposed / adopted / declined), with no UI editor.
4. No backfill. Legacy notes stay as they are, and a note is made to conform only when it is next touched.
5. New notes use the filename `pages/learn-<todo_id>-<slug>.md`, replacing the mixed study- / research- / transcript- / bare names.
6. The default depth is `study` when Roy says "学习" and `quick` when he says "总结 / 看看".

## Testing Decisions

- Module tests (local, untracked, per project convention): the index includes exactly the notes tagged `learning`; list rows expose study date, source link, tags, note path, and summary, with absent fields absent for legacy notes; the detail record carries every front-matter field above; front matter parsing classifies conforming vs legacy; filters and search return the expected subsets; the open-takeaways view lists only `proposed`; lint flags each missing required field, association, and carrier (an absent or blank `summary` is a non-failing warning, a non-string or multiline `summary` is an error, and an absent `title` produces nothing), and never writes.
- Use fixture notes that mirror real shapes: one conforming note, one legacy note without front matter tags (shaped like `pages/git-knowledge-loop.md`), and one with takeaways in mixed states.
- Skill acceptance: run the workflow once per source kind on a real recent example, then check the produced note with `y learning lint`. The video run follows the `video-learning` skill.

## Out of Scope

- A generic knowledge base, spaced repetition, flashcards, or a reading queue.
- Bulk migration or rewriting of historical learning notes.
- New storage tables, embeddings, or semantic search.
- Automatic adoption of takeaways (config, code, or todo creation). Takeaways stay proposals until Roy acts.
- Automatic entity creation for authors and sources.
- Curriculum-style learning (1309 valuation basics, 3011 CFA, 3009 DCF, 1595 history). These are structured courses, not source studies. Revisit them separately if needed.
- Managing Roy's own published content (owned by [media-management](media-management.md)).
- Paid transcription, external media uploads, cookie use, and publication without per-task approval.
