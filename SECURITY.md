# Security policy

This is a privileged endpoint management MVP for an explicitly authorized private network. Report suspected security issues privately to the repository owner; do not post credentials, customer data, scripts or command output in public issues.

Trust boundaries and operational requirements are documented in README. In particular, operators and approvers authorize code that runs as LocalSystem, gateways terminate agent TLS, and database administrators can alter the audit store. The execution mechanism is not a sandbox.

Dependency updates must retain passing authorization, tenant-isolation, claim, replay and relay-route tests. Keep .NET 10, container images and the identity provider on supported security patch releases. Never disable TLS validation or introduce an unauthenticated command-execution endpoint.
