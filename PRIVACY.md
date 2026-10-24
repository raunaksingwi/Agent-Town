# Privacy Policy

**Effective:** 16 October 2026

This policy applies to the hosted Agent Town service. Rushabh Singwi ("we", "us") runs this service.

**Contact:** rushabh@ravi.id

## The short version

- We store what you put into Agent Town (your account, your agents, their files, your chats). We
  store it so that the service can work. That is all: no ads, no sale of data, no analytics
  trackers.
- Your agents run on **your own** AI account (Claude or ChatGPT, by API key or subscription). What
  you say to an agent goes to that provider under **your** agreement with them.
- We encrypt the keys and tokens that you give us. We never show them back to you. We give them
  only to the sandbox of your own agent while it runs.
- Everything is private unless you select **Share publicly**.

## What we collect, and why

| What | Why | Stored as |
|---|---|---|
| **Email address, username, password** | To create your account and sign you in | Password: a one-way hash (argon2id); we never know it |
| **Sign-in sessions and API tokens** | To keep you signed in, and to let your scripts use the API | Only a one-way hash of each token |
| **Your AI account keys or subscription tokens** (Anthropic, OpenAI) | So your agents can think, on your account | Encrypted; never returned by the API |
| **App connections** (for example a GitHub token, or an app's server address) and their credentials | So agents you allow can use those apps | Credentials encrypted; never returned by the API |
| **Your agents**: their instructions, files, "about you" answers, team and settings; your shared files | That's what an agent is | As you wrote them |
| **Chats with your agents**: your messages, the agent's replies, and the tool calls and results it made | To show you the conversation, and to continue it | As text, until you delete the agent |
| **Chats with the caretaker** (the "?" helper): your messages, its replies, and what it changed, so you can undo it | To show you the conversation, continue it, and undo its changes | As text, until you delete your account |
| **What your agents remember**: the notes each one keeps between chats | So an agent can pick up where you left off; you can read, edit or wipe them in its house | As text, until you wipe them or delete the agent; never shared |
| **What you share publicly**: agents or files, a note, your username | So others can see what you chose to share | As text, visible to everyone |
| **Technical logs**: IP address, time, request path, errors | To keep the service running and secure | In our hosting provider's logs, kept for a limited time |

We do not use advertising, tracking pixels or third-party analytics.

**Cookies and browser storage:** one cookie keeps you signed in (`agenttown_session`: HttpOnly,
scripts cannot read it, and it goes only to us). A short-lived cookie guards each app sign-in while
it is in progress (`agenttown_oauth`, `agenttown_mcp_oauth`). Your browser also keeps some things on
your own device: your map style (`agenttown.theme`, which your account also keeps when you are
signed in), whether you put off the "tell your team about you" nudge, and, for one tab, which agent
setup to return to after you connect an app. That is all.

## Who else handles your data

We use a small number of providers to run the service. Each provider gets only what it needs:

- **Render** hosts the app and its database, in the United States.
- **Modal** runs the sandbox of each agent while you chat with it. For that run only, the sandbox
  gets the instructions and files of the agent, your "about you" answers, its notes and what was
  said in its last few chats, the team of the agent, and the credentials that it needs (your AI key
  or token, and tokens for the apps that you permitted). The sandbox is deleted when the chat ends.
  If your Claude is a subscription, the caretaker (the "?" helper) also runs in a sandbox of this
  type. It gets your subscription token, the description of your town (see below) and its recent
  conversation with you, and nothing else.
- **Anthropic or OpenAI**, the one that you select: your agent sends your messages, its
  instructions and files, and tool results to them, **with your own account**. Your agreement with
  them sets how they handle that data. The caretaker (the "?" helper) uses your own Claude (API key
  or subscription) in the same way. It sends Anthropic your message, a description of your town (the
  names, descriptions, colonies and connected app names of your agents, and where buildings stand,
  but no keys, files or chats with your agents) and its earlier conversation with you.
- **Apps you connect** (for example GitHub): when your agent uses them, it reads from them and
  writes to them, with the access that you gave.
- **Your browser's push service** (Google for Chrome and Android, Apple for Safari and iPhone,
  Mozilla for Firefox), only if you turn on notifications. We store the address that your device
  gave us for its notifications. Each notification is encrypted for your device, so the push
  service cannot read it. A notification says who and what ("Maya: your morning brief is ready",
  "Maya wants to send an email to sam@example.com"), never the text of an email. To stop them, turn
  notifications off, or sign in as a different person on that device.

