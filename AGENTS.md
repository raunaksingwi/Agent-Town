# AGENTS.md

This guide is for AI agents (Claude Code, Codex, Cursor and others) that read this repository.

- **To write an agent for Agent Town** (for a user, or for the market): read
  [Part 1](#part-1-agents-for-agent-town).
- **To design an agent for one person** from what they describe ("a trainer that logs my meals"):
  follow [create-an-agent.md](agents/mayor/skills/agent-builder/create-an-agent.md). Agent Town
  also serves it at `/api/guides/create-an-agent`.
- **To change the code of Agent Town**: read [Part 2](#part-2-working-on-this-codebase).

## Writing

Write all prose in ASD-STE100: messages to the user, documentation, README
files, code comments, commit messages, and pull request descriptions. Code,
identifiers, and quoted error text are not prose and stay as they are.

## Engineering philosophy

- **Remove, then change, then add.** For each goal, first try to remove
  code to reach it. If that is not possible, try to change the code that
  exists. Add new code only when the two other options fail, and add the
  smallest code that does the work. Apply the same order to documentation.

---

## Part 1: Agents for Agent Town

Agent Town is a place where people keep their personal AI agents. Each agent is a character in a
small town. It has its own house, files and chat. People chat with an agent. For each chat, the
agent wakes up in its own private sandbox, does the work, and goes back to sleep.

### What an agent is

An agent is a folder of markdown:

```
my-agent/
  AGENT.md        frontmatter + instructions (required)
  *.md, *.txt     what it knows: playbooks, checklists, examples, templates (optional, sub-folders fine)
```

`AGENT.md` uses the Claude Code agent format, with some extra keys for the market:

```markdown
---
name: my-agent                      # lowercase-with-hyphens; for the market, same as the folder
description: One line on what it does and when to use it.
tags: writing, productivity         # market only
author: github-username             # market only
color: #3f8fd2                      # optional: its roof and its character's outfit
building: library                   # optional: studio office forge library lab observatory tavern cottage tower
tools: gmail, github                # optional: apps it works best with (a suggestion; access is granted in the app,
                                    # except agent-town, Agent Town's own tools, which come with it)
team: research-assistant            # optional: other agents it hands work to
colony: Research                    # optional, for a lead: its colony's name…
about: Answers with sources         # …and what it's for
ask: What's your name? | What do you work on?   # optional: what it asks in its first chat
---

# My agent

Instructions…
```

Agent Town **ignores** the `tools:` field of Claude Code (a list such as `Read, Grep`) and the
`model:` field. In Agent Town, the owner selects in the app what an agent can use, which model it
thinks with, and how hard it thinks (its "brain").

### How an agent runs

When you know how an agent runs, you can write instructions that work:

- **The engine.** The agent runs on the AI account of its owner: **Claude Code** for Anthropic
  accounts, or **Codex** for OpenAI accounts, with an API key or a subscription. The body of
  `AGENT.md` becomes its system prompt.
- **Its working directory** holds these files, at the same paths as in the folder:
  - its own files.
  - the **shared files** of the owner (knowledge that all their agents read). These include
    **`about-us.md`**: the profile of the owner (who they are, the company, goals, team, voice, what
    needs their yes). Agent Town asks for this profile one time, for all their agents.
  - **`about-me.md`**: what the owner told this agent only. Until this file exists, the first chat
    tells the agent to get to know the owner. The agent asks its `ask:` questions in the
    conversation and writes the answers in this file. The agent can update this file in any chat,
    and Agent Town keeps it.
  - **`public/<owner>/…`**: things that other people shared, if the owner permits it.
  - **`team/<name>/…`**: the files of each teammate.

  The prompt also lists these files. Tell the agent which files to read ("Before you write, read
  `style-guide.md`").
- **Its tools:**
  - it can read, write and search files in its working directory.
  - a shell, **only in the cloud sandbox**.
  - the **apps that its owner permitted** (MCP tools: Notion, Linear, GitHub, a database, and
    others). A connected web API shows as one tool, `get`. Tell the agent which paths to read ("GET
    /dashboard for signups").
  - the **Task** tool, to hand work to its team. Claude only, one level deep (a teammate cannot have
    its own team).
  - **mail**, if the agent is the lead of a colony or an agent on its own: `list_colonies`,
    `send_message` to another colony, `ask_person` / `tell_person` for the mailbox of the owner on
    Today, and `finish_thread`. Mail arrives as a new message with the thread so far. Only what is
    written is shared.
- **Each chat is one run.** The conversation continues across messages until the chat ends. The chat
  ends when the owner ends it, after 15 minutes of silence, or after 4 hours at most.
- **It remembers through two files** in `.agent-town/`. Its prompt describes both files. No agent
  file can clash with them, because file paths cannot start with `.`:
  - **`.agent-town/memory.md`**: its own notes. Agent Town saves what the agent writes there after
    each turn and gives it to the next chat (20,000 characters at most). The owner can read, edit or
    erase it (the Diary in its house), also during a chat. The edit of the owner wins, and Agent
    Town tells the agent to read the file again. The file is never shared.
  - **`.agent-town/recent-chats.md`**: what was said in its last few chats (words only, newest
    first). Read-only.

  Agent Town tells every agent this already, so you do not have to. If your agent must always write
  some things down (the preferences of a client, open tasks), say so.
- **Agent Town keeps nothing else that the agent writes** after the chat ends, except `about-me.md`.
  Agent Town writes its files and the shared files again into each run. Reference knowledge belongs
  in its files.

### What it supports

| Supported | Not yet |
|---|---|
| Chat-driven work: a person asks, the agent does the work, and it answers | |
| Routines: the job of the owner for it on a schedule ("weekdays at 8"), or when email arrives from a person they have written to | Reaction to other events (a webhook, a Slack message) |
| Drafts, reviews, summaries, plans, research, analysis | |
| Use of the files it was given: playbooks, FAQs, checklists, examples | Files kept between chats (other than its notes) |
| Memory: its own notes, and its last few chats | Search of all its past chats |
| Apps that its owner connected and permitted: any MCP server that Claude or Codex can use (over HTTP with the sign-in or headers of the app, a command that runs in the sandbox with its environment, or pasted from a `.mcp.json` / Codex `config.toml`), or a read-only web API that Agent Town calls with a key that the agent never sees | Slack sign-in (soon), browsers or desktop apps |
| LinkedIn: `get_profile` (name, email, photo) and `create_post` (posts as its owner immediately, or after they press Post if they set it to ask), on servers with a LinkedIn app | Read of the LinkedIn feed, connections or messages (LinkedIn does not permit apps to do this) |
| Gmail (search, read, draft, and send: **when its owner presses Send**, or on its own if the owner gave it rules, such as "to people I have emailed before". Agent Town checks the rules) and Google Calendar (list, add events, no invites), on servers with a Google client. Also `find_people` and `open_loops`: who the owner emails and which threads wait for a reply, from the index of Agent Town (last 90 days, no email text) | Calendar invitations, search of the text of all their mail |
| A team: a lead that hands work to other agents (Claude). On the map and in the app, a team is a **colony**, with a name and a purpose. A colony can also be one agent on its own | Teams with more than one level, teams on Codex |
| Colonies that write to each other by mail (lead to lead, Claude and Codex alike), and that ask their owner in their mailbox. A new request waits for the **mayor**. The mayor looks every 30 minutes and wakes the colonies that are worth working on now. A loop guard pauses a thread that runs too long, costs too much or goes back and forth, and asks the owner | Live calls between agents (mail gets an answer in a later turn), a message to a team member directly |
| Agent Town itself (`tools: agent-town`): `list_agents`, and `create_agent` / `create_colony`. These two propose an agent or a colony, and Agent Town adds it **when its owner presses Add** | Changes to agents, deletion of agents, the grant of apps |
| Markdown and text files, up to 200,000 characters each, 50 per agent | Images, PDFs, spreadsheets as knowledge files |
| Skills: `skills/<name>/SKILL.md` among its files (or the shared files of the owner) load as Claude Code / Codex skills | Skills with scripts or other files that are not text |

If a job needs an item in the right-hand column, design the agent to **draft and hand back**
instead. For example, "write the email", not "send it every morning".

### What makes a good Agent Town agent

1. **One clear job.** The name and the description say what it is for, so that a person can select
   it from the market at a glance.
2. **A process and an output format.** The steps it follows and what its answer looks like. A
   template is better than adjectives.
3. **It uses what it is given.** It reads `about-me.md` and its files before it does the work, and
   it says when something it needs is missing.
4. **Safe by default.** For each action that sends, posts, pays, deletes or changes data: draft it
   and ask first. Say so in the instructions.
5. **Honest.** It never invents facts, numbers, sources, quotes or results, and it says when it is
   not sure.
6. **Short.** Usually 30–80 lines of instructions. Long reference material goes in its own file.
7. **Useful `ask:` questions.** Two to four questions whose answers change what it does: which
   emails are important, the brand voice, the main data table. Not trivia, and not what
   `about-us.md` already asks (their name, role, company, goals, team, writing voice, what needs
   their yes).

Good fits: a code reviewer, inbox triage (drafts only), meeting notes, a standup writer, a research
assistant, a data analyst (read-only), support replies, social posts, a chief of staff that leads a
team. See [`agents/`](agents/) for examples that work.

### Never

- **Secrets in the files of an agent:** API keys, tokens, passwords. Access comes from connected
  apps.
- **Personal data in market agents:** real emails, phone numbers, names, home paths. Use
  `example.com`.
- **Agents made to deceive or do harm:** impersonation, spam, phishing or collection of credentials,
  surveillance of people, evasion of security, harassment.
- **Pretense:** instructions that make it say that it sent, posted or did something that it did not
  do.

### Adding an agent to the market

Put it in `agents/<name>/`, add it to the table in [`agents/README.md`](agents/README.md), run
`cd backend && uv run pytest tests/test_marketplace.py`, and open a pull request. The full rules are
in [agents/README.md](agents/README.md#adding-an-agent-to-the-market).

---

## Part 2: Working on this codebase

- **Layout:**
  - `backend/` is the FastAPI API (`app/`), the sandbox runner (`runner/runner.py`: standard library
    only), the migrations (`alembic/`) and the tests.
  - `frontend/` is React plus a canvas game map (`src/city/`).
  - `agents/` is the market.
  - `CARETAKER.md` is the guide to each screen and button. The caretaker (the "?" helper,
    `backend/app/caretaker.py`) reads it. **When you change what the app shows, update this file
    too.**
  - The [README](README.md) has the full map and tells you how to run everything.
- **Before you finish:**
  - `cd backend && uv run pytest && uv run ruff check app runner tests`
  - `cd frontend && npm run build && npx oxlint src`

  CI runs the same checks on each pull request.
- **New endpoint:** scope each query to the signed-in user, and show this with a test in the style
  of `tests/test_isolation.py`.
- **UI change:** examine it in all three looks (Retro, Fantasy, Office), in the Standard view if it
  shows there, and at phone width.
- **Database changes:** add a migration
  (`cd backend && uv run alembic revision --autogenerate -m "…"`), read it, and give new non-null
  columns a `server_default`.
- **Privacy is the primary rule:**
  - each query is scoped to the signed-in user.
  - the things of another user return **404**.
  - keys and tokens are encrypted at rest, and the API never returns them.
  - the manifest that a sandbox gets holds no secrets. Credentials only travel through
    `/api/runtime/setup` (and `/api/runtime/secrets`, which refreshes app sign-ins between turns),
    with the token of the run.
  - **Known limit:** in its own sandbox, an agent can read what it was given (the model key of its
    owner, the headers of the apps it can use), and on Modal it has a shell. Text that it reads (an
    email, a web page, the public file of a person) could tell it to leak them. The mitigations are
    the taint on such runs (`Run.untrusted`: no sending or posting on its own), the Add/Send/Post
    clicks of the owner, hosted apps whose tokens never leave the server, and file paths that cannot
    climb out of their folder. Think about this before you widen what a sandbox gets.
- **This is a private repository**, but treat it as if it could become public: never commit secrets,
  `.env` files, databases or the personal data of a person. Test data is invented (`@example.com`).
- **Style:** match the code around you. Short functions, plain names, comments that say *why*. Keep
  the words that users see plain: "apps", not "MCP tools".
