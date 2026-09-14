# QueryBloom Subgraph Mining

This module powers QueryBloom's frequent subgraph mining workflow for knowledge graphs.

## Live Frontend In Docker

The public frontend uses SvelteKit's Vite development server with HMR. This is an
intentional single-user development deployment, not a hardened production server.
Source edits under `webapp/src` appear automatically in an open browser. No
frontend build or backend restart is needed. Vite can reload the page for changes
that cannot be hot-updated, so avoid editing during critical browser operations.

Start the frontend alongside the existing backend:

```sh
docker compose up -d querybloom-frontend
```

It listens on `127.0.0.1:5174` and forwards API requests to
`querybloom-prod:8000`. The HTTPS proxy's `/querybloom/` location must preserve
the prefix and forward WebSockets:

```nginx
location /querybloom/ {
    proxy_pass http://127.0.0.1:5174;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_buffering off;
    proxy_read_timeout 86400s;
}
```

After dependency manifest changes, run
`docker compose restart querybloom-frontend` to reinstall dependencies. After
Compose configuration changes, run `docker compose up -d --no-deps querybloom-frontend`.
The frontend installs locked dependencies on startup and restarts automatically
with Docker. Backend reload behavior is unchanged. The static bundle served on
port 8002 remains available but is not used by the public frontend after the proxy
is switched to Vite.

## Overview

- **ABSTAT**: Extracts frequent (subject_type, predicate, object_type) patterns from a knowledge graph
- **SubgraphMiner**: Uses ABSTAT patterns to discover connected subgraphs with configurable size and support thresholds

---

## How QueryBloom Subgraph Mining Works

### 1. Starting Point: Frequent Patterns from ABSTAT

The miner starts with **frequent patterns** (subject_type, predicate, object_type) that appear at least `min_support` times. Think of these as "edges" in a type-level graph:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#1e293b', 'primaryTextColor': '#ffffff', 'lineColor': '#64748b', 'edgeLabelBackground': 'transparent', 'fontSize': '14px'}, 'flowchart': {'padding': 24}}}%%
graph TB
    subgraph pool ["&ensp; Pattern Pool &ensp;"]
        direction TB

        subgraph p1 ["count: 500"]
            direction LR
            A1["Person"]:::type -->|worksAt| A2["Organization"]:::type
        end

        subgraph p2 ["count: 300"]
            direction LR
            B1["Organization"]:::type -->|locatedIn| B2["City"]:::type
        end

        subgraph p3 ["count: 450"]
            direction LR
            C1["Person"]:::type -->|livesIn| C2["City"]:::type
        end

        subgraph p4 ["count: 800 ↻"]
            direction LR
            D1["Person"]:::type -->|knows| D2["Person"]:::type
        end

        subgraph p5 ["count: 200"]
            direction LR
            E1["City"]:::type -->|partOf| E2["Country"]:::type
        end

        subgraph p6 ["count: 400"]
            direction LR
            F1["Organization"]:::type -->|hasEmployee| F2["Person"]:::type
        end
    end

    p1 ~~~ p2
    p2 ~~~ p3
    p3 ~~~ p4
    p4 ~~~ p5
    p5 ~~~ p6

    classDef type fill:#1e3a5f,stroke:#3b82f6,stroke-width:1.5px,color:#e2e8f0
    style pool fill:#1e293b,stroke:#3b82f6,stroke-width:2px,color:#e2e8f0
    style p1 fill:#0f172a,stroke:#334155,color:#94a3b8
    style p2 fill:#0f172a,stroke:#334155,color:#94a3b8
    style p3 fill:#0f172a,stroke:#334155,color:#94a3b8
    style p4 fill:#0f172a,stroke:#334155,color:#94a3b8
    style p5 fill:#0f172a,stroke:#334155,color:#94a3b8
    style p6 fill:#0f172a,stroke:#334155,color:#94a3b8
