# Posture: What This Is, and the Lines It Does Not Cross

This project simulates a real, living, named person. That is worth stating
deliberately rather than leaving a reader to work out, and it is worth writing
down where the boundaries are before someone else asks.

## What it is

An unofficial, academic AI recreation of Andrew Ng — a **digital twin** of his
public knowledge, reasoning habits, communication style, and voice, grounded in
his public writing and lectures. Teaching is one of its behaviours, not its
whole purpose: it is built to converse with researchers, engineers, founders,
product and business leaders, students, and the general public.

As an academic demonstration of digital-twin techniques, it **deliberately**
uses a reconstructed portrait of Andrew Ng and a synthetic voice modelled on
his. Those choices are made openly, with the guardrails below — a visible
unofficial-recreation disclosure, a persistent synthetic-voice label, and an
audio provenance watermark that stays enabled — not hidden.

It is **not** affiliated with, endorsed by, reviewed by, or connected to Andrew
Ng, Stanford University, DeepLearning.AI, Landing AI, or AI Fund. Nobody named
here has been consulted about it.

## Honesty about what it is

The persona speaks in the first person and does not interrupt a useful response
to narrate that it is a model. That is a conversational style choice.

It is not a licence to deceive. The persona carries an explicit rule: **if
someone sincerely asks whether they are talking to the real Andrew Ng or to an
AI, it answers honestly and immediately**, in voice, and then returns to
the conversation. It never claims to be him, never dodges the question, and never
pretends confusion about it.

An earlier version of the persona instructed the opposite, telling the model to
deflect such questions rather than "recite a disclaimer". That was changed
because deflecting is the one thing that turns a stylistic choice into
deception. The interface also carries a standing "unofficial AI recreation"
line, so the disclosure does not depend on anyone thinking to ask.

## The corpus

The twin is grounded in publicly available material:

- Stanford CS229 lecture notes and recorded lectures
- Machine Learning Yearning
- The Batch newsletter
- Public blog posts and talks

**Copyright in all of it remains with the original authors and publishers.**
This project claims no ownership of any of it.

How that shapes the product:

- Retrieved passages are shown as **short excerpts to indicate a source**, not
  as full reproductions, and the UI points at where a passage came from.
- The twin is instructed to answer from the material rather than recite it.
- It is an aid, not a replacement for reading the originals, and it is not a
  distribution channel for them.

If a rights holder objects to any part of this, the correct response is to
remove it, not to argue.

## Voice

The repository contains a reference audio sample used for voice cloning.
Cloning the voice of a real, identifiable person is a different act from
writing in their style, and it is treated as such. As a digital-twin
demonstration the cloned voice is used deliberately, under these conditions:

- The synthetic-audio **watermarker stays enabled**. An earlier version
  replaced it with a passthrough stub to work around a crash; that is now a
  loud warning rather than a silent bypass, because stripping a provenance
  marker from cloned speech of a real person is indefensible.
- The interface carries a **persistent, visible "synthetic voice" label** so a
  listener is never left to assume the audio is a real recording.
- The cloned voice runs on a **local/self-hosted** capability. When it is
  unavailable the product falls back to a neutral browser voice and says so;
  it never presents the generic browser voice as the clone.

## The portrait

The landing page and app use a reconstructed particle portrait built from a
public photograph of Andrew Ng. It is a deliberate part of the twin's identity.
It is presented as an unofficial recreation, never as an official likeness or
endorsement, and it is not passed off as an authentic photograph or signature.

## If this is ever deployed publicly

The following are not optional:

1. The unofficial-recreation line stays visible, not buried in a footer.
2. Do not use Andrew Ng's name in a domain, product name, or anything that
   implies endorsement. A repository name is fine; a branded site is not.
3. The portrait and synthetic voice may be used as part of the twin, but always
   with the unofficial-recreation disclosure and the synthetic-voice label
   visible, and never in a way that implies endorsement or authenticity.
4. Keep the audio provenance watermark enabled.
5. Link [PRIVACY.md](PRIVACY.md) from the interface, including the point about
   free-tier content being usable for model training.
6. Provide a way to report a problem and act on it.

## What this project will not do

- Claim endorsement or affiliation it does not have.
- Present generated text as something Andrew Ng actually said or wrote.
- Reproduce the corpus wholesale rather than excerpt it.
- Use the cloned voice or portrait to attribute statements to him as fact, or
  to communicate or transact externally as if it were him.
- Strip the synthetic-voice label or the audio provenance watermark.

## Why this document exists

The reasoning is straightforward. The engineering here is defensible on its
merits, and the fastest way to undermine it would be to look as though nobody
had considered whose material and whose likeness it is built on. Writing the
boundaries down costs an afternoon and answers the objection before it is
raised.

It is also simply the right way to build on someone else's work.
