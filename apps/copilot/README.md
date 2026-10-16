# Meridian ops copilot (T17)

An Anthropic SDK tool loop (`copilot/loop.py`) on Agent Bricks' managed `DurableAgentServer`, deployed as a
Databricks App. Every invocation runs as the caller: the Apps ingress supplies the caller's token
(`[auth.user] required = true`), knowledge search covers only the caller's entitled tiers, and the model call
goes through Unity Gateway as the caller. Build with `scripts/build_copilot.sh`, which copies `src/meridian`
and the shared config next to this code; deploy from `build/copilot`.
