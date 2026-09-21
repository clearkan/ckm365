# Graph behaviour notes (found by live probing)

What Microsoft Graph actually does in the places where its documentation is
silent, or where our offline mocks could not tell us. Every entry here came
from a throwaway probe run against a real mailbox: create one object,
measure, delete it, confirm the 404. Each gives the behaviour, a generic
request shape to reproduce it, and where ckm365 depends on it.

Scope: this page keeps the probe detail. The one-line rules already live
elsewhere, so they are linked rather than repeated:

- AGENTS.md "Gotchas already paid for": the comment-stripping rule, the
  sentinel-div fence, the plain-text quote shape, the MIME-import headers.
- `docs/graph-direct.md`: how to call Graph yourself (Recipe 1 for `Ctx`,
  Recipe 4 for MIME import) and where Microsoft's API reference lives.

Probe conventions, if you write a new one: print booleans, counts, lengths
and truncated ids only, never body text or subjects. Leave zero residue and
prove it with a 404. Read bodies back with
`Prefer: outlook.body-content-type="html"`, or Graph may hand you a text
rendering that hides the markup you are measuring.

---

## Mail: what survives in a stored draft body

### 1. Exchange strips HTML comments on store, and keeps element attributes

**Behaviour.** When a draft body is PATCHed and read back, every HTML
comment inside `<body>` is gone. Attributes on real elements survive
verbatim. Results were identical on both test tenants (2026-09-15):

| Candidate marker | Survives PATCH then GET |
|---|---|
| `<!--name-->` HTML comment | no |
| `<!--[if !mso]><!-->` conditional comment | no |
| `<div id="...">` (empty) | yes |
| `<span id="...">` (empty) | yes |
| `<div data-x="...">` (empty) | yes |
| `<div class="...">` (empty) | yes |

Nothing errors. The comment is just not there when you read the body back.

**Reproduce.**

```
POST  /users/<user>/messages/{id}/createReply            -> draft id
PATCH /users/<user>/messages/{draft}
      {"body": {"contentType": "html",
                "content": "<html><body><!--a--><p>x</p><!--/a-->
                            <div id=\"s\"></div><p>y</p><div id=\"e\"></div>
                            </body></html>"}}
GET   /users/<user>/messages/{draft}?$select=body
      Prefer: outlook.body-content-type="html"
      -> substring-test each marker; then DELETE the draft, expect 404
```

**ckm365 relies on it.** The compose fence in `tools/mail/common.py`
(`fence_open`/`fence_close`: an empty `<div id="ckm365-body-start">` and a
matching `-end` div, plus the same pair for the signature). `revise_draft`
replaces what sits between them. `verify_message` reports
`boundary="fence"` when it finds them. Until CKM-48 the fence was a pair of
comments, so it vanished on every save and `revise_draft` duplicated
bodies (CHANGELOG 2.7.0).

### 2. The fence also survives the MIME-import route

**Behaviour.** A draft created by POSTing base64 RFC-5322 MIME (Recipe 4)
keeps the sentinel divs in its HTML part. `verify_message` reports
`boundary="fence"` on the imported draft, and `revise_draft` replaces in
place through it. Verified on both tenants (2026-09-15, CKM-45).

**Reproduce.** Run `create_persona_reply`, then `verify_message` and
`revise_draft` on the result. Alternatively, import a MIME message by hand
with the divs in its `text/html` part (Recipe 4) and read the body back as
in finding 1.

**ckm365 relies on it.** `create_persona_reply` fences its text so the
normal revise loop works on persona drafts.

### 3. How Graph seeds a reply to a plain-text original

**Behaviour.** `createReply` on a message that arrived as plain text
produces none of the usual reply markup. Measured on one tenant
(2026-09-15), after ckm365 had inserted its fenced text at the top:

- None of `divRplyFwdMsg`, `id="appendonsend"`, `gmail_quote`,
  `-----Original Message-----` or `<blockquote` appears in the body.
- There is no `<hr>`.
- The only `id`/`class` attributes in the whole body are ckm365's two fence
  divs and one `<div class="PlainText">`, which holds the quoted text.
- The quoted lines are separated by `<br>` (26 of them in the sample), with
  one `<p>`, one `<font>`, one `<span>` and a `<style>` block in `<head>`.

The HTML-original case was not probed. The markers `divRplyFwdMsg` and
`appendonsend` for that case come from Graph's own reply markup, as noted
in `common.py` and `verify.py`. The CHANGELOG (2.7.0) records only that the
2.6.0 smoke run printed `boundary=quote` on both tenants. It doesn't say
which original shape each tenant used.

**Reproduce.**