```

### 2. Building the Adjacency Index

For fast lookups, patterns are indexed by their types so that when we have a partial subgraph with type `T`, we can instantly find all patterns that touch `T`:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#1e293b', 'primaryTextColor': '#ffffff', 'lineColor': '#64748b', 'edgeLabelBackground': 'transparent'}}}%%
graph TB
    subgraph adj_person ["adj[Person]"]
        direction TB
        subgraph ap1 [" "]
            direction LR
            PA1["Person"]:::type -->|worksAt| PA2["Org"]:::type
        end
        subgraph ap2 [" "]
            direction LR
            PB1["Person"]:::type -->|livesIn| PB2["City"]:::type
        end
        subgraph ap3 [" "]
            direction LR
            PC1["Person"]:::type -->|knows| PC2["Person"]:::type
        end
        subgraph ap4 [" "]
            direction LR
            PD1["Org"]:::type -->|hasEmployee| PD2["Person"]:::type
        end
    end

    subgraph adj_org ["adj[Organization]"]
        direction TB
        subgraph ao1 [" "]
            direction LR
            OA1["Person"]:::type -->|worksAt| OA2["Org"]:::type
        end
        subgraph ao2 [" "]
            direction LR
            OB1["Org"]:::type -->|locatedIn| OB2["City"]:::type
        end
        subgraph ao3 [" "]
            direction LR
            OC1["Org"]:::type -->|hasEmployee| OC2["Person"]:::type
        end
    end

    subgraph adj_city ["adj[City]"]
        direction TB
        subgraph ac1 [" "]
            direction LR
            CA1["Org"]:::type -->|locatedIn| CA2["City"]:::type
        end
        subgraph ac2 [" "]
            direction LR
            CB1["Person"]:::type -->|livesIn| CB2["City"]:::type
        end
        subgraph ac3 [" "]
            direction LR
            CC1["City"]:::type -->|partOf| CC2["Country"]:::type
        end
    end

    adj_person ~~~ adj_org
    adj_org ~~~ adj_city

    classDef type fill:#1e3a5f,stroke:#3b82f6,stroke-width:1.5px,color:#e2e8f0
    style adj_person fill:#1e293b,stroke:#3b82f6,stroke-width:2px,color:#e2e8f0
    style adj_org fill:#1e293b,stroke:#3b82f6,stroke-width:2px,color:#e2e8f0
    style adj_city fill:#1e293b,stroke:#3b82f6,stroke-width:2px,color:#e2e8f0
    style ap1 fill:#0f172a,stroke:#334155,color:#94a3b8
    style ap2 fill:#0f172a,stroke:#334155,color:#94a3b8
    style ap3 fill:#0f172a,stroke:#334155,color:#94a3b8
    style ap4 fill:#0f172a,stroke:#334155,color:#94a3b8
    style ao1 fill:#0f172a,stroke:#334155,color:#94a3b8
    style ao2 fill:#0f172a,stroke:#334155,color:#94a3b8
    style ao3 fill:#0f172a,stroke:#334155,color:#94a3b8
    style ac1 fill:#0f172a,stroke:#334155,color:#94a3b8
    style ac2 fill:#0f172a,stroke:#334155,color:#94a3b8
    style ac3 fill:#0f172a,stroke:#334155,color:#94a3b8
```

### 3. DFS Mining Process (Finding k=3 types)

#### Step 1: Initialize Stack with Base Patterns

Each single pattern becomes a candidate subgraph. The patterns are **shuffled** for random start order:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#1e293b', 'primaryTextColor': '#ffffff', 'edgeLabelBackground': 'transparent'}}}%%
graph TB
    subgraph stack ["&ensp; Stack (shuffled) &ensp;"]
        direction TB
        subgraph s1 [" "]
            direction LR
            S1A["Person"]:::type -->|worksAt| S1B["Organization"]:::type
        end
        subgraph s2 [" "]
            direction LR
            S2A["Organization"]:::type -->|locatedIn| S2B["City"]:::type
        end
        subgraph s3 [" "]
            direction LR
            S3A["Person"]:::type -->|livesIn| S3B["City"]:::type
        end
        S4["⋮"]
    end

    classDef type fill:#1e3a5f,stroke:#3b82f6,stroke-width:1.5px,color:#e2e8f0
    style stack fill:#1e293b,stroke:#3b82f6,stroke-width:2px,color:#e2e8f0
    style s1 fill:#0f172a,stroke:#334155,color:#94a3b8
    style s2 fill:#0f172a,stroke:#334155,color:#94a3b8
    style s3 fill:#0f172a,stroke:#334155,color:#94a3b8
    style S4 fill:#0f172a,stroke:#334155,color:#94a3b8
