from nwb.tracks import Job, is_done
from nwb.util import write_json


def test_is_done_only_for_successful_results_of_the_same_job(tmp_path):
    out = tmp_path / "r.json"
    job = Job(out=out, label="x", base={"prompt": "new"}, fn=lambda: {})
    assert not is_done(job)
    write_json(out, {"prompt": "new", "error": "boom"})
    assert not is_done(job)
    write_json(out, {"prompt": "old", "answer": "a"})  # the prompt changed since this result was made
    assert not is_done(job)
    write_json(out, {"prompt": "new", "answer": "a"})
    assert is_done(job)
