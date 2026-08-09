from research_decision_engine.world import DeterministicSyntheticWorld


def test_world_candidates_and_evaluation_are_deterministic() -> None:
    world = DeterministicSyntheticWorld()
    first_candidates = world.candidates()
    second_candidates = world.candidates()

    assert first_candidates == second_candidates
    assert len(first_candidates) == 72

    first_eval = world.evaluate(first_candidates[0])
    second_eval = world.evaluate(first_candidates[0])

    assert first_eval == second_eval
