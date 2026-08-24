Is meaningful: True
Verification: correct (iteration 2)
Most meaningful pair index: 4

============================================================
Pair 1
============================================================
Original Q: Which space missions used Titan IIIE as the launch vehicle?
Original SPARQL:
PREFIX dbo: <http://dbpedia.org/ontology/>
PREFIX dbr: <http://dbpedia.org/resource/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT ?mission ?missionLabel WHERE {
  ?mission rdf:type dbo:SpaceMission ;
           dbo:launchVehicle dbr:Titan_IIIE .
  OPTIONAL { ?mission rdfs:label ?missionLabel FILTER (lang(?missionLabel) = 'en') }
}
ORDER BY ?missionLabel

[+Complexity: ['UNION']]
Post-Complexity Q: Which space missions used Titan IIIE or Titan IIIB as the launch vehicle?
Post-Complexity SPARQL:
PREFIX dbo: <http://dbpedia.org/ontology/>
PREFIX dbr: <http://dbpedia.org/resource/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT ?mission ?missionLabel WHERE {
  {
    ?mission rdf:type dbo:SpaceMission ;
             dbo:launchVehicle dbr:Titan_IIIE .
  } UNION {
    ?mission rdf:type dbo:SpaceMission ;
             dbo:launchVehicle dbr:Titan_IIIB .
  }
  OPTIONAL { ?mission rdfs:label ?missionLabel FILTER (lang(?missionLabel) = 'en') }
}
ORDER BY ?missionLabel

[Verify: correct] 

Final Q: Which space missions used Titan IIIE or Titan IIIB as the launch vehicle?
Final SPARQL:
PREFIX dbo: <http://dbpedia.org/ontology/>
PREFIX dbr: <http://dbpedia.org/resource/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT ?mission ?missionLabel WHERE {
  {
    ?mission rdf:type dbo:SpaceMission ;
             dbo:launchVehicle dbr:Titan_IIIE .
  } UNION {
    ?mission rdf:type dbo:SpaceMission ;
             dbo:launchVehicle dbr:Titan_IIIB .
  }
  OPTIONAL { ?mission rdfs:label ?missionLabel FILTER (lang(?missionLabel) = 'en') }
}
ORDER BY ?missionLabel
Exec: success=True | count=6

============================================================
Pair 2
============================================================
Original Q: What country is the launch vehicle Vega (rocket) from?
Original SPARQL:
PREFIX dbo: <http://dbpedia.org/ontology/>
PREFIX dbr: <http://dbpedia.org/resource/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT ?country ?countryLabel WHERE {
  dbr:Vega_(rocket) rdf:type dbo:Rocket ;
                     dbo:countryOrigin ?country .
  OPTIONAL { ?country rdfs:label ?countryLabel FILTER (lang(?countryLabel) = 'en') }
}

[+Complexity: ['SUBQUERY']]
Post-Complexity Q: What country is the launch vehicle Vega (rocket) from, and how many space missions have used it as their launch vehicle?
Post-Complexity SPARQL:
PREFIX dbo: <http://dbpedia.org/ontology/>
PREFIX dbr: <http://dbpedia.org/resource/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT ?country ?countryLabel ?missionsUsed WHERE {
  dbr:Vega_(rocket) rdf:type dbo:Rocket ;
                     dbo:countryOrigin ?country .
  OPTIONAL { ?country rdfs:label ?countryLabel FILTER (lang(?countryLabel) = 'en') }
  {
    SELECT (COUNT(DISTINCT ?m) AS ?missionsUsed) WHERE {
      ?m rdf:type dbo:SpaceMission ;
         dbo:launchVehicle dbr:Vega_(rocket) .
    }
  }
}

[Verify: correct] 

[Reword]
Before: Which country (or countries) is the launch vehicle Vega (rocket) from, and how many space missions have used it as their launch vehicle?
After:  Which country or countries does the Vega rocket originate from, and how many space missions have used it as their launch vehicle?
Reason: Contains KG-style disambiguation “Vega (rocket)”, which a domain expert wouldn’t use.
Final SPARQL:
PREFIX dbo: <http://dbpedia.org/ontology/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT ?country ?countryLabel ?missionsUsed WHERE {
  <http://dbpedia.org/resource/Vega_(rocket)> rdf:type dbo:Rocket ;
                                               dbo:countryOrigin ?country .
  ?country rdf:type dbo:Country .
  OPTIONAL { ?country rdfs:label ?countryLabel FILTER (lang(?countryLabel) = 'en') }
  {
    SELECT (COUNT(DISTINCT ?m) AS ?missionsUsed) WHERE {
      ?m rdf:type dbo:SpaceMission ;
         dbo:launchVehicle <http://dbpedia.org/resource/Vega_(rocket)> .
    }
  }
}
Exec: success=True | count=1

============================================================
Pair 3
============================================================
Original Q: Did any space mission use Vector-R as its launch vehicle?
Original SPARQL:
PREFIX dbo: <http://dbpedia.org/ontology/>
PREFIX dbr: <http://dbpedia.org/resource/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

