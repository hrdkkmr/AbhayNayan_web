"""Image-model inference: decoding, quality checks, colour features and artifact registry.

`features.py` is the single preprocessing definition. Training scripts (`scripts/ml/`) import it,
and the Android port (`core/ColourFeatures.kt` in AbhayNayan_apk) is checked against golden vectors
produced by `scripts/ml/export_golden_vectors.py`.
"""
