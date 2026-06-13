"""The training task under the ablation — a tiny char-LM, refereed.

A real training loop at nano scale: an n-gram character language model with
add-k smoothing, fit on a train window, judged by held-out negative
log-likelihood (bits/char). Everything is seeded and stdlib-only, so one full
train+eval is milliseconds and a whole multi-arm ablation reproduces
byte-for-byte from one master seed.

The task is chosen for one property: it carries the REAL failure gradient a
self-certifying improver needs. Capacity mutations (order up, smoothing down)
always look better IN-SAMPLE — the model fits the data it can see more
sharply — and beyond the corpus's true structure they hurt HELD-OUT quality.
So a loop that grades its own homework (train-set fit) walks itself past the
optimum while honestly believing every step helped. That is the forgeable
channel `dos.improve` exists to ignore, reproduced in miniature.

Two channels, kept apart (the docs/138 split):

  * `in_sample_nll`  — the proposer's own estimate, computed on the window it
                       trained on. Agent-authored, systematically optimistic.
  * `heldout_nll` / `referee_nll` — the referee's measure on data the model
                       never saw, averaged over fresh seeded windows. The
                       bytes the proposer does not author.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, List, Tuple

ALPHABET = "abcdefghijklmnopqrstuvwxyz "
V = len(ALPHABET)

MAX_ORDER = 8
MIN_K, MAX_K = 1e-4, 8.0

TRAIN_CHARS = 6_000
VAL_CHARS = 4_000


# ---------------------------------------------------------------------------
# Corpus — a seeded pseudo-English source. Words built from syllables give the
# text learnable character structure up to roughly the word length; beyond it
# there is only noise to fit, so over-capacity models have something real to
# overfit. Deterministic from the seed; no bundled data file.
# ---------------------------------------------------------------------------
def make_corpus(seed: int, size: int = 120_000) -> str:
    rng = random.Random(seed)
    syllables = [c + v for c in "bcdfghklmnprstvw" for v in "aeiou"]
    rng.shuffle(syllables)
    vocab = []
    for _ in range(60):
        n = rng.randint(1, 3)
        vocab.append("".join(rng.choice(syllables) for _ in range(n)))
    weights = [1.0 / (i + 1) for i in range(len(vocab))]  # Zipf-ish ranks
    out: List[str] = []
    total = 0
    while total < size:
        w = rng.choices(vocab, weights)[0]
        out.append(w)
        total += len(w) + 1
    return " ".join(out)[:size]


# ---------------------------------------------------------------------------
# Recipe + model — the unit the loop mutates and the gate adjudicates.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Recipe:
    order: int  # context length, 1..MAX_ORDER
    add_k: float  # add-k smoothing constant, MIN_K..MAX_K

    def as_dict(self) -> dict:
        return {"order": self.order, "add_k": self.add_k}


Model = Tuple[Dict[str, int], Dict[Tuple[str, str], int]]


def train(recipe: Recipe, text: str) -> Model:
    """Count n-gram statistics — the whole 'training run' at this scale."""
    ctx_counts: Dict[str, int] = {}
    pair_counts: Dict[Tuple[str, str], int] = {}
    o = recipe.order
    for i in range(o, len(text)):
        ctx = text[i - o : i]
        ch = text[i]
        ctx_counts[ctx] = ctx_counts.get(ctx, 0) + 1
        pair_counts[(ctx, ch)] = pair_counts.get((ctx, ch), 0) + 1
    return ctx_counts, pair_counts


def nll_bits(model: Model, recipe: Recipe, text: str) -> float:
    """Mean negative log-likelihood of `text` under the model, in bits/char."""
    ctx_counts, pair_counts = model
    o, k = recipe.order, recipe.add_k
    total = 0.0
    n = 0
    for i in range(o, len(text)):
        ctx = text[i - o : i]
        num = pair_counts.get((ctx, text[i]), 0) + k
        den = ctx_counts.get(ctx, 0) + k * V
        total += -math.log2(num / den)
        n += 1
    return total / max(n, 1)


def windows(corpus: str, seed: int) -> Tuple[str, str]:
    """One seeded (train, val) pair of disjoint corpus windows. The seed is the
    noise source: different windows, different measured NLL."""
    rng = random.Random(seed)
    span = TRAIN_CHARS + VAL_CHARS
    start = rng.randrange(0, len(corpus) - span)
    return corpus[start : start + TRAIN_CHARS], corpus[start + span - VAL_CHARS : start + span]


def heldout_nll(corpus: str, recipe: Recipe, seed: int) -> float:
    """The witness channel, one sample: train on the seed's train window,
    measure on its held-out window."""
    tr, va = windows(corpus, seed)
    return nll_bits(train(recipe, tr), recipe, va)


def referee_nll(corpus: str, recipe: Recipe, seeds: List[int]) -> float:
    """The witness channel, averaged over independent seeded windows."""
    return sum(heldout_nll(corpus, recipe, s) for s in seeds) / len(seeds)


def in_sample_nll(corpus: str, recipe: Recipe, seed: int) -> float:
    """The forgeable channel: the model's fit on the very window it trained
    on — the proposer grading its own homework."""
    tr, _ = windows(corpus, seed)
    return nll_bits(train(recipe, tr), recipe, tr)


def work_points(ref_nll0: float, nll: float) -> int:
    """Map an NLL to the non-negative integer work unit `dos.improve` reads:
    milli-bits/char of improvement over the cycle-0 reference, floored at 0."""
    return max(0, round((ref_nll0 - nll) * 1000))


def mutate(recipe: Recipe, rng: random.Random) -> Tuple[Recipe, str]:
    """One recipe diff per cycle: perturb order or smoothing. Returns the
    candidate and a human-readable description of the step."""
    if rng.random() < 0.5:
        step = rng.choice([-1, 1])
        new_order = min(MAX_ORDER, max(1, recipe.order + step))
        if new_order == recipe.order:  # bounced off a bound — go the other way
            new_order = min(MAX_ORDER, max(1, recipe.order - step))
        return Recipe(new_order, recipe.add_k), f"order {recipe.order}->{new_order}"
    factor = rng.uniform(1.5, 4.0)
    if rng.random() < 0.5:
        factor = 1.0 / factor
    new_k = min(MAX_K, max(MIN_K, recipe.add_k * factor))
    return Recipe(recipe.order, round(new_k, 6)), f"add_k {recipe.add_k:g}->{new_k:g}"
