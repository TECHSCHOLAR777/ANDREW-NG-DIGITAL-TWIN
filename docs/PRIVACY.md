# Privacy and Data Handling

This document describes the application as implemented. A system that stores
conversations and contextual memory owes people a clear account of where that
information goes.

## What this is

Andrew Ng Digital Twin is an unofficial conversational recreation based on
public work. It supports conversations about machine learning research,
engineering, AI products and strategy, careers, industry questions, opinions,
and learning. Tutoring is one behaviour, not the complete product.

It is not affiliated with, endorsed by, or reviewed by Andrew Ng, Stanford
University, or DeepLearning.AI.

## What is stored

| Data | Purpose | Location |
|---|---|---|
| User messages and generated replies | Restore conversation history | `conversation_turns` |
| Conversation titles and timestamps | Display and order the session list | `chat_sessions` |
| Roles, organisations, projects, goals, preferences, people, concepts, and other context extracted from conversations | Carry relevant context across sessions | `entity_nodes`, `entity_aliases`, `relation_edges` |
| Short evidence excerpts from messages | Explain why a relationship was recorded and support correction | `relation_edges.evidence` |
| A random guest identifier | Associate guest sessions in one browser | Browser local storage |
| Email address, display name, tenant ownership, and a bcrypt password hash after signup | Authentication and cross-device continuity | `app_users` |

A guest is identified by a browser UUID. A signed-in account owns one tenant,
allowing conversations and contextual memory to follow the account across
devices.

## What is not stored

- The Gemini API key is held in browser session storage and sent with active
  generation requests. The application does not write it to PostgreSQL.
- The raw account password is not stored. Signup stores a bcrypt hash.
- Microphone recordings are not saved as conversation data.
- Generated speech audio is not stored as part of session history.

Do not enter secrets, payment information, government identifiers, private
addresses, health records, or other sensitive information into a conversation.
Context extraction is model-driven and can record information incorrectly.

## Where data is processed

### Application hosting and database

The public deployment uses Vercel for the frontend, Render for the API, and
Neon for PostgreSQL. These providers process requests, connection metadata, and
stored application data according to their own terms and retention policies.

### Gemini

For each generated answer, the backend sends the current message, relevant
conversation history, retrieved source passages, and a summary of contextual
memory to Gemini using the visitor's API key.

How a provider retains or uses API content depends on the selected account,
service tier, and current provider terms. Review those terms before sending
sensitive material.

### Embedding provider

Message text and extracted entity names are sent to the configured embedding
provider to create vectors for retrieval and graph matching. The default
provider is Jina, but an operator can configure Voyage, Gemini, or a local
model.

### Speech recognition

In interactive voice mode, the browser's speech-recognition implementation may
send microphone audio to its own provider for transcription. The application
receives the resulting text.

### Optional speech synthesis

When an external or cloned speech service is enabled, completed response
sentences are sent to that service and returned as audio. Browser speech
synthesis is used when the configured service is unavailable.

The project does not include application advertising trackers and does not sell
conversation data.

## User controls

- Inspect the session or global contextual memory graph.
- Remove an individual graph relationship.
- Delete one conversation and its session-scoped relationships.
- Use the full reset control to remove tenant-scoped sessions, turns, entities,
  aliases, and relationships.

Full reset preserves the tenant identity and, for registered users, the
authentication account. The current application does not expose a self-service
account-deletion route.

Deletion removes application records from the active database. It cannot recall
content already processed by an external model, embedding, recognition, or
speech provider. Provider-side retention is governed by that provider.

## Children

The application has no age-verification system. Anyone under 18 should use it
only with a parent or guardian who has reviewed this document and the relevant
provider terms.

## Self-hosting

In a self-hosted installation, stored data lives in the operator's database.
Requests still leave the application for whichever generation, embedding,
speech-recognition, and speech-synthesis providers the operator configures.

## Corpus

The twin retrieves from Andrew Ng's public lectures, course material, books,
newsletters, interviews, and writing. Copyright remains with the original
authors and publishers. Retrieved excerpts indicate a source and are not a
substitute for the original work.

See [`POSTURE.md`](POSTURE.md) for the project's public-use boundaries.

## Contact

Open an issue in the repository for privacy questions or correction requests.

If the application's behaviour and this document disagree, treat the document
as stale and correct it.
