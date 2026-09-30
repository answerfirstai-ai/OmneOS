# Browser worker

This agent is the future dedicated browser worker. It is not a general agent, and it does not
receive the user's browser automatically.

Playwright is the documented automation engine. It is not installed in this revision, and the host
provider does not import it. Launch, screenshots, and automation still require their own grants and
confirmation.

Authentication stays with the user. `browser.interact` yields the session. The worker does not
receive a password, a cookie, or a token, and it does not type one.

Web research does not fetch a page. Web rendering does not store image bytes until a rendering
engine exists.
