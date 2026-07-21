# Posture: What This Is, and the Lines It Does Not Cross

This project simulates a real, living, named person. That is worth stating
deliberately rather than leaving a reader to work out, and it is worth writing
down where the boundaries are before someone else asks.

## What it is

An unofficial, educational AI recreation of Andrew Ng's teaching style,
grounded in his public writing and lectures.

It is **not** affiliated with, endorsed by, reviewed by, or connected to Andrew
Ng, Stanford University, DeepLearning.AI, Landing AI, or AI Fund. Nobody named
here has been consulted about it.

## Honesty about what it is

The persona speaks in the first person and does not interrupt its own teaching
to narrate that it is a model. That is a style choice about how it teaches.

It is not a licence to deceive. The persona carries an explicit rule: **if
someone sincerely asks whether they are talking to the real Andrew Ng or to an
AI, it answers honestly and immediately**, in voice, and then returns to
teaching. It never claims to be him, never dodges the question, and never
pretends confusion about it.

An earlier version of the persona instructed the opposite, telling the model to
deflect such questions rather than "recite a disclaimer". That was changed
because deflecting is the one thing that turns a stylistic choice into
deception. The interface also carries a standing "unofficial AI recreation"
line, so the disclosure does not depend on anyone thinking to ask.

## The corpus

The tutor is grounded in publicly available material:

- Stanford CS229 lecture notes and recorded lectures
- Machine Learning Yearning
- The Batch newsletter
- Public blog posts and talks

**Copyright in all of it remains with the original authors and publishers.**
This project claims no ownership of any of it.

How that shapes the product:

- Retrieved passages are shown as **short excerpts to indicate a source**, not
  as full reproductions, and the UI points at where a passage came from.
- The tutor is instructed to teach from the material rather than recite it.
- It is a study aid, not a replacement for reading the originals, and it is not
  a distribution channel for them.

If a rights holder objects to any part of this, the correct response is to
remove it, not to argue.

## Voice

The repository contains a reference audio sample used for voice cloning.
Cloning the voice of a real, identifiable person is a different act from
writing in their style, and it is treated as such:

- The synthetic-audio **watermarker stays enabled**. An earlier version
  replaced it with a passthrough stub to work around a crash; that is now a
  loud warning rather than a silent bypass, because stripping a provenance
  marker from cloned speech of a real person is indefensible.
- The cloned voice is a **local capability**, not something to serve from a
  public URL.
- A public deployment should use a neutral voice, or none.

## If this is ever deployed publicly

The following are not optional:

1. The unofficial-recreation line stays visible, not buried in a footer.
2. Do not use Andrew Ng's name in a domain, product name, or anything that
   implies endorsement. A repository name is fine; a branded site is not.
3. Do not use his likeness, photograph, or signature.
4. Serve a non-cloned voice.
5. Link [PRIVACY.md](PRIVACY.md) from the interface, including the point about
   free-tier content being usable for model training.
6. Provide a way to report a problem and act on it.

## What this project will not do

- Claim endorsement or affiliation it does not have.
- Present generated text as something Andrew Ng actually said or wrote.
- Reproduce the corpus wholesale rather than excerpt it.
- Use the cloned voice to say things attributed to him as fact.

## Why this document exists

The reasoning is straightforward. The engineering here is defensible on its
merits, and the fastest way to undermine it would be to look as though nobody
had considered whose material and whose likeness it is built on. Writing the
boundaries down costs an afternoon and answers the objection before it is
raised.

It is also simply the right way to build on someone else's work.
