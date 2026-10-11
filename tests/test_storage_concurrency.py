"""Threaded status/database work must preserve durable usage limits."""
from concurrent.futures import ThreadPoolExecutor

from app.domain.workflow import WorkflowState
from app.services.limits import LimitExceeded, Limits


def test_parallel_database_calls_respect_the_same_saved_budget(make_run_manager):
    setup = make_run_manager()
    setup.repository.save_run(WorkflowState(run_id='parallel-budget', goal='Test the saved budget'), 'running')
    limits = Limits(max_model_calls=10, estimated_cost_per_call=0.05, max_estimated_cost_per_run=0.50)
    def attempt(_):
        try:
            setup.repository.reserve_call('parallel-budget', 'model', limits)
            return True
        except LimitExceeded:
            return False
    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = list(executor.map(attempt, range(20)))
    assert outcomes.count(True) == 10 and outcomes.count(False) == 10
    saved = setup.repository.run('parallel-budget')
    assert saved['model_calls'] == 10
    assert abs(saved['estimated_cost'] - 0.50) < 1e-9
