# Create an agent in Agent Town

This guide tells how to change "I want an agent that…" into an agent that works. The agent is for
one person, and for their life or work. The guide has two readers:

- **You, a person.** Read [The short version](#the-short-version). That is all that you must do:
  your mayor does the rest.
- **An AI agent** that makes an agent for a person: the mayor in their town, or any assistant
  (Claude Code, ChatGPT, Codex) that writes the files for them. Do the steps in sequence.

The latest version is at `/api/guides/create-an-agent` on any Agent Town server.

---

## The short version

Talk to your **mayor** (press **M** on the map). Tell it what you want, as you tell a new
assistant about a job. Three or four sentences are sufficient:

> I want a gym trainer. Every day I'll tell it what I ate and what I lifted. It should keep a log,
> tell me if I'm on track for my protein and my lifts, and give me a plan for tomorrow each
> evening. I train 4 days a week at a commercial gym, and my goal is to put on muscle.

These items help the most:

- **The job.** What it does, in one sentence.
- **How often, and who starts it.** Does it start each time that you send it a message? Every
  morning at 7?
- **What you want back.** A plan, a draft, a log, a list, a summary. An example is best.
- **What it should know.** Your goals, your situation, and the files or apps that hold the
  information.
- **What it must never do on its own.** For example: send, post, buy, delete.

The mayor asks some questions and shows you the agent. When you press **Add**, the mayor adds it.
Then try the agent. Tell the mayor about each error that it makes, or edit its **📜 Desk**.

Do you want to write it yourself, or with a different AI? Make the folder that
[Step 4](#step-4-write-agentmd) tells about, and drop it on **+ Add agents**.

---

## Step 1: Understand what they want

Before you write anything, find out what the agent is for. If the conversation already tells you,
get it from there and ask them to confirm it. Do not make them say it again. If not, ask some
questions at a time, in conversation, not as a form. Stop when you can fill in the card below.

These questions are usually important:

1. What must it do, and how will "it's working" look a week from now?
2. When does it work: when they send it a message, on a schedule, or when an email arrives?
3. What do they give it each time (a meal, a link, a transcript, nothing), and what must it give
   back?
4. What must it know about them that does not change frequently (goals, constraints, preferences)?
5. What must it remember from one chat to the next?
6. Which apps hold the information (Gmail, Calendar, Notion, GitHub…)?
7. What must it never do before it asks?

Then write the **design card**. Show it to them in simple words:

| | Gym trainer (example) |
|---|---|
| **Job** | Logs food and workouts; plans each training day |
| **Starts when** | They message it; a routine each evening at 9 for tomorrow's plan |
| **Input** | "Lunch: chicken rice bowl", "Bench 3×8 @ 60 kg" |
| **Output** | Log confirmed in one line; daily totals vs targets; tomorrow's plan as a table |
| **Knows (files)** | `program.md`: their split and progression rules; `foods.md`: meals they eat often, with macros |
| **Asks once (`ask:`)** | Goal and timeline · Training days and equipment · Injuries or foods to avoid |
| **Remembers (notes)** | Last 14 days of food and lifts, current working weights, personal bests |
| **Apps** | None needed. Optional: Notion for a long-term log |
| **Never** | Medical or injury diagnosis; diets under a safe minimum |

## Step 2: Check it fits what agents can do

Make the design agree with how agents run in Agent Town. If not, the agent will promise things
that it cannot do:

- **Each chat is a fresh start.** It wakes up in a private sandbox, does the work, and goes back to
  sleep. Between chats it keeps only these items:
  - **its notes** (`.agent-town/memory.md`, up to 20,000 characters). It writes them and reads
    them in the next chat. The person sees them in its **📓 Diary**.
  - **`about-me.md`**: what the person told it about themselves.
  - **its last few chats** (`.agent-town/recent-chats.md`, read-only).

  It does not keep other things that it writes. **An agent that logs or tracks must tell what goes
  in its notes and how to keep them short**: one short line for each day, and a weekly summary for
  older days. For a log that must last for years, connect an app (Notion, a database) and tell the
  agent to write there.
- **It can start on its own** only through a **routine**: on a schedule ("weekdays at 8"), or when
  an email arrives from a person that they wrote to. The person sets routines on
  **Today → Routines**. The agent cannot make a schedule for itself. Thus the instructions tell it
  what to do when the message of the routine arrives.
- **It knows what is in its files**: markdown or text, up to 50 files of 200,000 characters. Put
  reference material there (a program, a menu, a style guide, examples), not in the instructions.
- **It uses the apps that the person connected and ticked in its house → 🛠️ Tools.** You cannot
  connect apps for them. Tell them which apps to connect.
- **It cannot yet:** react to webhooks or Slack messages, browse websites or use desktop apps, read
  images or PDFs as knowledge, or search all past chats.

If the job needs one of these, make the agent **draft and hand back**: "write the email", not
"send it", and "here's the plan, paste it into your calendar", not "book it".

The full list is in AGENTS.md (Part 1) of the Agent Town repository.

## Step 3: One agent, or a team?

**Start with one agent.** Split the work only when the jobs are really different: different apps,
different schedules, different voices. A **colony** is a team: a lead that the person talks to, and
the agents that the lead hands work to (one level deep, Claude only). For example, "Fitness" can be
a lead coach with a nutrition agent and a programming agent. But one trainer agent does the job
better, until it does not.

Before you make it, examine the agents that they already have (`list_agents`). Change an agent that
they have. Do not add an almost identical copy.

## Step 4: Write AGENT.md

An agent is a folder:

```
gym-trainer/
  AGENT.md        frontmatter + instructions (required)
  program.md      what it knows (optional, any number of .md / .txt files, sub-folders fine)
```

### The frontmatter

```markdown
---
name: gym-trainer
description: Logs your food and workouts, tracks progress, and plans each training day.
color: #d2553f
building: forge
tools: notion
ask: What's your goal, and by when? | Which days do you train, and with what equipment? | Any injuries, or foods you avoid?
---
```

- **`name`**: lowercase-with-hyphens (`gym-trainer`), or a first name (`rex`).
- **`description`**: one line, under 200 characters: what it does and when to use it. Their mayor
  and its lead read it to decide when to send work to it. Thus, name the real things that it does.
- **`ask:`**: two to four questions, split by `|`. It asks them in its first chat and keeps them in
  `about-me.md`. Use only questions whose answers change what it does. Do not ask for their name,
  role, company or writing voice. These are in `about-us.md`, which all their agents share.
- **`tools:`**: the apps that it works best with. This is a suggestion: the person gives the access.
  `agent-town` gives it the tools to propose new agents.
- **`building:`** (studio, office, forge, library, lab, observatory, tavern, cottage, tower) and
  **`color:`** set its house and its outfit on the map.

Do not include `model:` or a Claude Code-style `tools:` list. The person selects its brain and its
apps in the app.

### The instructions

Write **30–80 lines**. Use this structure, and remove each section that it does not need:

```markdown
# Gym trainer

One or two lines: who it is, who it works for, and what it's for.

## Before you start
What to read first: about-me.md, its notes, the files that matter.

## How you work
Numbered steps for each kind of message it gets: "When they log food…", "When the evening routine runs…".

## What your answer looks like
A template or a short real example. Not adjectives.

## What you keep in your notes
What to write down after each chat, in what format, and when to roll old entries up.

## Always / Ask first / Never
The limits, each with a reason.
```

How to write it well (the guides from Anthropic and GitHub agree on these points):

- **A job, not a persona.** "You are a helpful assistant" does nothing. "You log Sam's meals and
  lifts and plan each training day" does.
- **Show, do not describe.** One example answer is better than a paragraph of "be concise, friendly
  and clear". If the format is important, give the template.
- **Use the correct level of detail.** Do not write a rigid if-this-then-that script. Do not write
  vague advice that assumes that it knows the person. Give it the steps and the reasons, and let it
  use its judgment.
- **Say why.** The agent obeys "Keep the reply to three lines: they log from the gym floor, on a
  phone" better than "ALWAYS BE BRIEF". It also applies the rule better to new cases.
- **Assume that it is smart.** Do not tell it what all capable models already know (what protein
  is, how to write an email). Use the lines for what is specific to this person.
- **Name what is missing.** When a file or an answer that it needs is not there, tell it to say
  what it needs. It must not guess.
- **Honest by default.** It never invents numbers, facts, sources or results. It says when it is
  not sure. For estimates (calories in a meal), it says that they are estimates.
- **Safe by default.** For each action that sends, posts, pays, deletes or changes the data of a
  different person: draft it and ask first.

### Never put in an agent

- Passwords, API keys or tokens. The agent gets access when the person connects apps.
- Instructions to deceive, spam, impersonate, watch other people, or bypass security.
- Instructions to say that it did something that it did not do.

## Step 5: Give it what it needs

- **Files** go in its house (**📚 Bookshelf → + put a book on the shelf**). If all agents must
  know them, they go in **Shared files**. Examples: a training program, a list of usual meals with
  macros, a reading list, examples of good output from the past.
- **Their profile** (`about-us.md`, under their name → **About you and your company**) holds what
  all their agents must know. If it is empty, ask them to fill it in.
- **Apps**: **Connect apps**, then the agent's house → **🛠️ Tools** → tick the app.
- **Skills**: you can put a playbook for one type of task in `skills/<name>/SKILL.md`, with its
  files. It loads only when the agent needs it. This keeps the instructions short.

## Step 6: Make it run on its own (optional)

If it must work when no person asks it, suggest a routine. Tell the person to add it on
**Today → Routines → + New routine**: **Who does it** (the agent), **What to do** (write it as a
message: "Plan tomorrow's training and meals"), **When** (days and a time). The instructions of the
agent tell it what to do with that message.

## Step 7: Test it, then tune it

An agent is never correct the first time. Tell the person to try it with these messages:

1. **Three realistic messages**: the messages that they will really send it on a usual day.
2. **One awkward one**: a message with missing information, a message with two meanings, or a
   message outside its job ("my knee hurts").
3. **A second chat**, to make sure that it remembered what it must remember.

Read what it did, not only what it answered. Its **📓 Diary** shows what it wrote down. For each
error, add the missing rule, reason or example to its **📜 Desk**, and add nothing more. Start
simple. Add detail only where it makes errors. Changes apply from its next chat.

---

## Example: a gym trainer

```markdown
---
name: gym-trainer
description: Logs your food and workouts, tracks progress against your goals, and plans each training day.
color: #d2553f
building: forge
ask: What's your goal, and by when? | Which days do you train, and with what equipment? | Any injuries, or foods you avoid?
---

# Gym trainer

You are their personal trainer and food log. They message you from the gym floor or the kitchen,
usually on a phone: keep replies short.

## Before you start

Read about-me.md (their goal, schedule, equipment, limits) and your notes (the log). Read
program.md for their training split and how to progress, and foods.md for meals they eat often.
If about-me.md has no goal yet, ask for one before planning anything.

## How you work

- **They log food** ("lunch: chicken rice bowl"): estimate calories and protein (use foods.md when
  the meal is there), add it to today's line in your notes, and reply in one line: what you logged,
  and the day's total vs target.
- **They log a workout** ("bench 3×8 @ 60kg"): record it; if it's a personal best, say so. If they
  hit every rep at a weight twice in a row, the next session goes up (program.md says by how much).
- **The evening routine runs** ("plan tomorrow"): if tomorrow is a training day, give the session
  as a table (exercise, sets × reps, weight) using their latest weights; then the food target, and
  one thing to fix from today.
- **"How am I doing?"**: the last 7 days vs the 7 before: average calories and protein, sessions
  done, lifts that went up or stalled. Three to five lines.

## Your notes

Keep the log compact, one line a day:
`Oct 23 | 2,450 kcal · 160 g protein | Push: bench 3×8 @ 60, OHP 3×8 @ 35`
Keep the last 14 days as lines. Roll older weeks into one summary line each. Keep a short
"Current weights" and "Personal bests" list at the top.

## Always / Ask first / Never

- Always say calorie and protein figures are estimates.
- Ask before changing their program or targets; propose the change and why.
- Never diagnose pain or injury: tell them to stop that exercise and see a professional.
- Never plan under 1,500 kcal a day, or a loss faster than about 1% of body weight a week.
```

It also has `program.md` (their split, rep ranges, how to progress) and `foods.md` (their usual
meals with calories and protein) on its bookshelf. And it has a routine
**every day at 21:00: "Plan tomorrow"**.

## Example: a curiosity agent

```markdown
---
name: curio
description: Feeds your curiosity: one surprising idea a day from the topics you love, and deep answers to any "why?" you ask.
color: #7a5bd2
building: observatory
ask: Which topics pull you in? | How deep do you like to go: a quick fact, or a long read? | Anything you've already read a lot about?
---

# Curio

You are their curiosity companion. You make them a little more fascinated by the world each day,
without being a lecture.

## Before you start

Read about-me.md (their topics and how deep they like to go) and your notes (what you've already
shared, and what caught their interest).

## How you work

- **The morning routine runs** ("today's idea"): pick one surprising, true idea from their topics
  that you haven't shared before, or from a topic next door to one they liked. Write it as below.
- **They ask a "why" or "how" question**: answer at the depth they like, from first principles,
  with one concrete example. End with the next question worth asking.
- **They say "more"** or ask a follow-up: go one level deeper, and log the topic as a favourite.
- **They say "meh"**: log it, and steer away from that topic for a while.

## What your answer looks like

**[A one-line hook, as a question or a surprise]**
Three to six short paragraphs: the idea, why it's true, an example you can picture.
*Go deeper:* one book, paper or search term, only if you're sure it exists.
*Next question:* one line.

## Your notes

- **Shared**: one line each: date, topic, the idea in five words. Drop entries older than a year.
- **Favourites** and **Not for them**: topics, kept short.

## Always / Ask first / Never

- Always separate what's established from what's debated or speculative.
- Never invent a source, quote, study or number. If you're not sure it exists, don't cite it.
```

It also has a routine **every day at 7:30: "Today's idea"**.

---

## Checklist before you propose it

- [ ] They agreed to the design card (job, when, input, output, memory, apps, limits).
- [ ] It is not a copy of an agent that they already have.
- [ ] `description` says what it does and when to use it, in one line.
- [ ] The instructions are 30–80 lines. They have steps, an output template, and what to keep in
  its notes.
- [ ] It has two to four `ask:` questions, and `about-us.md` does not already have them.
- [ ] Each action that sends, posts, pays or deletes waits until they say yes.
- [ ] It does not invent facts. It says when it estimates.
- [ ] Nothing that it needs is in the "cannot yet" list. If something is in that list, the agent
  drafts and hands back.
- [ ] You told them the files to add, the apps to connect, and the routine to set.
- [ ] It has no secrets, and no personal details of other persons.

## Where this comes from

The rules of Agent Town (AGENTS.md), and the best published advice about how to write agents,
changed for personal agents:
[Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents),
[Anthropic: Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents),
[Claude: Agent Skills best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices),
[Claude Code: subagents](https://code.claude.com/docs/en/sub-agents),
[Anthropic's skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator),
and [GitHub: How to write a great agents.md](https://github.blog/ai-and-ml/github-copilot/how-to-write-a-great-agents-md-lessons-from-over-2500-repositories/).
