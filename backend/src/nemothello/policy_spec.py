"""Serialization identifiers shared by research commands and saved reports."""

import string

SYMBOLS = string.ascii_uppercase + string.ascii_lowercase
TEMPLATE_VERSION = "othello-candidates-v1"
FEATURE_TEMPLATE_VERSION = "othello-rule-features-v1"
TEMPLATE_VERSIONS = (TEMPLATE_VERSION, FEATURE_TEMPLATE_VERSION)
SCORING_MODE = "candidate-batch-1d"
GENERATION_MODE = "single-token-generation"
POLICY_MODES = (GENERATION_MODE, SCORING_MODE)
GENERATION_SETTINGS = {"temperature": 0, "seed": 42, "max_tokens": 1}
