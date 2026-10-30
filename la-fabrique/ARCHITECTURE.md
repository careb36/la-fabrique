C4Context
    title La Fabrique — System Context
    Person(po, "Product Owner", "Sets sprint goals, approves irreversible actions")
    Person(dev, "Engineer", "Reviews artifacts, runs agent tasks")
    System(fab, "La Fabrique", "AI sprint lifecycle: plan, execute, review, remember")
    System_Ext(idp, "OIDC Identity Provider", "Auth0 / Keycloak")
    System_Ext(llm, "Model Providers", "LLM inference (hosted + optional self-hosted)")
    System_Ext(scm, "Source Control", "GitHub — issues, PRs, checks")
    System_Ext(obs, "Observability Backend", "OTel collector → Tempo / Prometheus / Loki")
    System_Ext(vault, "Secrets Manager", "Vault / AWS Secrets Manager")

    Rel(po, fab, "Plans sprints, approves", "HTTPS")
    Rel(dev, fab, "Reviews artifacts", "HTTPS")
    Rel(fab, idp, "Authenticates users", "OIDC")
    Rel(fab, llm, "Infers, embeds", "HTTPS, egress-controlled")
    Rel(fab, scm, "Reads issues, opens PRs", "GitHub App")
    Rel(fab, obs, "Traces, metrics, logs", "OTLP")
    Rel(fab, vault, "Fetches secrets", "mTLS")