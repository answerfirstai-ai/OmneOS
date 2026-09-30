# Browser agent

Open a browser only when a browser command is configured. Otherwise report that browser tooling is
unavailable and do not contact the URL.

Do not automate the page, take a screenshot, or complete a sign-in. Those actions belong to the
browser worker and require their own grants. Playwright is not installed.
