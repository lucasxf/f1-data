# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an MVP analytics project combining **Formula 1 telemetry data** (via Open F1 API) with **Metabase** analytics capabilities, built as a portfolio project for a Metabase backend engineering interview.

**Goal**: Enable natural language queries and visual dashboards over F1 race data.

## Key Directives

- **MVP first**: Ship fast. Skip unit/integration tests for now.
- **Free tools only** (Metabase itself excepted).
- **Plan before building**: Enter plan mode for any non-trivial task. Wait for approval before executing.
- **Prefer open source** Metabase options over cloud/paid.

## Tech Stack

- **Frontend**: React
- **Backend**: Java or Python
- **Analytics/Data**: Python
- **Database**: TBD (evaluate 3+ options with trade-offs before committing)

## Architecture

```
Open F1 API → Data Ingestion → Database → Backend API → Metabase → React Frontend
```

1. Fetch F1 telemetry from Open F1 REST API
2. Store in a local database (or CSV for prototype)
3. Backend exposes data to Metabase
4. Metabase handles analytics, natural language queries, and chart generation
5. React frontend wraps Metabase UI and chat interface

## Happy Path Use Cases

1. **Chat query**: User asks "What was the top speed at Suzuka on 29/03/2026?" → returns driver name, number, team, and speed
2. **Dashboard query**: User asks for "Top 10 lap times sorted ascending" → app renders a Metabase chart

## Local Resources

- **Open F1 source code**: `C:\repo\openf1` — reference for API structure and data models
- **Learnimo (patterns)**: `C:\repo\engineering-daybook` — reuse agents, skills, and automation workflows
- **Metabase source**: `C:\repo\metabase` — reference for embedding, API, and SDK usage

## Metabase Setup References

- Docker: https://www.metabase.com/docs/latest/installation-and-operation/running-metabase-on-docker
- JAR: https://www.metabase.com/docs/latest/installation-and-operation/running-the-metabase-jar-file
- OSS start: https://www.metabase.com/start/oss/
