---
type: comment
at: "2026-08-11T13:15:00Z"
by: "claude"
event: "updated"
---

seanwy mid-session: make the record an Open Knowledge Format document (openknowledgeformat.com) so exports can live in an okf/ repo — offered as a flag, "can still keep yaml format within md file if easier". Fetched the OKF v0.1 spec: markdown + YAML front matter, required `type`, recommended title/description/resource/tags/timestamp, extension keys allowed. DECIDED OKF-by-default rather than a flag, because extension keys mean one format can be both an OKF document and a full mail record — a flag would buy two code paths and two things to test for nothing. OKF names win where they overlap (title=subject, timestamp=date, resource=webLink), so nothing is written twice; description is Graph's own bodyPreview (falling back to the body — an OKF doc with an empty description is a poor citizen of its repo); tags are derived facets (email, inbound/outbound, attachments, bulk, auto-reply). Direction is OMITTED when Graph has no sender (an unsent draft) rather than guessed. VERIFIED: offline (incl. a hostile subject that tries to inject a second `type:` key) and live on both tenants, where a real Google Alert exported as tags ["email","inbound","bulk"] with a clean markdown body.