```
POST /users/<user>/messages/{plain-text message id}/createReply
GET  /users/<user>/messages/{draft}?$select=body
     Prefer: outlook.body-content-type="html"
     -> regex out tag names and id/class/name attributes only
        (never text nodes); then DELETE the draft, expect 404
```

Pick the source message deliberately. Which shape you get depends on the
format of the newest mail in the test mailbox, and that differs between
tenants.

**ckm365 relies on it.** `verify.py:_QUOTE_MARKS` includes
`class="plaintext"`, matched against the lowercased body. Without it,
`verify_message["quoted_thread"]` reported False on intact replies to
plain-text mail (fixed in 2.7.0).

---

## Calendar: a hidden marker via single-value extended properties

These probes checked whether a calendar mirror could tag its own events
invisibly, so a reconciler can find "events I made" and skip them when
reading (idempotency and echo prevention). The context is the calendar-sync
question on the board (issue `0x83nw`, backlog). All findings are from one
delegated operator tenant, 2026-09-16, using one test event a year in the
future with no attendees. No ckm365 tool uses extended properties today.
Everything below goes through the escape hatch (`docs/graph-direct.md`).

The property id has the form
`String {<namespace-guid>} Name <propertyName>`. Generate your own
namespace GUID once and keep it constant.

### 4. The property saves, but the create response does not echo it

**Behaviour.** A `POST .../events` that carries `singleValueExtendedProperties`
succeeds and the property is stored. The POST response body does **not**
include it. The same response does echo `showAs: busy`,
`sensitivity: private`, `isReminderOn: false` and zero attendees as sent.

**Reproduce.**

```
POST /users/<user>/events
     {"subject": "Busy", "showAs": "busy", "sensitivity": "private",
      "isReminderOn": false,
      "start": {"dateTime": "...", "timeZone": "UTC"},
      "end":   {"dateTime": "...", "timeZone": "UTC"},
      "singleValueExtendedProperties":
        [{"id": "String {<namespace-guid>} Name <propertyName>",
          "value": "<tag>"}]}
-> response has no singleValueExtendedProperties key
```

**ckm365 relies on it.** Not yet. `create_event` does not expose extended
properties, `showAs` or `sensitivity`. It does keep the no-attendees rule:
with attendees, `create_event` escalates to the send tier.

### 5. Which reads return the property, and one that silently does not

**Behaviour.** The same stored property, read four ways:

| Read | Property returned |
|---|---|
| A. `GET /events/{id}` + `$expand` | yes |
| B. `GET /calendarView` (window) + `$expand` only | **no, and no error** |
| C. `GET /events` + `$filter` on id **and** value + `$expand` | yes |
| D. `GET /calendarView` + the same `$filter` + `$expand` | yes |

The `$expand` in every row is
`singleValueExtendedProperties($filter=id eq '<property id>')`.

Read B is the trap. The event row comes back, the property does not, and
nothing signals a problem. A reconciler built on B would take every one of
its own mirrors for a real meeting and mirror it again.

**Reproduce.**

```
GET /users/<user>/calendarView?startDateTime=<s>Z&endDateTime=<e>Z
    &$select=id
    &$expand=singleValueExtendedProperties($filter=id eq '<property id>')
    -> row present, property absent                      (B)
GET /users/<user>/calendarView?startDateTime=<s>Z&endDateTime=<e>Z
    &$select=id
    &$filter=singleValueExtendedProperties/Any(ep: ep/id eq '<property id>'
                                                  and ep/value eq '<tag>')
    &$expand=singleValueExtendedProperties($filter=id eq '<property id>')
    -> row present, property present                     (D)
```

**ckm365 relies on it.** Not yet. `list_events` reads `calendarView`, so
any future marker-aware read must use shape D, not B.

### 6. Filtering on the property id alone is rejected

**Behaviour.** A `calendarView` `$filter` that names the property id with no
value restriction fails:

```
400 ErrorInvalidUrlQueryFilter
"The filter expression for $filter does not match to a single extended
 property and a value restriction."
```

So "list every event carrying my marker in this window" cannot be written as
an id-only `Any(...)` filter. Graph needs an equality test on the value as
well.

**Reproduce.** Use shape D from finding 5 and drop the `and ep/value eq '...'`
clause.

**Proposed workaround (not probed).** Give each marked
event two properties: a constant flag, such as `<propertyName>Flag = "1"`,
to filter on, and the source reference to read back for tracking. This is
untested. Confirm it live before designing on it.

**ckm365 relies on it.** Not yet. This matters to anyone building the
two-way or idempotent calendar sync described on the board.

---

## Not recorded here

- `showAs`/`sensitivity` as filter or read inputs, and `calendarView/delta`:
  reachable under `Calendars.ReadWrite`, never probed.
