# Design records

A design record explains why a part of murmur works the way it does. It states the problem and
what a person needs, then the decision and the reason for it, and it names what is out of scope.
The records are for contributors. Before you change a part, read its record; when you change a
decision, update the record.

Most records here are about the fleet dashboard, the web page that runs on a farm (an always-on
Linux machine that runs coding agents).

Code comments cite records by section number, for example "github-projects.md, section 6". So a
record keeps its section numbers, even when a section's content changes.

If a record disagrees with the code or with the user documentation, the code and the user
documentation are right. Fix the record.

| Record | What it covers |
|---|---|
| [`dashboard-product.md`](dashboard-product.md) | What every dashboard tab shares: the shell, the API rules, the front end, the panel states and the vocabulary |
| [`dashboard-v2.md`](dashboard-v2.md) | The dashboard's three tabs, Board, Mail and Machine, and the numbered rules each one keeps |
| [`github-projects.md`](github-projects.md) | The Machine tab's Projects section: the farm's GitHub connection, importing a repository, and the routes behind both |
| [`hosting.md`](hosting.md) | Where a farm can run (your own machine over SSH, or a DigitalOcean Droplet) and the Machine tab's Hosting section |
| [`one-click-farm.md`](one-click-farm.md) | `/murmur:farm`, a Claude Code command on your laptop that creates a DigitalOcean Droplet, installs murmur on it and opens its dashboard |
| [`models-providers.md`](models-providers.md) | The Machine tab's Models section: providers, the models you switch on for each, and where a provider's model list comes from |

The user documentation for a farm and its dashboard is [`QUICKSTART.md`](../QUICKSTART.md) and
[`OPERATIONS.md`](../OPERATIONS.md).
