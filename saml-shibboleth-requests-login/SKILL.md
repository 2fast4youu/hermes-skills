---
name: saml-shibboleth-requests-login
description: "Use for Shibboleth/SAML logins via requests, not browser."
version: 1.0.0
author: Hermes Agent
license: MIT
---

# SAML/Shibboleth-Login via requests

Use when a script (not browser automation) must log in to a site behind a
Shibboleth IdP — JKU Moodle/USI/myJKU, university portals, or any
`SAML2/Redirect/SSO?execution=e1s1` flow — and plain credential POSTs fail.

## The #1 rule: follow redirects with allow_redirects=True
IdP POSTs answer 302s that the browser follows with **GET**. Manually
re-posting to each `Location` (a common recipe in older writeups) replays the
POST and produces **400 "Processing Error"** at `execution=e1s2`. Always use:

```python
r = s.post(url, data=fields, allow_redirects=True, timeout=30)
```

requests switches to GET after a 302 automatically. This single detail was the
difference between total failure and a working login.

## Typical flow
1. `GET <sp>/login/index.php` with `allow_redirects=True` → lands on the IdP
   page (`...execution=e1s1`).
2. That page is often a **JS auto-submit interstitial**: one form, NO username
   field, only `csrf_token`, `shib_idp_ls_*` hidden inputs, an empty
   `_eventId_proceed`. It submits itself via `document.form1.submit()`.
   Mimic it: collect all hidden inputs (fresh `csrf_token`!), POST back to
   the same URL.
3. Now the real credential form appears (`j_username`, `j_password`,
   `_eventId_proceed="Login"` — use the exact button value). Collect hidden
   fields again + credentials, POST with `allow_redirects=True`.
4. The IdP returns the SAML handoff page:
   `<form action="https://<sp>/Shibboleth.sso/SAML2/POST">` containing
   `RelayState` + `SAMLResponse`. POST it verbatim → logged in.

## Pitfalls
- **HTML-entity-encoded forms**: the SAML handoff form can encode its action
  and values (`&#x3a;` for `:`). Run `html.unescape()` over the action URL and
  attribute values before parsing/posting.
- **Relative form actions**: the IdP forms' `action` is often a relative URL
  (`/idp/profile/SAML2/Redirect/SSO?execution=e1s1`). Resolve it against the
  current page before POSTing — `target = urljoin(r.url, html.unescape(action))`;
  posting the raw relative action raises `requests.exceptions.MissingSchema`.
  This applies to the e1s1 interstitial and e1s2 credential form alike.
- **Don't trust "the form is wrong"** on a 400: first check whether you
  followed a redirect with POST instead of GET. The Processing Error page is
  generic and hides the real cause.
- **Dump intermediate pages** to files and list `<input>` names — the
  auto-submit page looks like an error page but is just boilerplate.
- Hidden-field collection regex: match `<input ...name="x"...>` then search
  `value="..."` inside the same tag; some inputs have no value attribute.
- Session cookies are HttpOnly on myJKU — only the requests-session path works
  there; `document.cookie` returns nothing.

## Verification before claiming success
A login is only proven when a subsequent authenticated GET shows logged-in
state (account name visible or `/my/` reachable) AND the target action (e.g.
calendar JSON fetch) succeeds end-to-end.