ASK WHERE {
  ?mission rdf:type dbo:SpaceMission ;
           dbo:launchVehicle dbr:Vector-R .
}

[+Complexity: ['UNION']]
Post-Complexity Q: Did any space mission use Vector-R or Vega (rocket) as its launch vehicle?
Post-Complexity SPARQL:
PREFIX dbo: <http://dbpedia.org/ontology/>
PREFIX dbr: <http://dbpedia.org/resource/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

ASK WHERE {
  {
    ?mission rdf:type dbo:SpaceMission ;
             dbo:launchVehicle dbr:Vector-R .
  } UNION {
    ?mission rdf:type dbo:SpaceMission ;
             dbo:launchVehicle dbr:Vega_(rocket) .
  }
}

[Verify: correct] 

[Reword]
Before: Did any space mission use Vector-R or Vega (rocket) as its launch vehicle?
After:  Did any space mission use the Vector-R or the Vega rocket as its launch vehicle?
Reason: Contains KG-style disambiguation “Vega (rocket)”, which a domain expert wouldn’t use.
Final SPARQL:
PREFIX dbo: <http://dbpedia.org/ontology/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

ASK WHERE {
  {
    ?mission rdf:type dbo:SpaceMission ;
             dbo:launchVehicle <http://dbpedia.org/resource/Vector-R> .
  } UNION {
    ?mission rdf:type dbo:SpaceMission ;
             dbo:launchVehicle <http://dbpedia.org/resource/Vega_(rocket)> .
  }
}
Exec: success=True | count=0

============================================================
Pair 4
============================================================
Original Q: Which countries have the most rockets that have been used as launch vehicles for space missions? Return the top 5.
Original SPARQL:
PREFIX dbo: <http://dbpedia.org/ontology/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?country ?countryLabel (COUNT(DISTINCT ?rocket) AS ?rocketsUsed) WHERE {
  ?mission rdf:type dbo:SpaceMission ;
           dbo:launchVehicle ?rocket .
  ?rocket rdf:type dbo:Rocket ;
          dbo:countryOrigin ?country .
  OPTIONAL { ?country rdfs:label ?countryLabel FILTER (lang(?countryLabel) = 'en') }
}
GROUP BY ?country ?countryLabel
ORDER BY DESC(?rocketsUsed) ?countryLabel
LIMIT 5

[+Complexity: ['EXISTS']]
Post-Complexity Q: Considering only rockets whose origin is actually a country (and not an organization), which countries have the most rockets that have been used as launch vehicles for space missions? Return the top 5.
Post-Complexity SPARQL:
PREFIX dbo: <http://dbpedia.org/ontology/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?country ?countryLabel (COUNT(DISTINCT ?rocket) AS ?rocketsUsed) WHERE {
  ?mission rdf:type dbo:SpaceMission ;
           dbo:launchVehicle ?rocket .
  ?rocket rdf:type dbo:Rocket ;
          dbo:countryOrigin ?country .
  FILTER EXISTS { ?country rdf:type dbo:Country }
  OPTIONAL { ?country rdfs:label ?countryLabel FILTER (lang(?countryLabel) = 'en') }
}
GROUP BY ?country ?countryLabel
ORDER BY DESC(?rocketsUsed) ?countryLabel
LIMIT 5

[Verify: correct] 

Final Q: Considering only rockets whose origin is actually a country (and not an organization), which countries have the most rockets that have been used as launch vehicles for space missions? Return the top 5.
Final SPARQL:
PREFIX dbo: <http://dbpedia.org/ontology/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?country ?countryLabel (COUNT(DISTINCT ?rocket) AS ?rocketsUsed) WHERE {
  ?mission rdf:type dbo:SpaceMission ;
           dbo:launchVehicle ?rocket .
  ?rocket rdf:type dbo:Rocket ;
          dbo:countryOrigin ?country .
  FILTER EXISTS { ?country rdf:type dbo:Country }
  OPTIONAL { ?country rdfs:label ?countryLabel FILTER (lang(?countryLabel) = 'en') }
}
GROUP BY ?country ?countryLabel
ORDER BY DESC(?rocketsUsed) ?countryLabel
LIMIT 5
Exec: success=True | count=5




Is meaningful: True
Verification: correct (iteration None)

============================================================
Pair 1
============================================================
Original Q: Which automobiles are manufactured by the company that was the fastest driver team in the 1981 Monaco Grand Prix?
Original SPARQL:
PREFIX dbo: <http://dbpedia.org/ontology/>
PREFIX dbr: <http://dbpedia.org/resource/>
SELECT ?automobile WHERE {
  dbr:1981_Monaco_Grand_Prix dbo:fastestDriverTeam ?company .
  ?company a dbo:Company .
  ?automobile a dbo:Automobile ;
              dbo:manufacturer ?company .
}
[Verify: correct]
[Reword]
Before: Which automobiles are manufactured by the company that was the fastest driver team in the 1981 Monaco Grand Prix?
After:  Which automobiles are manufactured by the company whose driver set the fastest lap in the 1981 Monaco Grand Prix?
Reason: Uses the raw property name 'fastest driver team' literally, which is unnatural phrasing.
Final Q: Which automobiles are manufactured by the company whose driver set the fastest lap in the 1981 Monaco Grand Prix?
Final SPARQL:
PREFIX dbo: <http://dbpedia.org/ontology/>
PREFIX dbr: <http://dbpedia.org/resource/>
SELECT ?automobile WHERE {
  dbr:1981_Monaco_Grand_Prix dbo:fastestDriverTeam ?company .
  ?company a dbo:Company .
  ?automobile a dbo:Automobile ;
              dbo:manufacturer ?company .
}
Exec: success=None | count=None

