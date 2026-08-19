# Devpost submission draft — CoS

> **Working draft, not final copy.** Things to check/update before actually submitting:
> - The "How we built it" section below is written assuming the Bedrock model swap + AgentCore Runtime deployment (Phases B/C) are done by submission. If AWS approval doesn't clear in time, soften those claims to "built and tested against a mocked deployment, live migration in progress" — the honest version is still a strong technical story, don't oversell.
> - Swap in the real YouTube/Vimeo video link, GitHub repo link, and live demo link (all currently `[PLACEHOLDER]`).
> - Confirm AWS Builder ID is on hand for the submission form.
> - Written here as a solo entrant ("I built..."). Change to "we" if this ends up a Team submission.
> - Track: **Everyday Agents**.

---

## Elevator pitch (one-liner / gallery tagline)

CoS is a Telegram agent that turns "we should really deal with that" into a tracked, owned, followed-up task — so no partner has to be the household's only rememberer.

---

## Text description (features & functionality)

CoS is a household chief-of-staff that lives inside a shared Telegram group chat between two partners. It listens for the loose, half-finished way household tasks actually get mentioned — "we need to book Mia's dentist appointment," "someone should renew the passport" — and turns them into tracked, owned, followed-up items, without either partner having to open an app or fill out a form.

**What it does:**
- **Capture** — turns a natural mention in the group chat into a structured task automatically, no slash commands or forms.
- **Delegation** — asks who's taking it via inline buttons (one tap per partner, or "Split — let's talk"). Once assigned, CoS owns the follow-up, not the person who mentioned it.
- **Two ways to close a task** — tap "Done" on a nudge, or just say so in chat ("I bought milk") and CoS matches it against the open list and closes it out.
- **Daily nudges** — reminds the owner of tasks due soon, posted in the group and addressed to them by name, once a day at most per task.
- **On-demand queries** — ask CoS what's open any time ("what should I get from the market") and get a straight answer.
- **Weekly fairness stats** — a neutral, no-blame summary of who captured what and who completed what, and how many tasks got resolved without CoS ever having to nag. Visibility without guilt.
- **A reliability safety net** — CoS runs on a smaller, cheaper model for cost, which occasionally does the work but forgets to actually send the reply. A hook-based tracker catches that pattern and retries automatically, so a real answer never silently vanishes.

Under the hood, one Strands Agent handles all of this through a small set of purpose-built tools (task tracking, Telegram messaging, a calendar hook reserved for real Google Calendar integration next). This isn't a demo wired up just for the video — it's been running daily against a real household's real Telegram group since the first days of the build, and stayed running through every feature added since.

---

## Inspiration

Household task-tracking usually collapses onto whoever happens to remember first — and that person quietly becomes the default project manager for the relationship. Shared to-do apps don't fix this because they require someone to open them; group chats are where couples actually talk, but nothing in a group chat *tracks* anything. CoS started from a simple question: what if the chat itself could remember, assign, and follow up, instead of leaving that invisible labor to one partner?

## What it does

See "Text description" above — capture, delegation, two completion paths, daily nudges, on-demand queries, and a weekly no-blame fairness summary, all inside the Telegram group a couple already uses.

## How we built it

CoS is a single Strands Agent (Strands Agents SDK) with a small, single-purpose toolset — `task_store` for the task lifecycle, `telegram_tools` for the only two ways it's allowed to talk back (a plain message or a button-choice message), and a `calendar_tool` reserved for real Google Calendar wiring next. The system prompt, not a hardcoded state machine, drives all of the behavior above — capture, delegation, completion matching, nudging, and the weekly summary are all prompt-defined behaviors over the same small tool surface.

Two architecture decisions mattered more than they look:

1. **Amazon Bedrock AgentCore Runtime is a synchronous request/response service — it doesn't support a long-polling Telegram listener or scheduled background jobs.** So CoS splits into a thin, always-on **gateway** (Telegram polling + the daily/weekly schedulers — unchanged, ordinary long-running process) that invokes an **AgentCore-hosted "brain"** (the actual Strands Agent and its tool-calling loop) per message, over `boto3`.
2. **AgentCore's containers are ephemeral**, so the task database couldn't stay on local SQLite once the brain moved off the gateway process. Persistence sits behind a small backend interface — SQLite for local dev, DynamoDB for the deployed path — so the agent's tools never had to change to make that swap.

Claude runs via Amazon Bedrock; the model-invocation code is deliberately isolated to one small module so the model provider was never hardwired into the rest of the system.

## Challenges we ran into