```

#### Step 2: Pop and Extend

Pop: `{Person, Organization}` with edge `Person --worksAt--> Organization`

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#1e293b', 'primaryTextColor': '#ffffff', 'lineColor': '#3b82f6', 'edgeLabelBackground': 'transparent'}}}%%
graph LR
    P["<b>Person</b>"]:::typeNode -->|worksAt| O["<b>Organization</b>"]:::typeNode

    classDef typeNode fill:#1e3a5f,stroke:#3b82f6,stroke-width:2px,color:#e2e8f0,font-weight:bold
```

Current subgraph has **2 types**, but we need **3**. Find extensions by looking at `adj[Person]` and `adj[Organization]`:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#1e293b', 'primaryTextColor': '#ffffff', 'lineColor': '#64748b', 'edgeLabelBackground': 'transparent'}}}%%
graph TB
    subgraph ext ["&ensp; Candidate Extensions &ensp;"]
        direction TB
        subgraph e1 ["✚ adds new type"]
            direction LR
            E1A["Org"]:::type -->|locatedIn| E1B["City"]:::newType
        end
        subgraph e2 ["✚ adds new type"]
            direction LR
            E2A["Person"]:::type -->|livesIn| E2B["City"]:::newType
        end
        subgraph e3 ["↻ adds structure only"]
            direction LR
            E3A["Org"]:::type -->|hasEmployee| E3B["Person"]:::dimType
        end
    end

    e1 ~~~ e2
    e2 ~~~ e3

    classDef type fill:#1e3a5f,stroke:#3b82f6,stroke-width:1.5px,color:#e2e8f0
    classDef newType fill:#1e3a5f,stroke:#f59e0b,stroke-width:2px,color:#fbbf24
    classDef dimType fill:#1e293b,stroke:#334155,stroke-width:1.5px,color:#64748b
    style ext fill:#1e293b,stroke:#3b82f6,stroke-width:2px,color:#e2e8f0
    style e1 fill:#0f172a,stroke:#60a5fa,color:#93c5fd
    style e2 fill:#0f172a,stroke:#60a5fa,color:#93c5fd
    style e3 fill:#0f172a,stroke:#334155,color:#64748b
```

#### Step 3: Push Extended Candidates

One possible extension extends the subgraph to 3 types:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#1e293b', 'primaryTextColor': '#ffffff', 'lineColor': '#3b82f6', 'edgeLabelBackground': 'transparent'}}}%%
graph TD
    P["<b>Person</b>"]:::existingType -->|worksAt| O["<b>Organization</b>"]:::existingType
    O -->|locatedIn| C["<b>City</b> ✦ new"]:::newType

    classDef existingType fill:#1e3a5f,stroke:#3b82f6,stroke-width:2px,color:#e2e8f0
    classDef newType fill:#1e3a5f,stroke:#f59e0b,stroke-width:2px,color:#fbbf24
```

> **types = {Person, Organization, City} — k=3 REACHED ✓**

#### Step 4: Verify Support with SPARQL

Before accepting, the algorithm verifies the **combined pattern** has enough instances:

```sparql
SELECT (COUNT(*) as ?count) WHERE {
    ?v0 a <City> .
    ?v1 a <Organization> .
    ?v2 a <Person> .
    ?v2 <worksAt> ?v1 .
    ?v1 <locatedIn> ?v0 .
}
```

This counts **actual embeddings** in the KG—real entities matching this structure.

- If `count >= min_support` → edge is **required** ✓
- If `1 <= count < min_support` and optional slots remain → edge is marked **optional** (shown with `*`)
- If `count = 0` → candidate is **pruned**

#### Step 5: Sample Entity Instances

Once a subgraph is accepted, the miner fetches **`m` real entity instances per type** that satisfy the subgraph pattern. It issues a SPARQL query that matches all the type and edge constraints, then samples up to `m` distinct entities for each type from the result. These concrete entities (with their URIs and labels) are included in the YAML output and are later used to ground the question generation.

