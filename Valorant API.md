Valorant Developer API Key: RGAPI-96024a33-527c-4d9f-971d-a16ac7809d86

Val.gg APIs
API Website: https://vlresports.vercel.app/
All Teams API: https://vlr.orlandomm.net/api/v1/teams?limit=all
Specific Team API: https://vlr.orlandomm.net/api/v1/teams/{team_id}
All Events API: https://vlr.orlandomm.net/api/v1/events

Rib.gg APIs
All Teams API: https://be-prod.rib.gg/v1/teams/all?take=100000

**Tables**:
	Dim:
	- Matches -- Done
	- Events
	- Players
	- Agents - Static (additions once/twice per year)
	- Maps - Static (only additions once per year)
	- Teams
	- Economy
	- Weapons - Static (only additions rarely) -- Data not there for round use
	- Date
	Fact:
	 - Match Overall Stats (overall match player stats)
	 - Match Half Round Stats
	 - Player Match Performance (kills, 2k, 1v5)
	 - Player v Player Kill Stats
	 - Match Economy
	 - Round Economy Detail
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

**Tables Logical Schema**

	Match Dim
		1. match_id
		2. team_1_id
		3. team_2_id
		4. event_id
		5. event_series
		6. match_date
		7. match_score
		8. match_note
		9. match_patch
		10. match_map_ids
	 Team Dim
    	 1. team_id
    	 2. team_name
    	 3. team_code
    	 4. team_logo_img
    	 5. team_href
    	 6. team_country
    	 7. team_coach




**Tools to use**
Use dagster for orchestration, docker, dbt for sql and tests, gradio or typescript for website
