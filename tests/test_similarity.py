"""
Unit tests for Element 3: Similarity Modeling.
Validates PCA explained variance threshold, cosine similarity range [-1, 1],
self-similarity diagonal == 1.0, and symmetry.
"""
import numpy as np
import pytest
from sklearn.decomposition import PCA
from sklearn.metrics.pairwise import cosine_similarity


def test_pca_variance_threshold_retention():
    # Synthetic dataset with 20 players and 10 features
    np.random.seed(42)
    X = np.random.randn(20, 10)

    threshold = 0.90
    max_components = min(X.shape[0], X.shape[1])
    pca = PCA(n_components=max_components)
    pca.fit(X)

    cumsum = np.cumsum(pca.explained_variance_ratio_)
    k = int(np.argmax(cumsum >= threshold) + 1)
    k = min(k, max_components)

    pca_reduced = PCA(n_components=k)
    X_reduced = pca_reduced.fit_transform(X)

    # Explained variance should be at least threshold or 1.0 if k saturated
    total_var = np.sum(pca_reduced.explained_variance_ratio_)
    assert total_var >= threshold or k == max_components
    assert X_reduced.shape == (20, k)


def test_cosine_similarity_properties():
    # 5 player vectors
    np.random.seed(42)
    X = np.random.randn(5, 4)

    sim = cosine_similarity(X)

    # 1. Diagonal must be 1.0 (self-similarity)
    diag = np.diag(sim)
    assert np.allclose(diag, 1.0, atol=1e-5)

    # 2. Symmetry: sim[i, j] == sim[j, i]
    assert np.allclose(sim, sim.T, atol=1e-5)

    # 3. Value range: -1.0 <= score <= 1.0
    assert np.all(sim >= -1.0001)
    assert np.all(sim <= 1.0001)


def test_identical_profiles_max_similarity():
    # Two identical players should have similarity score = 1.0
    player_a = np.array([[1.5, -0.8, 2.1, 0.4]])
    player_b = np.array([[1.5, -0.8, 2.1, 0.4]])

    sim = cosine_similarity(player_a, player_b)[0, 0]
    assert pytest.approx(sim, 1e-5) == 1.0
