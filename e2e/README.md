# E2E Tests (Playwright)

Run E2E tests:

```bash
npm run e2e
```

With headed browser (see the tests run):

```bash
npm run e2e:headed
```

## Auth

The appointments tests require authentication for full flows (Accept/Reject). For now, tests cover:

- Home page load
- Dashboard redirect / access state
- Appointments tab visibility

To test Accept/Reject with a real user, sign in manually in a headed run or use Clerk's testing utilities to obtain a session token.
