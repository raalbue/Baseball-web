from django.db import migrations

STADIUMS_SQL = """
INSERT INTO stadium (stadium_id, name, city, state, country, capacity) VALUES
(1,  'Fenway Park',               'Boston',        'MA', 'USA', 37755),
(2,  'Yankee Stadium',            'New York',      'NY', 'USA', 46537),
(3,  'Citi Field',                'New York',      'NY', 'USA', 41922),
(4,  'Camden Yards',              'Baltimore',     'MD', 'USA', 44970),
(5,  'Tropicana Field',           'St. Petersburg','FL', 'USA', 25000),
(6,  'Rogers Centre',             'Toronto',       'ON', 'CAN', 49286),
(7,  'Guaranteed Rate Field',     'Chicago',       'IL', 'USA', 40615),
(8,  'Progressive Field',         'Cleveland',     'OH', 'USA', 34830),
(9,  'Comerica Park',             'Detroit',       'MI', 'USA', 41083),
(10, 'Kauffman Stadium',          'Kansas City',   'MO', 'USA', 37903),
(11, 'Target Field',              'Minneapolis',   'MN', 'USA', 38544),
(12, 'Minute Maid Park',          'Houston',       'TX', 'USA', 41168),
(13, 'Globe Life Field',          'Arlington',     'TX', 'USA', 40518),
(14, 'Angel Stadium',             'Anaheim',       'CA', 'USA', 45477),
(15, 'Oakland Coliseum',          'Oakland',       'CA', 'USA', 46765),
(16, 'T-Mobile Park',             'Seattle',       'WA', 'USA', 47929),
(17, 'Wrigley Field',             'Chicago',       'IL', 'USA', 41649),
(18, 'Busch Stadium',             'St. Louis',     'MO', 'USA', 44383),
(19, 'American Family Field',     'Milwaukee',     'WI', 'USA', 41900),
(20, 'PNC Park',                  'Pittsburgh',    'PA', 'USA', 38362),
(21, 'Great American Ball Park',  'Cincinnati',    'OH', 'USA', 42319),
(22, 'Truist Park',               'Cumberland',    'GA', 'USA', 41084),
(23, 'loanDepot Park',            'Miami',         'FL', 'USA', 37446),
(24, 'Nationals Park',            'Washington',    'DC', 'USA', 41339),
(25, 'Citizens Bank Park',        'Philadelphia',  'PA', 'USA', 42792),
(26, 'Dodger Stadium',            'Los Angeles',   'CA', 'USA', 56000),
(27, 'Petco Park',                'San Diego',     'CA', 'USA', 40162),
(28, 'Oracle Park',               'San Francisco', 'CA', 'USA', 41915),
(29, 'Chase Field',               'Phoenix',       'AZ', 'USA', 48519),
(30, 'Coors Field',               'Denver',        'CO', 'USA', 46897)
ON CONFLICT (stadium_id) DO NOTHING;
"""

TEAMS_SQL = """
INSERT INTO team (team_id, name, city, abbreviation, conference, division, head_coach, stadium_id, founded_year) VALUES
(1,  'Yankees',      'New York',      'NYY', 'American League', 'East',    'Aaron Boone',      2,  1901),
(2,  'Red Sox',      'Boston',        'BOS', 'American League', 'East',    'Alex Cora',        1,  1901),
(3,  'Orioles',      'Baltimore',     'BAL', 'American League', 'East',    'Brandon Hyde',     4,  1901),
(4,  'Rays',         'Tampa Bay',     'TB',  'American League', 'East',    'Kevin Cash',       5,  1998),
(5,  'Blue Jays',    'Toronto',       'TOR', 'American League', 'East',    'John Schneider',   6,  1977),
(6,  'White Sox',    'Chicago',       'CWS', 'American League', 'Central', 'Grady Sizemore',   7,  1900),
(7,  'Guardians',    'Cleveland',     'CLE', 'American League', 'Central', 'Stephen Vogt',     8,  1901),
(8,  'Tigers',       'Detroit',       'DET', 'American League', 'Central', 'A.J. Hinch',       9,  1901),
(9,  'Royals',       'Kansas City',   'KC',  'American League', 'Central', 'Matt Quatraro',    10, 1969),
(10, 'Twins',        'Minnesota',     'MIN', 'American League', 'Central', 'Rocco Baldelli',   11, 1901),
(11, 'Astros',       'Houston',       'HOU', 'American League', 'West',    'Joe Espada',       12, 1962),
(12, 'Rangers',      'Texas',         'TEX', 'American League', 'West',    'Bruce Bochy',      13, 1961),
(13, 'Angels',       'Anaheim',       'LAA', 'American League', 'West',    'Ron Washington',   14, 1961),
(14, 'Athletics',    'Oakland',       'OAK', 'American League', 'West',    'Mark Kotsay',      15, 1901),
(15, 'Mariners',     'Seattle',       'SEA', 'American League', 'West',    'Dan Wilson',       16, 1977),
(16, 'Braves',       'Atlanta',       'ATL', 'National League', 'East',    'Brian Snitker',    22, 1876),
(17, 'Marlins',      'Miami',         'MIA', 'National League', 'East',    'Skip Schumaker',   23, 1993),
(18, 'Mets',         'New York',      'NYM', 'National League', 'East',    'Carlos Mendoza',   3,  1962),
(19, 'Phillies',     'Philadelphia',  'PHI', 'National League', 'East',    'Rob Thomson',      25, 1883),
(20, 'Nationals',    'Washington',    'WSH', 'National League', 'East',    'Dave Martinez',    24, 1969),
(21, 'Cubs',         'Chicago',       'CHC', 'National League', 'Central', 'Craig Counsell',   17, 1876),
(22, 'Reds',         'Cincinnati',    'CIN', 'National League', 'Central', 'David Bell',       21, 1882),
(23, 'Brewers',      'Milwaukee',     'MIL', 'National League', 'Central', 'Pat Murphy',       19, 1969),
(24, 'Pirates',      'Pittsburgh',    'PIT', 'National League', 'Central', 'Derek Shelton',    20, 1882),
(25, 'Cardinals',    'St. Louis',     'STL', 'National League', 'Central', 'Oliver Marmol',    18, 1882),
(26, 'Diamondbacks', 'Arizona',       'ARI', 'National League', 'West',    'Torey Lovullo',    29, 1998),
(27, 'Rockies',      'Colorado',      'COL', 'National League', 'West',    'Bud Black',        30, 1993),
(28, 'Dodgers',      'Los Angeles',   'LAD', 'National League', 'West',    'Dave Roberts',     26, 1883),
(29, 'Padres',       'San Diego',     'SD',  'National League', 'West',    'Mike Shildt',      27, 1969),
(30, 'Giants',       'San Francisco', 'SF',  'National League', 'West',    'Bob Melvin',       28, 1883)
ON CONFLICT (team_id) DO NOTHING;
"""

REVERSE_SQL = """
DELETE FROM team WHERE team_id BETWEEN 1 AND 30;
DELETE FROM stadium WHERE stadium_id BETWEEN 1 AND 30;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("baseball", "0005_gamestat"),
    ]

    operations = [
        migrations.RunSQL(sql=STADIUMS_SQL + TEAMS_SQL, reverse_sql=REVERSE_SQL),
    ]