**Pattern Template:**

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#1e293b', 'primaryTextColor': '#ffffff', 'lineColor': '#3b82f6', 'edgeLabelBackground': 'transparent'}}}%%
graph LR
    P["Person"]:::typeNode -->|worksAt| O["Organization"]:::typeNode
    O -->|locatedIn| C["City"]:::typeNode

    classDef typeNode fill:#1e3a5f,stroke:#3b82f6,stroke-width:2px,color:#e2e8f0
```

**↓ Sample m examples ↓**
```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#1e293b', 'primaryTextColor': '#ffffff', 'lineColor': '#3b82f6', 'edgeLabelBackground': 'transparent'}}}%%
graph TB
    subgraph i1 ["Instance 1"]
        direction LR
        P1["John Doe"]:::entity -->|worksAt| O1["ACME Corp"]:::entity
        O1 -->|locatedIn| C1["Austin"]:::entity
    end
    
    subgraph i2 ["Instance 2"]
        direction LR
        P2["Jane Smith"]:::entity -->|worksAt| O2["TechStart Inc"]:::entity
        O2 -->|locatedIn| C2["Seattle"]:::entity
    end
    
    subgraph i3 ["Instance 3"]
        direction LR
        P3["Bob Lee"]:::entity -->|worksAt| O3["ACME Corp"]:::entity
        O3 -->|locatedIn| C3["Austin"]:::entity
    end

    i1 ~~~ i2
    i2 ~~~ i3

    iMore["⋮"]

    classDef entity fill:#0f172a,stroke:#60a5fa,stroke-width:1.5px,color:#93c5fd
    style i1 fill:#0f172a,stroke:#334155,color:#94a3b8
    style i2 fill:#0f172a,stroke:#334155,color:#94a3b8
    style i3 fill:#0f172a,stroke:#334155,color:#94a3b8
    style iMore fill:#0f172a,stroke:#334155,color:#94a3b8
```

#### Step 6: Find & Attach Attributes

The miner then optionally discovers **data attributes** (entity → literal edges) for each type. Attributes are sampled from ABSTAT's `attribute_counts` and verified via SPARQL. The actual values are fetched for each sampled entity:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#1e293b', 'primaryTextColor': '#ffffff', 'lineColor': '#3b82f6', 'edgeLabelBackground': 'transparent'}}}%%
graph LR
    P["John Doe"]:::entity -->|worksAt| O["ACME Corp"]:::entity
    O -->|locatedIn| C["Austin"]:::entity

    P -.->|"age = 32"| A1((" ")):::attrDot
    P -.->|"birthDate = '1993-05-12'"| A2((" ")):::attrDot
    O -.->|"revenue = 1500000.0"| A3((" ")):::attrDot
    O -.->|"name* = 'ACME'"| A4((" ")):::optAttrDot
    C -.->|"population = 950000"| A5((" ")):::attrDot

    classDef entity fill:#0f172a,stroke:#60a5fa,stroke-width:1.5px,color:#93c5fd
    classDef attrDot fill:#312e81,stroke:#6366f1,color:#c7d2fe,font-size:10px
    classDef optAttrDot fill:#0f172a,stroke:#f59e0b,stroke-dasharray:5 5,color:#fbbf24,font-size:10px
```

- Solid dashed lines = required attributes (support ≥ `min_support`)
- Dashed lines with `*` = optional attributes (support ≥ 1 but < `min_support`)
- `num_attrs` parameter controls how many attributes are sampled

### 4. Visual Example of a Complete Found Subgraph

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#1e293b', 'primaryTextColor': '#ffffff', 'lineColor': '#3b82f6', 'edgeLabelBackground': 'transparent'}}}%%
graph TD
    subgraph sg ["SUBGRAPH #1 — support: 150 — 3 types"]
        P["Person"]:::typeNode -->|"worksAt (500)"| O["Organization"]:::typeNode
        O -->|"locatedIn (300)"| C["City"]:::typeNode
        O -.-|"hasSubsidiary (30) *"| O2["Organization"]:::typeNode
        P -.-|"age : integer"| A1((" ")):::attrDot
        C -.-|"population : long"| A2((" ")):::attrDot
    end

    classDef typeNode fill:#1e3a5f,stroke:#3b82f6,stroke-width:2px,color:#e2e8f0
    classDef attrDot fill:#312e81,stroke:#6366f1,color:#c7d2fe,font-size:10px
    style sg fill:#1e293b,stroke:#3b82f6,stroke-width:2px,color:#e2e8f0
