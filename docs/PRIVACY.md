# Privacy and Data Handling

Written plainly, because a product that asks people to expose what they do not
understand owes them a straight answer about where that goes.

## What this is

An unofficial, academic AI recreation of Andrew Ng. You can converse with it
about research, engineering, AI products and strategy, careers, or learning —
it is a general digital twin, not only a tutor. It is not affiliated with,
endorsed by, or reviewed by Andrew Ng, Stanford, or DeepLearning.AI. It is not
him, and if you ask it directly it will tell you so.

## What gets stored

When you use the twin, the following is written to a PostgreSQL database:

| Data | Why | Where |
|---|---|---|
| Your messages and the twin's replies | So conversations survive a refresh and can be reopened | `conversation_turns` |
| Context you share — concepts you mention, your role, organisation, projects, goals, and stated preferences, and what you are learning or working on | This is the memory feature: it is how the twin carries context across sessions | `entity_nodes`, `relation_edges` |
| Short quotes from your messages | Evidence for why something was recorded, so you can see and correct it | `relation_edges.evidence` |
| A conversation title, taken from your first message | The sidebar | `chat_sessions` |
| A random identifier for your browser | Ties your conversations together without an account | browser localStorage |

There is no account, no email address, and no password. The identifier in your
browser is the only thing linking one session to another. The twin does not
intentionally record passwords, API keys, payment or government identifiers,
private addresses, or sensitive personal attributes; if it ever captures
something it should not have, you can delete it (see below).

## What is NOT stored

- **Your API key.** It is held in `sessionStorage`, which the browser clears
  when you close the tab. It is sent with each request **to this application's
  backend**, which uses it to call Google and then discards it. It is **not**
  stored — never written to the database or to a log — but it is transmitted
  through the backend, so this is not an "it never leaves your browser" claim.
- **Audio.** Speech is transcribed by the browser and only the resulting text
  is sent onward.

## Where your data goes

**To Google.** Every message, along with the retrieved course material and a
summary of what the tutor remembers about you, is sent to the Gemini API to
generate a reply. This is not optional; it is how the tutor works.

**This matters and is easy to miss:** on Google's free API tier, content sent
to Gemini **may be used to improve their models**. Paid tiers are covered by
different terms. If your learning conversations are sensitive, use a paid key
or do not use this product.

**To Google, again, in voice mode.** The browser's speech recognition sends
your microphone audio to Google's servers for transcription. That happens in
the browser, before this application sees anything.

**Nowhere else.** There is no analytics, no tracking, no third-party embed, and
nothing is sold or shared.

## What you can do about it

- **See what it believes about you.** The memory panel shows every concept and
  relationship recorded, with the quote that produced it.
- **Correct it.** Any single belief can be deleted. Extraction is a language
  model making a guess, and some guesses are wrong.
- **Delete one conversation.** Removes its messages and the graph edges it
  produced.
- **Delete everything.** "Forget everything about me" in Settings removes all
  conversations, concepts and relationships for your browser identifier.

Deletion is immediate and permanent. There are no backups to restore from, and
data already sent to Google is outside this application's control.

## Children

This is built for a general audience and has no age verification. If you are
under 18, please do not use it without a parent or guardian who has read this
page. The point above about free-tier content being used for model training
applies to everyone.

## Self-hosting

Running your own instance means your data lives in your database and your key
is yours. See the README. Everything above about Google still applies, because
the tutor cannot generate a reply without calling a model.

## Corpus

The tutor answers using material from Andrew Ng's public work: CS229 lecture
notes, Machine Learning Yearning, The Batch newsletter, and public talks.
Copyright remains with the original authors and publishers. Passages are shown
as short excerpts to indicate a source, not as a substitute for reading the
original. See [POSTURE.md](POSTURE.md).

## Contact

Open an issue on the repository.

*If the behaviour of the product and this page ever disagree, the page is
wrong and should be fixed.*
