from research_decision_engine.policies import GreedyPredictedPerformancePolicy, RandomPolicy
from research_decision_engine.types import ExperimentRecord
from research_decision_engine.world import DeterministicSyntheticWorld


def test_random_policy_is_reproducible() -> None:
    candidates = DeterministicSyntheticWorld().candidates()

    left = RandomPolicy(seed=11).select(candidates, [])
    right = RandomPolicy(seed=11).select(candidates, [])

    assert left == right


def test_greedy_policy_avoids_completed_candidate() -> None:
    world = DeterministicSyntheticWorld()
    candidates = world.candidates()
    observed_value, true_value, cost = world.evaluate(candidates[0])
    history = [
        ExperimentRecord.new(
            candidate=candidates[0],
            policy="greedy",
            observed_value=observed_value,
            true_value=true_value,
            cost=cost,
        )
    ]

    selected = GreedyPredictedPerformancePolicy().select(candidates, history)

    assert selected.candidate_id != candidates[0].candidate_id
