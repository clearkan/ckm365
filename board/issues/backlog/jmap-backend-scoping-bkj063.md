---
type: "issue"
title: "JMAP + CalDAV backend: scope what ckm365 needs to run against a self-hosted mail server"
created: "2026-11-13T05:55:23Z"
resource: "oif:ckm/bkj063"
kind: "task"
priority: "medium"
requested_by: "human:seanwy"
tags: ["architecture", "jmap", "caldav", "self-hosted", "scoping"]
---

The owner is piloting a self-hosted, open-source mail stack: Stalwart for
SMTP, IMAP, JMAP, CalDAV and CardDAV, with a paid outbound relay. It
starts on one low-traffic owner domain. What prompted it is a ~12-hour
Exchange Online outage on 2026-11-13. Graph's front end answered, but
every mailbox call on both owner tenants returned 502 or 504
`UnknownError` after 20-30 s. Agents need the same tools against the new
server, so this card scopes a JMAP backend. Scoping only: no code, no
new dependencies.

## The coupling today

Tools call Graph paths directly (`g.request(... mailbox_path(...))`), so
there is no backend seam. JMAP would be the second caller, which is the
point where KISS says to add the abstraction.

**Recommended shape:**
- The profile picks the backend: `backend = "graph" | "jmap"`, default
  graph.
- Tool names, signatures, tiers and presets stay the same, so agents
  notice nothing.
- Each concern gets a JMAP implementation module beside the Graph one,
  and the tool dispatches on `ctx`.
- Pure modules are shared unchanged: disk fences, exclusions, record
  export, migrate, audit, compose-fence helpers.

## Mapping, by tool family

| ckm365 today (Graph) | JMAP / CalDAV equivalent | Notes |
|---|---|---|
| list_messages predicates as `$filter`; KQL `search` | `Email/query` FilterCondition (`inMailbox`, `after`, `from`, `hasKeyword`), `text` | The subject-index-lag warning is Graph-specific; re-measure on Stalwart |
| get_message, headers, `internetMessageId` | `Email/get` with `header:*` properties, `messageId` | The cross-mailbox dedupe key carries over unchanged |
| export_message `.eml` (`$value`) | `blobId` download of the raw MIME | Simpler than Graph |
| attachments, upload session above 3 MB | Blob upload and download | No size-split path |
| watch.py delta, `delta_token` | `Email/changes`, `Mailbox/changes` state strings; push via EventSource | wait_for_message can block on push instead of polling |
| createReply/All/Forward seeding | ckm365 builds the reply: In-Reply-To, References, quoted body | The fence gets simpler, since there are no Graph seed markers (`divRplyFwdMsg`, `appendonsend`) |
| update_draft, revise_draft PATCH | Email objects are IMMUTABLE: create the new draft, destroy the old | **The draft id changes on every edit.** That breaks the current id-stability contract, so design it explicitly |
| send_draft | `EmailSubmission/set` with `onSuccessUpdateEmail` (move to Sent, clear `$draft`) | |
| persona/shared mailboxes, create_persona_reply MIME import | JMAP Identities (send-as), shared accounts, `Email/import` | Biggest design item after drafts |
| flags, categories, move | `$seen`, `$flagged`, custom keywords, `mailboxIds` patch | complete_flag has no equivalent: a keyword convention, or drop it |
| calendar list/get/create/update/respond | JMAP for Calendars: `Calendar/*`, `CalendarEvent/*`, events as JSCalendar (RFC 8984) JSON | Supported since Stalwart v0.14.0 (see Facts). JSON in, JSON out, so NO iCalendar parser is needed. CalDAV stays as the server's interface for Thunderbird and phones |
| teams, meetings presets | None | Out of scope; those stay Graph-only |
| auth.py (msal, device code) | Basic over TLS, or bearer / app password from the secret store | jmap profiles need no msal; httpx is enough |
| admin.py (tenant app registration) | Stalwart's admin API is a separate concern | Do not fold server admin into ckm365 |

## Phases, each shippable

1. **Read:** list, get, headers, folders, export, attachment download,
   watch (changes and push).
2. **Write:** drafts (incl. reply seeding and the immutable-draft id
   contract), triage keywords, move.
3. **Send:** EmailSubmission and identities, persona replies.
4. **Calendar:** JMAP for Calendars plus Contacts (RFC 9610) when
   needed. Re-check the calendar draft revision Stalwart implements at
   build time, since it is not yet an RFC.

## Testing

Offline tests stay mock-based, with a JMAP MockTransport alongside the
Graph one. Live tests run against a throwaway account on the pilot
server, never a live owner mailbox, as with the Graph live tests.

## Facts (checked 2026-11-13)

- Stalwart **v0.14.0** (2025-10-22) added JMAP for Calendars, JMAP for
  Contacts (RFC 9610) and JMAP Sharing (RFC 9670), alongside the CalDAV,
  CardDAV and WebDAV that v0.12 brought. So Q1 is answered: JMAP, not
  only CalDAV. Sources: the v0.14.0 GitHub release notes and the
  Stalwart blog post "JMAP for Calendars, Contacts and Files now in
  Stalwart".
- **v1.0.0** (2026-10-26) is the first stable release. Its changelog
  pins JMAP for Calendars to draft-ietf-jmap-calendars-33 and fixes
  `Calendar/set`, `CalendarEvent/set`, `AddressBook/set` and
  `ContactCard/set` responses. It changes the database layout, so a
  v0.16 install cannot be upgraded in place. **A new pilot should
  install 1.0.x directly.** A third-party project reports testing
  against v1.0.3. Check the releases page for the current patch.
- Client support for JMAP Calendars and Contacts is still thin, per the
  Stalwart blog. Thunderbird and iOS keep using CalDAV and CardDAV
  against the same data. Agents use JMAP, people's devices use DAV,
  one store underneath.

## Decisions for the owner (recommendation first)

- **No iCalendar dependency. Recommended: yes, go without one.** JMAP
  Calendars speaks JSCalendar JSON, so httpx alone covers it. Revisit
  only if a tool must parse a raw `.ics` attachment. Stalwart handles
  the scheduling of invites from Outlook senders on the server side.
- **Standard reply format, not an Outlook clone. Recommended: yes.**
  Threading rides on `In-Reply-To` and `References`, which Outlook,
  Gmail and Thunderbird all honour. The body gets a plain "On <date>,
  <name> wrote:" header above a `<blockquote>` of the original.
  Imitating Outlook's `divRplyFwdMsg` markup would buy nothing and
  re-import the forged-fence surface fixed in v2.14.0 (3s6pwx).