- **AgentCore's request/response-only model** meant the original single-process design (one long-running bot doing everything) couldn't deploy as-is — see the gateway/brain split above.
- **Cost vs. reliability**: running a smaller, cheaper model to keep this affordable for daily real use surfaced a real bug — the model would do the work (fetch the right data) and then just... not send it, since its only way to actually reply is a tool call, and it sometimes skipped that step. Fixed with a hook-based tracker that detects "did work, never replied" and retries once, rather than either eating the cost of a bigger model or leaving real messages silently dropped.
- **Getting delegation right took real iteration**: the first live version leaked an internal "Partner 1 / Partner 2" role tag into the buttons users saw, and a stray "I'll take it" option that confused ownership. Both only surfaced once real people used it — fixed after two rounds of live testing, not caught by any test suite.
- **Keeping the weekly summary useful without turning it into a blame report** — the numbers have to be genuinely informative (who's carrying what) without becoming a scoreboard one partner can weaponize against the other.

## Accomplishments that we're proud of

- CoS isn't a demo — it's been running daily against a real household's real Telegram group and real task list since the earliest days of the build, not just switched on for the video.
- The full loop actually works end to end: capture → delegate → complete (two different ways) → nudge → weekly fairness stats — all live-tested, not just unit-tested.
- Built genuine reliability engineering in response to a real production bug (the silent-reply retry), not a hypothetical one.
- The persistence layer swap (SQLite → DynamoDB) and the agent-invocation split (in-process → AgentCore) both shipped without touching the agent's tool contract or system prompt — the abstraction actually held up under a real architecture change.

## What we learned

How Strands' tool-calling and hook system (`AfterToolCallEvent`) compose well for building genuine reliability behaviors, not just capabilities. How Bedrock AgentCore Runtime's synchronous, stateless model shapes the *whole* system design around it, not just the one component being deployed. And a very concrete lesson about cheaper models: they don't just answer worse, they sometimes fail in ways a bigger model simply wouldn't — silently dropping a reply is a failure mode that needs its own engineering, not just a prompt tweak.

## What's next for CoS

Real Google Calendar integration (the `calendar_tool` is wired into the prompt but still a stub) — cross-referencing seasonal/recurring tasks against an actual calendar is the most-requested missing piece from real usage. Beyond that: broader household support past two partners, and DM-based nudges as an opt-in alongside the group-chat nudges CoS uses today.

## Built with

Strands Agents SDK · Amazon Bedrock · Amazon Bedrock AgentCore Runtime · Amazon DynamoDB · Python · python-telegram-bot · Telegram Bot API · SQLite · pytest · moto · boto3

---

## Video pitch script (~5 minutes)

Voiceover + screen recording, no on-camera needed. Record the demo segment against the sanitized **demo household**, not the real one.

**[0:00–0:35] Hook / problem**
> *(Cold open on a messy group chat screenshot, or just voice-over)*
> "In a lot of households, task-tracking collapses onto whoever remembers first. One partner ends up being the one who remembers the dentist appointment, the passport renewal, the school form — not because they agreed to that job, but because forgetting first became a pattern. That's invisible labor, and it's a real source of relationship friction. This is CoS — an agent that takes that job instead of a person."

**[0:35–1:00] Who it's for / one-liner**
> "CoS lives inside a shared Telegram group chat between two partners. It's for any couple who already coordinates household stuff in a group chat — which is most couples — and wants that chat to actually remember things, not just hold the conversation."

**[1:00–3:30] Live demo — screen recording of the real Telegram flow**
> "Here's what that looks like." *(narrate over screen recording, roughly:)*
> - Post a task-shaped message → CoS captures it and asks who's taking it, one tap per partner.
> - Tap a name → confirmed, assigned, done.
> - Close a task two ways: tap "Done" on a nudge, or just mention it in chat — "I bought milk" — and CoS matches it and closes it out.
> - A daily nudge example, addressed to the owner by name, right in the group.
> - The weekly stats summary — neutral, no blame, just visibility into who's carrying what and how much got resolved without a single reminder.

**[3:30–4:20] How it's built**
> *(show the architecture diagram — docs/architecture.svg)*
> "Under the hood, this is one Strands Agent with a small toolset, deployed on Amazon Bedrock AgentCore Runtime. AgentCore only handles request/response, so the always-on parts — the Telegram listener and the daily/weekly schedulers — stay in a lightweight gateway process, which calls into the AgentCore-hosted agent per message. Task data lives in DynamoDB since AgentCore's containers are ephemeral. Claude runs via Amazon Bedrock."

**[4:20–4:50] Why it matters**
> "This isn't a hackathon demo that stops working the day judging ends — CoS has been running daily in a real household since the earliest days of the build. The goal isn't a smarter to-do list. It's making the mental load of running a household visible and shared, instead of quietly falling on one person by default."

**[4:50–5:00] Close**
> "CoS — for the household task that never had an owner. Thanks for watching."

---

## Submission checklist (from the official rules)

- [ ] Public GitHub repo, MIT/Apache LICENSE visible in the "About" section (done — `LICENSE` at repo root)
- [ ] README with setup instructions (done)
- [ ] Architecture diagram (done — `docs/architecture.svg`)
- [ ] Video ≤5 min, public on YouTube/Vimeo, demonstrates the working project + pitch covering problem/who/why
- [ ] Text description (this doc, condensed to fit Devpost's actual field)
- [ ] AWS Builder ID entered on the submission form
- [ ] Track selected: Everyday Agents
- [ ] (Optional, strengthens score) live demo link — e.g. an invite to the demo Telegram group with the gateway running against the deployed AgentCore backend
- [ ] (Optional, up to +0.6 score) builder.aws blog post(s), title referencing "Agents for Humans"
