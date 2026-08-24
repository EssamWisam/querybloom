import re
import numpy as np
import warnings
from collections import Counter

# Optional advanced NLP imports
try:
    from sentence_transformers import SentenceTransformer
    from sklearn.metrics.pairwise import cosine_similarity
    HAS_SBERT = True
    # Load a lightweight, fast model suitable for sentence embeddings
    sbert_model = SentenceTransformer('all-MiniLM-L6-v2') 
except ImportError:
    HAS_SBERT = False
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    warnings.warn("sentence_transformers not found. Falling back to TF-IDF for semantic similarity.")

try:
    import nltk
    from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
    HAS_BLEU = True
except ImportError:
    HAS_BLEU = False
    warnings.warn("nltk not found. Self-BLEU will not be calculated.")

try:
    import spacy
    # Load small english model. If not installed, this will throw OSError which we catch.
    try:
        nlp = spacy.load("en_core_web_sm")
        HAS_SPACY = True
    except OSError:
        HAS_SPACY = False
        warnings.warn("spacy model 'en_core_web_sm' not found. Syntactic complexity will be skipped.")
except ImportError:
    HAS_SPACY = False
    warnings.warn("spacy not found. Syntactic complexity will be skipped.")


def extract_basic_lexical_features(questions):
    """Extract lengths and TTR."""
    length_words = []
    length_chars = []
    all_words = []
    
    for text in questions:
        words = re.findall(r'\b\w+\b', text.lower())
        length_words.append(len(words))
        length_chars.append(len(text))
        all_words.extend(words)
        
    vocab_size = len(set(all_words))
    total_words = len(all_words)
    
    return {
        'length_words_mean': round(float(np.mean(length_words)), 3),
        'length_words_std': round(float(np.std(length_words)), 3),
        'length_chars_mean': round(float(np.mean(length_chars)), 3),
        'length_chars_std': round(float(np.std(length_chars)), 3),
        'vocab_size': vocab_size,
        'ttr': round(vocab_size / max(total_words, 1), 3)
    }

def compute_pairwise_semantic_distance(questions):
    """Compute average pairwise semantic distance."""
    if len(questions) < 2:
        return {'avg_semantic_distance': 0.0}
        
    try:
        if HAS_SBERT:
            embeddings = sbert_model.encode(questions)
            sim_matrix = cosine_similarity(embeddings)
        else:
            vectorizer = TfidfVectorizer()
            embeddings = vectorizer.fit_transform(questions)
            sim_matrix = cosine_similarity(embeddings)
            
        # Upper triangle without diagonal
        indices = np.triu_indices_from(sim_matrix, k=1)
        pairwise_sims = sim_matrix[indices]
        avg_sim = float(np.mean(pairwise_sims))
        
        return {
            'avg_semantic_distance': round(1.0 - avg_sim, 3)
        }
    except Exception as e:
        warnings.warn(f"Failed to compute semantic distance: {e}")
        return {'avg_semantic_distance': None}

def compute_self_bleu(questions):
    """Compute Self-BLEU to measure generation diversity (lower is more diverse)."""
    if not HAS_BLEU or len(questions) < 2:
        return {}
        
    tokenized_questions = [re.findall(r'\b\w+\b', q.lower()) for q in questions]
    bleu_scores = []
    smoother = SmoothingFunction().method1
    
    for i, hypothesis in enumerate(tokenized_questions):
        # All other questions are references
        references = tokenized_questions[:i] + tokenized_questions[i+1:]
        score = sentence_bleu(references, hypothesis, smoothing_function=smoother)
        bleu_scores.append(score)
        
    return {
        'self_bleu_mean': round(float(np.mean(bleu_scores)), 3),
        'self_bleu_std': round(float(np.std(bleu_scores)), 3)
    }

def compute_syntactic_complexity(questions):
    """Compute average parse tree depth and linguistic complexity using spaCy."""
    if not HAS_SPACY or not questions:
        return {}
        
    tree_depths = []
    noun_chunks_counts = []
    
    def get_depth(node):
        if not list(node.children):
            return 1
        return 1 + max(get_depth(child) for child in node.children)
        
    for doc in nlp.pipe(questions):
        # Tree depth from root
        roots = [token for token in doc if token.head == token]
        depth = max((get_depth(root) for root in roots), default=0)
        tree_depths.append(depth)
        
        # Noun chunks as a proxy for phrase density
        noun_chunks_counts.append(len(list(doc.noun_chunks)))
        
    return {
        'parse_tree_depth_mean': round(float(np.mean(tree_depths)), 3),
        'parse_tree_depth_std': round(float(np.std(tree_depths)), 3),
        'noun_chunks_per_question_mean': round(float(np.mean(noun_chunks_counts)), 3)
    }

def aggregate_text_diversity(questions):
    """Run all semantic and lexical diversity metrics on a set of questions."""
    if not questions:
        return {}
        
    metrics = {}
    metrics.update(extract_basic_lexical_features(questions))
    metrics.update(compute_pairwise_semantic_distance(questions))
    metrics.update(compute_self_bleu(questions))
    metrics.update(compute_syntactic_complexity(questions))
    
    return metrics

def measure_semantic_diversity(data1, data2):
    """
    Measure semantic diversity across two benchmarks.
    
    Args:
        data1 (list): List of dictionaries from first jsonl.
        data2 (list): List of dictionaries from second jsonl.
        
    Returns:
        dict: A dictionary containing semantic diversity metrics.
    """
    q1 = [item.get('question', '') for item in data1 if 'question' in item]
    q2 = [item.get('question', '') for item in data2 if 'question' in item]
    
    return {
        "benchmark1": aggregate_text_diversity(q1),
        "benchmark2": aggregate_text_diversity(q2),
        "bm1_size": len(q1),
        "bm2_size": len(q2)
    }
