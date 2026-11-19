-- Share of each tract covered by each 1930s HOLC grade.
-- Run from build_holc.py; it sets the input paths below by string
-- replacement. Areas use EPSG:5070 (US equal-area) so shares are true.
INSTALL spatial;
LOAD spatial;

CREATE TABLE tracts AS
SELECT GEOID AS geoid,
       ST_Transform(geom, 'EPSG:4269', 'EPSG:5070', always_xy := true) AS g
FROM (SELECT * FROM ST_Read('@GA@') UNION ALL SELECT * FROM ST_Read('@MI@'))
WHERE substr(GEOID, 1, 5) IN ('13089','13121','13063','26163','26125','26099');

-- Graded residential areas only; commercial/industrial have no grade.
CREATE TABLE holc AS
SELECT g AS grade,
       ST_Transform(ST_MakeValid(geom), 'EPSG:4326', 'EPSG:5070', always_xy := true) AS geom5070
FROM ST_Read('@HOLC@')
WHERE g IN ('A','B','C','D');

COPY (
  SELECT t.geoid, h.grade,
         sum(ST_Area(ST_Intersection(t.g, h.geom5070))) / any_value(ST_Area(t.g)) AS share
  FROM tracts t JOIN holc h ON ST_Intersects(t.g, h.geom5070)
  GROUP BY t.geoid, h.grade
  ORDER BY t.geoid, h.grade
) TO '@OUT@' (HEADER);