```

- **Solid arrows** = required edges (support ≥ `min_support`)
- **Dashed arrow with `*`** = optional edge (support ≥ 1 but below threshold)
- **Dashed lines to dots** = data attributes (entity → literal)

### 5. Diversity via Seed Limits & Randomness

To prevent the miner from getting "stuck" returning many variations of the same pattern (e.g., 20 variations of movie subgraphs), we calculate which **initial pattern (seed)** each candidate originated from.

*   Each time a valid subgraph is found, we increment a counter for its seed.
*   If `seed_usage[seed] >= max_subgraphs_per_seed`, we stop exploring paths from that seed.
*   Moreover, we allow random popping from the stack
This forces the miner to move on to other parts of the Knowledge Graph (other seeds) once it has harvested enough from the current topic.

### 6. Output: YAML with Entity Samples & Attributes

For each found subgraph, real entities are sampled and attribute values are fetched:

```yaml
subgraph_id: 1
num_types: 3
min_support: 150
types:
  Person:
    uri: http://example.org/Person
    sample_entities:
      - uri: http://example.org/person/john_doe
        label: "John Doe"
        attributes: "(age:integer=32, birthDate:date='1993-05-12')"
      - uri: http://example.org/person/jane_smith
        label: "Jane Smith"
        attributes: "(age:integer=28)"
  Organization:
    uri: http://example.org/Organization
    sample_entities:
      - uri: http://example.org/org/acme_corp
        label: "ACME Corp"
        attributes: "(revenue:decimal=1500000.0, name*:string='ACME')"
edges:
  - "Person --worksAt --> Organization"
  - "Organization --locatedIn --> City"
  - "Organization --hasSubsidiary -->* Organization"    # optional edge
predicate_uris:
  - http://example.org/worksAt
  - http://example.org/locatedIn
  - http://example.org/hasSubsidiary
```

---

---


## Usage

```python
from querybloom.subgraph_miner import SubgraphMiner

# Initialize Miner (automatically initializes ABSTAT)
miner = SubgraphMiner(endpoint="http://your-sparql-endpoint/sparql", min_support=100)

# Run preprocessing to extract patterns
# property_limit: number of predicates to analyze
# max_triples: how many triples to sample per predicate
miner.preprocess(property_limit=300, max_triples=50000)

# Mine subgraphs with at least 3 types
subgraphs = miner.mine(
    k=3,                          # Minimum number of types
    num_subgraphs=5,              # Number of subgraphs to find
    prob_optional=0.3,            # 30% of subgraphs should have optional edges
    max_subgraphs_per_seed=1,     # Max subgraphs allowed per initial seed pattern
    exact_support=False,          # Use LIMIT optimization
    verif_timeout=5,              # Timeout for SPARQL support checks
    m=5,                          # Sample entities per type
    num_attrs=(1, 3),             # 1-3 attributes per subgraph
    output_dir="subgraphs_output" # Save YAMLs here
)
```

## Parameters

| Parameter | Description |
|-----------|-------------|
| `k` | Number of types in the subgraph. Int (exact) or tuple `(min, max)` for a range |
| `num_subgraphs` | Maximum number of subgraphs to discover |
| `max_subgraphs_per_seed` | Max successful subgraphs allowed from a single start pattern |
| `exact_support` | If `True`, computes exact support (slower) |
| `verif_timeout` | Timeout in seconds for support verification SPARQL queries |
| `prob_optional` | Fraction of results to include optional edges (0.0 - 1.0) |
| `num_attrs` | Number of data attributes per subgraph. Int or tuple `(min, max)` for a range |
| `strategy` | `"rand"` (random pop) or `"dfs"` (stack top) |
| `m` | Number of sample entities to fetch per type |
| `output_dir` | Directory to save YAML files (optional) |
