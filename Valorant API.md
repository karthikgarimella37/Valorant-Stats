Valorant Developer API Key: RGAPI-96024a33-527c-4d9f-971d-a16ac7809d86

Val.gg APIs
API Website: https://vlresports.vercel.app/
All Teams API: https://vlr.orlandomm.net/api/v1/teams?limit=all
Specific Team API: https://vlr.orlandomm.net/api/v1/teams/{team_id}
All Events API: https://vlr.orlandomm.net/api/v1/events

Rib.gg APIs
# Discovered Endpoints (as of Feb 2, 2026)
# Base URL: https://be-prod.rib.gg

# Teams
All Teams API: https://be-prod.rib.gg/v1/teams/all?take=100000
Teams (Paginated): https://be-prod.rib.gg/v1/teams
  - Returns: {meta: {start, results, total}, data: [...]}
  - Fields: id, name, shortName, description, websiteUrl, logoUrl, countryId
Specific Team: https://be-prod.rib.gg/v1/teams/{team_id}

# Events/Tournaments
Events API: https://be-prod.rib.gg/v1/events
  - Returns: {meta: {start, results, total}, data: [...]}
  - Fields: id, name, shortName, description, formatMd, eventType, startDate, endDate

# Series (Matches)
Series API: https://be-prod.rib.gg/v1/series
  - Returns: {meta: {start, results, total}, data: [...]}
  - Fields: id, eventId, team1Id, team2Id, team1Score, team2Score, startDate

# Query Parameters
- ?take=N - Limit results (for /all endpoints)
- ?start=N - Pagination offset (for base endpoints)
- ?results=N - Results per page (for base endpoints)

**Source rule:** rib.gg first. vlr.gg for anything rib does not have (including previous years). No valorant-api.com. VLR has no round-by-round data.

**Tables:** see `DATA_MODEL.md` (dims include region + country; half-round stats is a view; facts not locked yet).
Riot API Developer Key: b858c426-8dee-48c9-beef-32179832976b

**Graphs**
Line Plot for k/d/a race among players
Player Profile
- Race Plot for kills
- Stats per agent, per map
- Radar chat for stats/per match
- Bar chart for match (kills/deaths/assists)
- Beeswarm chart
- Most similar players (regression)

Match Report Visualization
Player Comparison
Team Comparison
Team Profile

Tournament prize distribution and event standings, agents played [https://www.vlr.gg/event/agents/2283/valorant-champions-2025]

Map Dashaboard (attack/defense win rate) and by how much
VCT Teams which lost on their map picks graph

**Tables Logical Schema:** superseded by `DATA_MODEL.md`.




**Tools to use**
Use dagster for orchestration, docker, dbt for sql and tests, gradio or typescript for website