We do not sell or rent your data. We do not share it with anyone else unless the law requires it.
If that happens, we will tell you when we are permitted to.

## Google data

If you connect Gmail or Google Calendar:

- Agent Town's use and transfer of information received from Google APIs will adhere to the
  [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy),
  including the Limited Use requirements.
- **What we ask for:** to read your email, to write drafts and send them, and to read and add
  calendar events. Agents never invite people to calendar events.
- **When email goes out:** by default, only when you press **Send** on it. You can give an agent
  rules instead (for example "send on its own to people I've emailed before"). Our server checks
  those rules, not the agent. An email that is permitted out in this way waits 2 minutes, so that
  you can cancel it. At most 10 emails a day go out on their own. To find out if you have emailed a
  person before, our server examines the email index (see below). If the index does not show the
  person, it searches your Sent Mail at that moment.
- **The email index ("Remember who I email"):** on, unless you turn it off under Connect apps. For
  the last 90 days of your Gmail (not Promotions, Social, Updates or Forums), we keep who each email
  was from and to, when it was sent, which thread it belongs to, and its subject. We keep this
  encrypted. We never keep what emails say. We use the index to show on Today the email that waits
  for you, to let your agents find people and find threads that need a reply, and to start routines
  that you set to run when email arrives. When you turn it off, we delete it at once. We also
  delete it when you disconnect the account or delete your Agent Town account. We delete each
  entry when it becomes older than 90 days.
- **Where it goes:** your Google tokens stay encrypted on our server. They never go into the
  sandbox of an agent. When an agent that you permitted uses Gmail or Calendar, our server makes
  the call. Our server passes the result (for example the text of an email) to the chat of that
  agent. That chat goes to your AI provider, as described above.
- Your agents use that data only to do what you ask them to do in Agent Town.
- We do not use it for advertising. We do not sell it. We do not let people read it, except with
  your consent or for security or legal reasons. We do not use it to train AI models.
- **Disconnect any time** under Connect apps: we revoke access at Google, and we delete the tokens
  that we stored and the email index. When you delete your account, we do the same.

## LinkedIn data

If you connect LinkedIn:

- **What we ask for:** your name, email address and photo (to show which account is connected), and
  permission to post as you. We cannot read your feed, connections or messages, and we do not ask
  to.
- **When a post goes out:** as soon as an agent that you permitted writes it, unless you set that
  agent to ask you first. After 5 posts in a day from your agents, it asks you in all cases. We keep
  the text and link of the post with that chat, so that you can see what was posted.
- **Where it goes:** your LinkedIn token stays encrypted on our server. It never goes into the
  sandbox of an agent. Our server makes the call.
- **Disconnect any time** under Connect apps: we revoke access at LinkedIn and delete the token.
  The token also stops working on its own after 60 days. This is the limit that LinkedIn sets.

## How long we keep it

- **Agents, files, chats and connections:** until you delete them. When you delete an agent, that
  deletes its files and its chat history.
- **Keys, tokens and connections:** until you remove them in the app.
- **Your account:** until you delete it (see below). That deletes your account and everything in it
  immediately.
- **Backups and logs:** deleted data can stay in backups and hosting logs for a limited time. Then
  it is gone.

## Your choices and rights

- **See and change** your agents, files, connections and keys in the app at any time.
- **Delete** any agent, file, key, token or connection in the app.
- **Delete your account** yourself: your @username (top right) → **Account** → **Delete my account**.
  This deletes your agents, files, chats, keys, app connections, tokens and public shares at once.
  It also stops each agent that runs at that time. If you cannot sign in, send us an email from the
  address on your account.
- **Get a copy** of your data, or ask us to correct it: send us an email.
- Depending on where you live (for example under the GDPR in the EU and UK, or in California), you
  may have more rights, such as the right to object to or restrict how we use your data. Send us an
  email to use them. You can also complain to your local data protection authority.

## Security

Passwords and tokens are hashed. Keys and app credentials are encrypted at rest. We check every
request against the signed-in account, so that nobody can reach the agents, files or chats of a
different person. Agents run in isolated sandboxes, which are deleted after each chat. No system is
fully secure. For this reason, do not put secrets that you cannot rotate into the files of an
agent.

## Children

Agent Town is not for children. Do not use it if you are under 16 (or the age of digital consent
where you live).

## Changes

If we change this policy, we will update the date above. For significant changes, we will tell you
in the app or by email before they take effect.
