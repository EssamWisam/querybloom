# Figure Annotations for LaTeX Paper

This document provides recommended LaTeX captions and descriptions for the generated diversity analysis figures comparing the **QueryBloom** generated dataset with the **DBpedia QALD-9** baseline.

---

## 1. SPARQL Feature Distribution (`feature-dist.png`)

**LaTeX Caption:**
```latex
\begin{figure}[t]
    \centering
    \includegraphics[width=\linewidth]{figures/feature-dist.png}
    \caption{Distribution of SPARQL 1.1 features across QueryBloom (Blue) and DBpedia QALD-9 (Orange). The y-axis represents the percentage of queries containing each respective feature. QueryBloom maintains competitive structural complexity, particularly in its use of [specific features, e.g., FILTER, OPTIONAL].}
    \label{fig:sparql_features}
\end{figure}
```

**Description for Analysis:**
This bar chart compares the use of SPARQL 1.1 operators (OPTIONAL, UNION, FILTER, GROUP BY, ORDER BY / LIMIT, and Property Paths). It demonstrates that QueryBloom is capable of generating queries with a feature distribution that closely mirrors or exceeds the structural variety found in human-authored benchmarks like QALD-9.

---

## 2. Semantic Embedding Space (`embeddings.png`)

**LaTeX Caption:**
```latex
\begin{figure}[t]
    \centering
    \includegraphics[width=\linewidth]{figures/embeddings.png}
    \caption{t-SNE visualization of the semantic embedding space for questions in QueryBloom (Blue) and DBpedia QALD-9 (Orange). APD denotes Average Pairwise Distance, and MNND represents Mean Nearest-Neighbour Distance. The broader spread of QueryBloom points (higher APD/MNND) indicates a more diverse set of natural language questions compared to the baseline.}
    \label{fig:semantic_space}
\end{figure}
```

**Description for Analysis:**
This figure visualizes the semantic spread of the natural language questions using SBERT (BGE-large) embeddings reduced to 2D via t-SNE. APD (Average Pairwise Distance) measures global diversity, while MNND (Mean Nearest-Neighbour Distance) captures the local density. QueryBloom's superior APD suggests it covers a wider range of linguistic intents and vocabulary than the fixed QALD-9 test set.

---

## 3. Holistic Diversity Radar (`radar_summary.png`)

**LaTeX Caption:**
```latex
\begin{figure}[t]
    \centering
    \includegraphics[width=0.8\linewidth]{figures/radar_summary.png}
    \caption{Holistic benchmarking diversity space comparing QueryBloom (Blue) and DBpedia QALD-9 (Orange). The radar chart normalizes unique entities/relations per query, median variables/triples, and the unique template ratio. QueryBloom demonstrates broader coverage across the schema and higher structural complexity per query.}
    \label{fig:radar_summary}
\end{figure}
```

**Description for Analysis:**
The radar chart provides a multi-dimensional summary of dataset diversity. It includes:
- **Unique Entities/Relations:** Average number of unique schema elements per query.
- **Variables/Triples:** Median structural size of the SPARQL queries.
- **Unique Templates:** The ratio of unique query structures to total queries. QueryBloom's performance here highlights its ability to generate novel query patterns rather than simple variations of a few templates.
