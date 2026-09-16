---
type: comment
at: "2026-09-16T02:35:00Z"
by: "claude"
event: "updated"
---

Reframed after a second round with the reporting session, with each claim
checked against the code rather than accepted.

Confirmed: all 18 invocations byte-identical with no `--account`, and they
genuinely do hold SEND-scoped tokens. The sharper detail neither of us had:
`allow_send` DEFAULTS TO TRUE, so the per-profile send cap is opt-out. Both
device_code profiles therefore get `Mail.Send`. I briefly concluded the
opposite mid-check by reading the key's absence from profiles.toml as
"false" — the dataclass default is what settles it, not the TOML.

Corrected the reporter on one point: a shared daemon would NOT only ever
instantiate one profile. There is no default profile — `resolve_profile`
raises unless exactly one is configured, and three are — so every call
already names an account and per-profile keying is required today.

Priority low -> medium, and the pitch now leads with standing privilege
rather than memory. Still not built, still needs the owner: the transport
change contradicts a stated phase-1 requirement, and consolidating send
reach is his decision.