============================================================
Pair 2
============================================================
Original Q: For each country, how many Grand Prix events had a first driver representing that country?
Original SPARQL:
PREFIX dbo: <http://dbpedia.org/ontology/>
SELECT ?country (COUNT(?gp) AS ?eventCount) WHERE {
  ?gp a dbo:GrandPrix ;
      dbo:firstDriverCountry ?country .
  ?country a dbo:Country .
} GROUP BY ?country
[+Complexity: ['ORDER_BY_LIMIT']]
Post-Complexity Q: Which top 5 countries had the highest number of Grand Prix events where the first driver represented that country?
Post-Complexity SPARQL:
PREFIX dbo: <http://dbpedia.org/ontology/>
SELECT ?country (COUNT(?gp) AS ?eventCount) WHERE {
  ?gp a dbo:GrandPrix ;
      dbo:firstDriverCountry ?country .
  ?country a dbo:Country .
} GROUP BY ?country
ORDER BY DESC(?eventCount) LIMIT 5
[Verify: correct]
[Reword]
Before: Which top 5 countries had the highest number of Grand Prix events where the first driver represented that country?
After:  Which 5 countries have had the highest number of Grand Prix races where the winning driver represented that country?
Reason: Uses 'first driver' as a literal translation of the property, which is unnatural for referring to the winning driver.
Final Q: Which 5 countries have had the highest number of Grand Prix races where the winning driver represented that country?
Final SPARQL:
PREFIX dbo: <http://dbpedia.org/ontology/>
SELECT ?country (COUNT(?gp) AS ?eventCount) WHERE {
  ?gp a dbo:GrandPrix ;
      dbo:firstDriverCountry ?country .
  ?country a dbo:Country .
} GROUP BY ?country
ORDER BY DESC(?eventCount) LIMIT 5
Exec: success=None | count=None

============================================================
Pair 3
============================================================
Original Q: Which Formula One racers were the first driver in a Grand Prix where the fastest driver team is also a company that manufactures automobiles?
Original SPARQL:
PREFIX dbo: <http://dbpedia.org/ontology/>
SELECT DISTINCT ?racer WHERE {
  ?gp a dbo:GrandPrix ;
      dbo:firstDriver ?racer ;
      dbo:fastestDriverTeam ?company .
  ?racer a dbo:FormulaOneRacer .
  ?company a dbo:Company .
  ?automobile a dbo:Automobile ;
              dbo:manufacturer ?company .
}
[+Complexity: ['OPTIONAL']]
Post-Complexity Q: Which Formula One racers were the first driver in a Grand Prix where the fastest driver team is also a company that manufactures automobiles, and what is the first driver country of that Grand Prix, if known?
Post-Complexity SPARQL:
PREFIX dbo: <http://dbpedia.org/ontology/>
SELECT DISTINCT ?racer ?country WHERE {
  ?gp a dbo:GrandPrix ;
      dbo:firstDriver ?racer ;
      dbo:fastestDriverTeam ?company .
  ?racer a dbo:FormulaOneRacer .
  ?company a dbo:Company .
  ?automobile a dbo:Automobile ;
              dbo:manufacturer ?company .
  OPTIONAL { 
    ?gp dbo:firstDriverCountry ?country .
    ?country a dbo:Country .
  }
}
[Verify: correct]
[Reword]
Before: Which Formula One racers were the first driver in a Grand Prix where the fastest driver team is also a company that manufactures automobiles, and what is the first driver country of that Grand Prix, if known?
After:  Which Formula One drivers won a Grand Prix where the team that set the fastest lap is an automobile manufacturing company, and what was the winning driver's nationality for that race, if known?
Reason: Highly unnatural and robotic phrasing that pieces together raw property names like 'first driver', 'fastest driver team', and 'first driver country'.
Final Q: Which Formula One drivers won a Grand Prix where the team that set the fastest lap is an automobile manufacturing company, and what was the winning driver's nationality for that race, if known?
Final SPARQL:
PREFIX dbo: <http://dbpedia.org/ontology/>
SELECT DISTINCT ?racer ?country WHERE {
  ?gp a dbo:GrandPrix ;
      dbo:firstDriver ?racer ;
      dbo:fastestDriverTeam ?company .
  ?racer a dbo:FormulaOneRacer .
  ?company a dbo:Company .
  ?automobile a dbo:Automobile ;
              dbo:manufacturer ?company .
  OPTIONAL { 
    ?gp dbo:firstDriverCountry ?country .
    ?country a dbo:Country .
  }
}
Exec: success=None | count=None