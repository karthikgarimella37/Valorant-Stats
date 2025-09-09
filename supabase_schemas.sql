-- VALORANT Stats Database Schema for Supabase
-- Dimension Tables

-- Events table
CREATE TABLE dim_events (
    event_id SERIAL PRIMARY KEY,
    event_name VARCHAR(255) NOT NULL,
    event_type VARCHAR(100),
    start_date DATE,
    end_date DATE,
    location VARCHAR(255),
    prize_pool DECIMAL(15,2),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Teams table
CREATE TABLE dim_teams (
    team_id SERIAL PRIMARY KEY,
    team_name VARCHAR(255) NOT NULL,
    team_tag VARCHAR(10),
    region VARCHAR(100),
    country VARCHAR(100),
    logo_url TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Players table
CREATE TABLE dim_players (
    player_id SERIAL PRIMARY KEY,
    player_name VARCHAR(255) NOT NULL,
    player_tag VARCHAR(100),
    real_name VARCHAR(255),
    country VARCHAR(100),
    team_id INTEGER REFERENCES dim_teams(team_id),
    role VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Agents table
CREATE TABLE dim_agents (
    agent_id SERIAL PRIMARY KEY,
    agent_name VARCHAR(100) NOT NULL UNIQUE,
    agent_type VARCHAR(50), -- Duelist, Controller, Initiator, Sentinel
    created_at TIMESTAMP DEFAULT NOW()
);

-- Maps table
CREATE TABLE dim_maps (
    map_id SERIAL PRIMARY KEY,
    map_name VARCHAR(100) NOT NULL UNIQUE,
    map_type VARCHAR(50),
    release_date DATE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Matches table
CREATE TABLE dim_matches (
    match_id SERIAL PRIMARY KEY,
    vlr_match_id VARCHAR(50) UNIQUE, -- VLR.gg match ID
    event_id INTEGER REFERENCES dim_events(event_id),
    team1_id INTEGER REFERENCES dim_teams(team_id),
    team2_id INTEGER REFERENCES dim_teams(team_id),
    match_date TIMESTAMP,
    match_format VARCHAR(20), -- BO1, BO3, BO5
    match_status VARCHAR(20), -- completed, live, upcoming
    winner_team_id INTEGER REFERENCES dim_teams(team_id),
    final_score VARCHAR(20), -- e.g., "2-1"
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Fact Tables

-- Match Overall Stats (team-level aggregated stats per match)
CREATE TABLE fact_match_overall_stats (
    stat_id SERIAL PRIMARY KEY,
    match_id INTEGER REFERENCES dim_matches(match_id),
    team_id INTEGER REFERENCES dim_teams(team_id),
    map_id INTEGER REFERENCES dim_maps(map_id),
    rounds_won INTEGER,
    rounds_lost INTEGER,
    total_kills INTEGER,
    total_deaths INTEGER,
    total_assists INTEGER,
    total_acs DECIMAL(8,2), -- Average Combat Score
    total_adr DECIMAL(8,2), -- Average Damage per Round
    first_kills INTEGER,
    first_deaths INTEGER,
    clutches_won INTEGER,
    clutches_attempted INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Match Performance (individual player performance per map)
CREATE TABLE fact_match_performance (
    performance_id SERIAL PRIMARY KEY,
    match_id INTEGER REFERENCES dim_matches(match_id),
    player_id INTEGER REFERENCES dim_players(player_id),
    team_id INTEGER REFERENCES dim_teams(team_id),
    map_id INTEGER REFERENCES dim_maps(map_id),
    agent_id INTEGER REFERENCES dim_agents(agent_id),
    kills INTEGER,
    deaths INTEGER,
    assists INTEGER,
    acs DECIMAL(8,2), -- Average Combat Score
    adr DECIMAL(8,2), -- Average Damage per Round
    hs_percentage DECIMAL(5,2), -- Headshot percentage
    first_kills INTEGER,
    first_deaths INTEGER,
    fkfd_diff INTEGER, -- First kill/First death difference
    rating DECIMAL(4,2),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Match Economy (economy-related stats per player per map)
CREATE TABLE fact_match_economy (
    economy_id SERIAL PRIMARY KEY,
    match_id INTEGER REFERENCES dim_matches(match_id),
    player_id INTEGER REFERENCES dim_players(player_id),
    team_id INTEGER REFERENCES dim_teams(team_id),
    map_id INTEGER REFERENCES dim_maps(map_id),
    total_spent INTEGER, -- Total credits spent
    equipment_value INTEGER, -- Average equipment value
    money_saved INTEGER, -- Credits saved/eco rounds
    clutches_won INTEGER,
    clutches_attempted INTEGER,
    multi_kills INTEGER, -- 2k, 3k, 4k, 5k combined
    created_at TIMESTAMP DEFAULT NOW()
);

-- Insert default agents
INSERT INTO dim_agents (agent_name, agent_type) VALUES
('Jett', 'Duelist'),
('Reyna', 'Duelist'),
('Raze', 'Duelist'),
('Phoenix', 'Duelist'),
('Yoru', 'Duelist'),
('Neon', 'Duelist'),
('Iso', 'Duelist'),
('Brimstone', 'Controller'),
('Viper', 'Controller'),
('Omen', 'Controller'),
('Astra', 'Controller'),
('Harbor', 'Controller'),
('Clove', 'Controller'),
('Sova', 'Initiator'),
('Breach', 'Initiator'),
('Skye', 'Initiator'),
('KAY/O', 'Initiator'),
('Fade', 'Initiator'),
('Gekko', 'Initiator'),
('Sage', 'Sentinel'),
('Cypher', 'Sentinel'),
('Killjoy', 'Sentinel'),
('Chamber', 'Sentinel'),
('Deadlock', 'Sentinel'),
('Vyse', 'Sentinel');

-- Insert default maps
INSERT INTO dim_maps (map_name, map_type) VALUES
('Bind', 'Standard'),
('Haven', 'Standard'),
('Split', 'Standard'),
('Ascent', 'Standard'),
('Dust2', 'Standard'),
('Breeze', 'Standard'),
('Fracture', 'Standard'),
('Pearl', 'Standard'),
('Lotus', 'Standard'),
('Sunset', 'Standard'),
('Abyss', 'Standard');

-- Create indexes for better performance
CREATE INDEX idx_matches_vlr_id ON dim_matches(vlr_match_id);
CREATE INDEX idx_matches_date ON dim_matches(match_date);
CREATE INDEX idx_performance_match ON fact_match_performance(match_id);
CREATE INDEX idx_performance_player ON fact_match_performance(player_id);
CREATE INDEX idx_overall_stats_match ON fact_match_overall_stats(match_id);
CREATE INDEX idx_economy_match ON fact_match_economy(match_id);
